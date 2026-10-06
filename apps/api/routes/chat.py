"""Chats: create, list, read, delete, and ask a question (streamed as server-sent events).

The agent runs in a background task that saves the answer itself, so an answer is not lost
when the browser disconnects mid-stream.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Any

from arq import ArqRedis
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.agent.context import load_project_context
from api.agent.loop import Event, Outcome, run_agent
from api.agent.tools import ProjectContext, ToolBox, ToolError
from api.db.models import Chat, Message, Query
from api.db.session import get_sessionmaker
from api.limits import WithinAIBudget
from api.llm.client import LLMClient
from api.routes.deps import OwnedProject, Queue, Session
from api.routes.query import execute_logged
from api.semantic.column_retrieval import ColumnRetriever
from api.sql.executor import QueryResult

router = APIRouter(prefix="/projects/{project_id}/chats", tags=["chat"])

log = logging.getLogger(__name__)

NEW_CHAT_TITLE = "New chat"
_running: set[asyncio.Task[None]] = set()


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime


class ChatIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)


class QuestionIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class QueryOut(BaseModel):
    id: int
    sql: str
    row_count: int | None
    duration_ms: int | None
    error: str | None
    columns: list[str]
    rows: list[list[Any]]


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    kind: str | None = None  # answer | clarification | cannot_answer | error | pending
    charts: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    queries: list[QueryOut] = []
    grounding: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    stopped: str | None = None


class ChatDetail(BaseModel):
    chat: ChatOut
    messages: list[MessageOut]


@router.get("")
async def list_chats(project: OwnedProject, session: Session) -> list[ChatOut]:
    rows = await session.scalars(
        select(Chat).where(Chat.project_id == project.id).order_by(Chat.id.desc())
    )
    return [ChatOut.model_validate(c) for c in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_chat(body: ChatIn, project: OwnedProject, session: Session) -> ChatOut:
    chat = Chat(project_id=project.id, title=(body.title or "").strip() or NEW_CHAT_TITLE)
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    return ChatOut.model_validate(chat)


async def _owned_chat(chat_id: int, project_id: int, session: AsyncSession) -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")
    return chat


@router.get("/{chat_id}")
async def get_chat(chat_id: int, project: OwnedProject, session: Session) -> ChatDetail:
    chat = await _owned_chat(chat_id, project.id, session)
    messages = (
        await session.scalars(
            select(Message).where(Message.chat_id == chat.id).order_by(Message.id)
        )
    ).all()
    queries = await _queries_by_message(session, [m.id for m in messages])
    return ChatDetail(
        chat=ChatOut.model_validate(chat),
        messages=[_message_out(m, queries.get(m.id, [])) for m in messages],
    )


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(chat_id: int, project: OwnedProject, session: Session) -> None:
    chat = await _owned_chat(chat_id, project.id, session)
    await session.delete(chat)
    await session.commit()


@router.post("/{chat_id}/messages")
async def ask(
    chat_id: int,
    body: QuestionIn,
    project: OwnedProject,
    session: Session,
    queue: Queue,
    _: WithinAIBudget,
) -> StreamingResponse:
    chat = await _owned_chat(chat_id, project.id, session)
    ctx = await load_project_context(session, project)
    if not ctx.tables:
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload a dataset before asking questions")

    previous = (
        await session.scalars(
            select(Message).where(Message.chat_id == chat.id).order_by(Message.id)
        )
    ).all()
    history = [
        {"role": m.role, "content": m.content}
        for m in previous
        if m.content and (m.trace_json or {}).get("kind") not in ("pending", "error")
    ]

    question = body.content.strip()
    if chat.title == NEW_CHAT_TITLE:
        chat.title = question if len(question) <= 80 else question[:79] + "…"
    user_message = Message(chat_id=chat.id, role="user", content=question)
    reply = Message(chat_id=chat.id, role="assistant", content="", trace_json={"kind": "pending"})
    session.add_all([user_message, reply])
    await session.commit()

    events: asyncio.Queue[Event | None] = asyncio.Queue()
    task = asyncio.create_task(_answer(ctx, queue, question, history, reply.id, events))
    _running.add(task)
    task.add_done_callback(_running.discard)

    async def stream() -> AsyncIterator[str]:
        yield _sse({"type": "accepted", "user_message_id": user_message.id, "id": reply.id})
        while (event := await events.get()) is not None:
            yield _sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _answer(
    ctx: ProjectContext,
    queue: ArqRedis,
    question: str,
    history: list[dict[str, Any]],
    message_id: int,
    events: asyncio.Queue[Event | None],
) -> None:
    async with get_sessionmaker()() as session:

        async def execute(sql: str, row_limit: int) -> tuple[int, QueryResult]:
            try:
                return await execute_logged(
                    ctx.project_id, sql, session, queue, message_id=message_id, row_limit=row_limit
                )
            except HTTPException as exc:
                raise ToolError(str(exc.detail)) from exc

        client = LLMClient.from_settings()
        retriever = None
        if client.embedding_model:

            async def embed(texts: Sequence[str]) -> list[list[float]]:
                return await client.embed(texts, step="column_retrieval", project_id=ctx.project_id)

            retriever = ColumnRetriever(embed)
        box = ToolBox(ctx, execute, retriever)
        outcome: Outcome | None = None
        try:
            async for event in run_agent(client, box, question, history):
                if event["type"] == "done":
                    outcome = event["outcome"]
                else:
                    events.put_nowait(event)
        except Exception as exc:
            log.exception("chat agent failed (message %s)", message_id)
            outcome = Outcome("error", f"Something went wrong: {type(exc).__name__}.", [], [], None)
        finally:
            if outcome is None:
                outcome = Outcome("error", "The answer was interrupted.", [], [], None)
            reply = await session.get(Message, message_id)
            if reply is not None:
                charts = [c for c in box.state.charts if c["id"] in outcome.chart_ids]
                reply.content = outcome.answer
                reply.chart_json = charts or None
                reply.trace_json = {
                    "kind": outcome.kind,
                    "steps": [s.to_json() for s in box.state.steps],
                    "query_ids": outcome.query_ids,
                    "grounding": outcome.grounding,
                    "usage": outcome.usage,
                    "stopped": outcome.stopped,
                }
                await session.commit()
                queries = await _queries_by_message(session, [reply.id])
                events.put_nowait(
                    {
                        "type": "done",
                        "message": _message_out(reply, queries.get(reply.id, [])).model_dump(
                            mode="json"
                        ),
                    }
                )
            events.put_nowait(None)


def _sse(event: Event) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


async def _queries_by_message(
    session: AsyncSession, message_ids: list[int]
) -> dict[int, list[QueryOut]]:
    if not message_ids:
        return {}
    out: dict[int, list[QueryOut]] = {}
    for q in await session.scalars(
        select(Query).where(Query.message_id.in_(message_ids)).order_by(Query.id)
    ):
        preview = q.result_preview_json or {}
        assert q.message_id is not None
        out.setdefault(q.message_id, []).append(
            QueryOut(
                id=q.id,
                sql=q.sql,
                row_count=q.row_count,
                duration_ms=q.duration_ms,
                error=q.error,
                columns=preview.get("columns", []),
                rows=preview.get("rows", []),
            )
        )
    return out


def _message_out(m: Message, queries: list[QueryOut]) -> MessageOut:
    trace = m.trace_json or {}
    return MessageOut(
        id=m.id,
        role=m.role,
        content=m.content,
        created_at=m.created_at,
        kind=trace.get("kind"),
        charts=m.chart_json or [],
        steps=trace.get("steps", []),
        queries=queries,
        grounding=trace.get("grounding"),
        usage=trace.get("usage"),
        stopped=trace.get("stopped"),
    )
