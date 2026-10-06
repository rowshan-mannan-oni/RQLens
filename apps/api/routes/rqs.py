"""Research questions and their fit assessments.

Assessments run in the worker; the API stores the question, bumps its version and enqueues a job.
Editing the text clears the parsed form and mapping; editing the mapping keeps the parsed form.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from api.agent.context import load_project_context
from api.db.models import Project, Query, ResearchQuestion, RQAssessment
from api.limits import WithinAIBudget, ai_usage, over_limit_message
from api.routes.deps import OwnedProject, Queue, Session
from api.rq import mapper
from api.rq.schemas import Mapping

router = APIRouter(prefix="/projects/{project_id}/rqs", tags=["research questions"])

MAX_QUESTIONS = 20


class QuestionIn(BaseModel):
    text: str = Field(min_length=5, max_length=1000)


class QuestionUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=5, max_length=1000)
    position: int | None = Field(default=None, ge=0)


class AssessIn(BaseModel):
    remap: bool = False  # map the constructs again instead of keeping the current mapping


class QueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sql: str
    row_count: int | None
    duration_ms: int | None
    error: str | None
    result_preview_json: dict[str, Any] | None


class AssessmentOut(BaseModel):
    id: int
    verdict: str
    explanation: str | None
    rewording: str | None
    suggested_method: str | None
    threats: list[str]
    rules: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    problems: list[str]
    grounding: dict[str, Any] | None
    explained_by: str | None
    config_version: str
    created_at: datetime
    queries: list[QueryOut]


class QuestionOut(BaseModel):
    id: int
    text: str
    position: int
    status: str
    error: str | None
    parsed: dict[str, Any] | None
    mapping: dict[str, Any] | None
    assessment: AssessmentOut | None
    created_at: datetime


class ColumnOption(BaseModel):
    table: str
    column: str
    label: str
    type: str | None


class QuestionsOut(BaseModel):
    questions: list[QuestionOut]
    columns: list[ColumnOption]  # what a mapping may use
    suggestions: list[dict[str, Any]] | None
    suggestions_status: str | None
    suggestions_error: str | None


async def _owned(rq_id: int, project: Project, session: Session) -> ResearchQuestion:
    rq = await session.get(ResearchQuestion, rq_id)
    if rq is None or rq.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Research question not found")
    return rq


async def _over_budget(rq: ResearchQuestion, project: Project, session: Session) -> bool:
    """For buttons on a question card: record the limit message on the card instead of failing
    the request, so the researcher sees why nothing happened."""
    over = over_limit_message(await ai_usage(session, project.user_id))
    if over:
        rq.status, rq.error = "failed", over
        await session.commit()
    return over is not None


async def _enqueue(rq: ResearchQuestion, session: Session, queue: Queue) -> None:
    rq.version += 1
    rq.status, rq.error = "queued", None
    await session.commit()
    await queue.enqueue_job("assess_rq", rq.id, rq.version)


async def _out(session: Session, rq: ResearchQuestion) -> QuestionOut:
    latest = await session.scalar(
        select(RQAssessment)
        .where(RQAssessment.rq_id == rq.id)
        .order_by(RQAssessment.id.desc())
        .limit(1)
    )
    assessment = None
    if latest is not None:
        queries = await session.scalars(
            select(Query).where(Query.rq_assessment_id == latest.id).order_by(Query.id)
        )
        assessment = AssessmentOut(
            id=latest.id,
            verdict=latest.verdict,
            explanation=latest.explanation,
            rewording=latest.rewording,
            suggested_method=latest.suggested_method,
            threats=latest.threats_json or [],
            rules=latest.evidence_json or [],
            facts=latest.facts_json or [],
            gaps=latest.gaps_json or [],
            problems=latest.problems_json or [],
            grounding=latest.grounding_json,
            explained_by=latest.explained_by,
            config_version=latest.config_version,
            created_at=latest.created_at,
            queries=[QueryOut.model_validate(q) for q in queries],
        )
    return QuestionOut(
        id=rq.id,
        text=rq.text,
        position=rq.position,
        status=rq.status,
        error=rq.error,
        parsed=rq.parsed_json,
        mapping=rq.mapping_json,
        assessment=assessment,
        created_at=rq.created_at,
    )


@router.get("")
async def list_questions(project: OwnedProject, session: Session) -> QuestionsOut:
    rows = await session.scalars(
        select(ResearchQuestion)
        .where(ResearchQuestion.project_id == project.id)
        .order_by(ResearchQuestion.position, ResearchQuestion.id)
    )
    ctx = await load_project_context(session, project)
    return QuestionsOut(
        questions=[await _out(session, rq) for rq in rows],
        columns=[
            ColumnOption(
                table=t.table, column=c.name, label=c.label or c.name, type=c.semantic_type
            )
            for t in ctx.tables
            for c in t.columns
        ],
        suggestions=project.rq_suggestions_json,
        suggestions_status=project.rq_suggestions_status,
        suggestions_error=project.rq_suggestions_error,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_question(
    body: QuestionIn, project: OwnedProject, session: Session, queue: Queue, _: WithinAIBudget
) -> QuestionOut:
    n = await session.scalar(select(func.count()).where(ResearchQuestion.project_id == project.id))
    if (n or 0) >= MAX_QUESTIONS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A project can have at most {MAX_QUESTIONS} questions"
        )
    last = await session.scalar(
        select(func.max(ResearchQuestion.position)).where(ResearchQuestion.project_id == project.id)
    )
    rq = ResearchQuestion(
        project_id=project.id,
        text=body.text.strip(),
        position=(last + 1) if last is not None else 0,
        version=0,
        status="queued",
    )
    session.add(rq)
    await session.flush()
    await _enqueue(rq, session, queue)
    return await _out(session, rq)


@router.patch("/{rq_id}")
async def update_question(
    rq_id: int, body: QuestionUpdate, project: OwnedProject, session: Session, queue: Queue
) -> QuestionOut:
    rq = await _owned(rq_id, project, session)
    if body.position is not None:
        rq.position = body.position
    if body.text is not None and body.text.strip() != rq.text:
        if await _over_budget(rq, project, session):
            return await _out(session, rq)
        rq.text = body.text.strip()
        rq.parsed_json = None
        rq.mapping_json = None
        await _enqueue(rq, session, queue)
    else:
        await session.commit()
    return await _out(session, rq)


@router.put("/{rq_id}/mapping")
async def update_mapping(
    rq_id: int, body: Mapping, project: OwnedProject, session: Session, queue: Queue
) -> QuestionOut:
    """Replace the mapping with the user's version and re-assess (parse and map are kept)."""
    rq = await _owned(rq_id, project, session)
    if rq.parsed_json is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Wait for the first assessment to finish")
    ctx = await load_project_context(session, project)
    mapping, problems = mapper.validate(ctx, body)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"problems": problems})
    parsed_names = [(c["name"], c["role"]) for c in rq.parsed_json.get("constructs", [])]
    if [(c.name, c.role) for c in mapping.constructs] != parsed_names:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"problems": ["Constructs must match the parsed question (names, roles and order)."]},
        )
    rq.mapping_json = mapping.model_dump(mode="json")
    await _enqueue(rq, session, queue)
    return await _out(session, rq)


