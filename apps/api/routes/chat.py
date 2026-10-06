"""Chat about a project's data. Answers stream as server-sent events while the agent works."""

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from api.agent.catalog import load_catalog
from api.agent.loop import AgentAnswer, run_agent
from api.agent.tools import SqlRun, ToolContext
from api.db.models import Chat, Message, Project, Query
from api.db.session import get_sessionmaker
from api.llm.client import LLMClient
from api.routes.deps import OwnedProject, Queue, Session
from api.routes.query import execute_logged
from api.sql.executor import QueryResult

router = APIRouter(prefix="/projects/{project_id}/chats", tags=["chat"])

TITLE_CHARS = 80
HISTORY_LIMIT = 6


def get_llm_client() -> LLMClient:
    return LLMClient.from_settings()


LLM = Annotated[LLMClient, Depends(get_llm_client)]


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=TITLE_CHARS)


class QueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sql: str
    row_count: int | None
    duration_ms: int | None
    error: str | None
    result_preview_json: dict[str, Any] | None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    chart: dict[str, Any] | None
    details: dict[str, Any] | None
    queries: list[QueryOut]
    created_at: datetime


class ChatDetail(BaseModel):
    chat: ChatOut
    messages: list[MessageOut]


class Ask(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


async def _owned_chat(chat_id: int, project: Project, session: Session) -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")
    return chat


async def _message_out(session: Any, message: Message) -> MessageOut:
    queries = list(
        await session.scalars(
            select(Query).where(Query.message_id == message.id).order_by(Query.id)
        )
    )
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        chart=message.chart_json,
        details=message.details_json,
        queries=[QueryOut.model_validate(q) for q in queries],
        created_at=message.created_at,
    )


@router.get("")
async def list_chats(project: OwnedProject, session: Session) -> list[ChatOut]:
    rows = await session.scalars(
        select(Chat).where(Chat.project_id == project.id).order_by(Chat.id.desc())
    )
    return [ChatOut.model_validate(c) for c in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_chat(body: ChatCreate, project: OwnedProject, session: Session) -> ChatOut:
    chat = Chat(project_id=project.id, title=(body.title or "").strip() or "New chat")
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    return ChatOut.model_validate(chat)


@router.get("/{chat_id}")
async def get_chat(chat_id: int, project: OwnedProject, session: Session) -> ChatDetail:
    chat = await _owned_chat(chat_id, project, session)
    messages = await session.scalars(
        select(Message).where(Message.chat_id == chat.id).order_by(Message.id)
    )
    return ChatDetail(
        chat=ChatOut.model_validate(chat),
        messages=[await _message_out(session, m) for m in messages],
    )


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(chat_id: int, project: OwnedProject, session: Session) -> None:
    chat = await _owned_chat(chat_id, project, session)
    # Messages go by ON DELETE CASCADE; their logged queries stay, unlinked.
    await session.delete(chat)
    await session.commit()


@router.post("/{chat_id}/messages")
async def ask(
    chat_id: int,
    body: Ask,
    project: OwnedProject,
    session: Session,
    queue: Queue,
    client: LLM,
) -> StreamingResponse:
    """Ask a question. The response is an event stream: `user`, then `step`s, then `answer`."""
    chat = await _owned_chat(chat_id, project, session)
    question = body.content.strip()
    previous = list(
        await session.scalars(
            select(Message)
            .where(Message.chat_id == chat.id)
            .order_by(Message.id.desc())
            .limit(HISTORY_LIMIT)
        )
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(previous)]

    user_message = Message(chat_id=chat.id, role="user", content=question)
    session.add(user_message)
    if not previous and chat.title == "New chat":
        chat.title = question[:TITLE_CHARS]
    await session.commit()
    catalog = await load_catalog(session, project)
    project_id, user_message_id = project.id, user_message.id

    async def run_sql(sql: str, row_limit: int) -> SqlRun:
        async with get_sessionmaker()() as s:
            try:
                query_id, result = await execute_logged(
                    project_id, sql, s, queue, row_limit=row_limit
                )
            except HTTPException as exc:
                return SqlRun(None, QueryResult(sql, [], [], [], 0, False, 0, str(exc.detail)))
        return SqlRun(query_id, result)

    ctx = ToolContext(catalog=catalog, run_sql=run_sql)

    async def events() -> AsyncIterator[str]:
        yield _sse("user", {"id": user_message_id, "content": question})
        if not catalog.tables:
            async with get_sessionmaker()() as s:
                message = Message(
                    chat_id=chat_id,
                    role="assistant",
                    content="This project has no ready datasets yet. Upload a CSV first.",
                    details_json={"kind": "cannot_answer", "stop_reason": "no_data"},
                )
                s.add(message)
                await s.commit()
                yield _sse("answer", (await _message_out(s, message)).model_dump(mode="json"))
            return

        answer: AgentAnswer | None = None
        async for event in run_agent(client, ctx, question, history=history, project_id=project_id):
            if event.answer is not None:
                answer = event.answer
            else:
                yield _sse("step", event.data)
        assert answer is not None

        async with get_sessionmaker()() as s:
            message = Message(
                chat_id=chat_id,
                role="assistant",
                content=answer.text,
                chart_json=answer.chart,
                details_json=answer.details(),
            )
            s.add(message)
            await s.flush()
            # Link every query this answer ran, including failed attempts.
            ran = [q for q in ctx.query_order if q > 0]
            if ran:
                await s.execute(
                    update(Query).where(Query.id.in_(ran)).values(message_id=message.id)
                )
            await s.commit()
            yield _sse("answer", (await _message_out(s, message)).model_dump(mode="json"))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
