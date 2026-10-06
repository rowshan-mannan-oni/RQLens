"""Insights: start a generation run and read the latest one."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from api.db.models import Dataset, Insight, InsightRun, Query
from api.routes.deps import OwnedProject, Queue, Session

router = APIRouter(prefix="/projects/{project_id}/insights", tags=["insights"])


class QueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sql: str
    row_count: int | None
    duration_ms: int | None
    error: str | None
    result_preview_json: dict[str, Any] | None


class InsightOut(BaseModel):
    id: int
    rq_id: int | None
    kind: str
    status: str | None
    title: str
    statement: str
    effect_size: float | None
    p_value: float | None
    p_adjusted: float | None
    score: float | None
    result: dict[str, Any] | None
    chart: dict[str, Any] | None
    caveats: list[str]
    spec: dict[str, Any] | None
    grounding: dict[str, Any] | None
    written_by: str | None
    queries: list[QueryOut]


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    error: str | None
    planned: int | None
    failed_json: list[str] | None
    dropped_json: list[str] | None
    used_llm: bool
    config_version: str | None
    created_at: datetime


class InsightsOut(BaseModel):
    run: RunOut | None  # the newest run, which may still be running
    insights: list[InsightOut]  # from the newest finished run


@router.get("")
async def get_insights(project: OwnedProject, session: Session) -> InsightsOut:
    runs = list(
        await session.scalars(
            select(InsightRun)
            .where(InsightRun.project_id == project.id)
            .order_by(InsightRun.id.desc())
        )
    )
    shown = next((r for r in runs if r.status == "done"), None)
    insights: list[InsightOut] = []
    if shown is not None:
        rows = list(
            await session.scalars(
                select(Insight)
                .where(Insight.run_id == shown.id)
                .order_by(Insight.score.desc().nulls_last(), Insight.id)
            )
        )
        ids = {q for i in rows for q in (i.query_ids_json or [])}
        queries = {
            q.id: QueryOut.model_validate(q)
            for q in await session.scalars(select(Query).where(Query.id.in_(ids)))
        }
        insights = [
            InsightOut(
                id=i.id,
                rq_id=i.rq_id,
                kind=i.kind,
                status=i.status,
                title=i.title,
                statement=i.statement,
                effect_size=i.effect_size,
                p_value=i.p_value,
                p_adjusted=i.p_adjusted,
                score=i.score,
                result=i.result_json,
                chart=i.chart_json,
                caveats=i.caveats_json or [],
                spec=i.spec_json,
                grounding=i.grounding_json,
                written_by=i.written_by,
                queries=[queries[q] for q in (i.query_ids_json or []) if q in queries],
            )
            for i in rows
        ]
    return InsightsOut(run=RunOut.model_validate(runs[0]) if runs else None, insights=insights)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_run(project: OwnedProject, session: Session, queue: Queue) -> RunOut:
    ready = await session.scalar(
        select(Dataset.id).where(Dataset.project_id == project.id, Dataset.status == "ready")
    )
    if ready is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload a dataset before generating insights")
    running = await session.scalar(
        select(InsightRun.id).where(
            InsightRun.project_id == project.id, InsightRun.status.in_(("queued", "running"))
        )
    )
    if running is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Insights are already being generated")
    run = InsightRun(project_id=project.id, status="queued")
    session.add(run)
    await session.commit()
    await session.refresh(run)
    await queue.enqueue_job("generate_insights", run.id)
    return RunOut.model_validate(run)
