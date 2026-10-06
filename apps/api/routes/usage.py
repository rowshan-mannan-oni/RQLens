"""AI and query usage per project for the signed-in user: calls, tokens, cost and latency."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Float, cast, func, select

from api.auth import CurrentUser
from api.config import get_settings
from api.db.models import LLMCall, Project, Query
from api.limits import ai_usage, month_start
from api.routes.deps import Session

router = APIRouter(prefix="/usage", tags=["usage"])


class StepUsage(BaseModel):
    step: str
    calls: int
    cost_usd: Decimal
    avg_latency_ms: float


class ProjectUsage(BaseModel):
    project_id: int
    title: str
    calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    avg_latency_ms: float
    p95_latency_ms: float
    queries: int
    avg_query_ms: float
    steps: list[StepUsage]


class UsageOut(BaseModel):
    period: str
    since: datetime | None
    month_calls: int
    month_cost_usd: Decimal
    call_limit: int
    budget_usd: float
    resets_on: date
    limits: dict[str, int]
    projects: list[ProjectUsage]


@router.get("")
async def get_usage(
    user: CurrentUser, session: Session, period: Literal["month", "all"] = "month"
) -> UsageOut:
    since = month_start() if period == "month" else None
    projects = {
        p.id: p.title
        for p in await session.scalars(
            select(Project).where(Project.user_id == user.id).order_by(Project.id)
        )
    }
    in_scope: list[ColumnElement[bool]] = [LLMCall.project_id.in_(projects)]
    if since is not None:
        in_scope.append(LLMCall.created_at >= since)
    failed = LLMCall.response_json.has_key("error")  # failed calls store {"error": ...}

    totals = {
        r.project_id: r
        for r in await session.execute(
            select(
                LLMCall.project_id,
                func.count(LLMCall.id).label("calls"),
                func.count(LLMCall.id).filter(failed).label("failed"),
                func.coalesce(func.sum(LLMCall.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(LLMCall.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(LLMCall.cost_usd), 0).label("cost"),
                func.coalesce(func.avg(cast(LLMCall.latency_ms, Float)), 0).label("avg_ms"),
                func.coalesce(func.percentile_cont(0.95).within_group(LLMCall.latency_ms), 0).label(
                    "p95_ms"
                ),
            )
            .where(*in_scope)
            .group_by(LLMCall.project_id)
        )
    }
    steps: dict[int, list[StepUsage]] = {}
    for r in await session.execute(
        select(
            LLMCall.project_id,
            LLMCall.step,
            func.count(LLMCall.id),
            func.coalesce(func.sum(LLMCall.cost_usd), 0),
            func.coalesce(func.avg(cast(LLMCall.latency_ms, Float)), 0),
        )
        .where(*in_scope)
        .group_by(LLMCall.project_id, LLMCall.step)
        .order_by(func.count(LLMCall.id).desc())
    ):
        steps.setdefault(r[0], []).append(
            StepUsage(step=r[1], calls=r[2], cost_usd=Decimal(r[3]), avg_latency_ms=float(r[4]))
        )

    query_scope: list[ColumnElement[bool]] = [Query.project_id.in_(projects)]
    if since is not None:
        query_scope.append(Query.created_at >= since)
    queries = {
        r[0]: (int(r[1]), float(r[2] or 0))
        for r in await session.execute(
            select(Query.project_id, func.count(Query.id), func.avg(cast(Query.duration_ms, Float)))
            .where(*query_scope)
            .group_by(Query.project_id)
        )
    }

    out = []
    for pid, title in projects.items():
        t = totals.get(pid)
        q = queries.get(pid, (0, 0.0))
        out.append(
            ProjectUsage(
                project_id=pid,
                title=title,
                calls=t.calls if t else 0,
                failed_calls=t.failed if t else 0,
                input_tokens=int(t.input_tokens) if t else 0,
                output_tokens=int(t.output_tokens) if t else 0,
                cost_usd=Decimal(t.cost) if t else Decimal(0),
                avg_latency_ms=float(t.avg_ms) if t else 0.0,
                p95_latency_ms=float(t.p95_ms) if t else 0.0,
                queries=q[0],
                avg_query_ms=q[1],
                steps=steps.get(pid, []),
            )
        )
    out.sort(key=lambda p: (-p.calls, p.project_id))

    month = await ai_usage(session, user.id)
    s = get_settings()
    return UsageOut(
        period=period,
        since=since,
        month_calls=month.calls,
        month_cost_usd=month.cost_usd,
        call_limit=month.call_limit,
        budget_usd=month.budget_usd,
        resets_on=month.resets_on,
        limits={
            "projects": s.max_projects_per_user,
            "datasets_per_project": s.max_datasets_per_project,
            "upload_mb": s.max_upload_bytes // 2**20,
        },
        projects=out,
    )