@router.post("/{rq_id}/assess", status_code=status.HTTP_202_ACCEPTED)
async def reassess(
    rq_id: int, body: AssessIn, project: OwnedProject, session: Session, queue: Queue
) -> QuestionOut:
    rq = await _owned(rq_id, project, session)
    if (body.remap or rq.parsed_json is None) and await _over_budget(rq, project, session):
        return await _out(session, rq)
    if body.remap:
        rq.mapping_json = None
    await _enqueue(rq, session, queue)
    return await _out(session, rq)


@router.delete("/{rq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(rq_id: int, project: OwnedProject, session: Session) -> None:
    rq = await _owned(rq_id, project, session)
    await session.delete(rq)  # assessments cascade; their queries stay, unlinked
    await session.commit()


@router.post("/suggestions", status_code=status.HTTP_202_ACCEPTED)
async def request_suggestions(project: OwnedProject, session: Session, queue: Queue) -> None:
    over = over_limit_message(await ai_usage(session, project.user_id))
    if over:  # shown on the page as "Suggestions failed: ..."
        project.rq_suggestions_status, project.rq_suggestions_error = "failed", over
        await session.commit()
        return
    project.rq_suggestions_status = "running"
    project.rq_suggestions_error = None
    await session.commit()
    await queue.enqueue_job("suggest_rqs", project.id)
