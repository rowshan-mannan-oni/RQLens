"""Per-user limits: projects, datasets, and AI use per calendar month.

AI use is measured from `llm_calls` (every call is traced, including failed ones), summed over
the user's projects since the first day of the month, UTC. A limit of 0 means no limit.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.db.models import Dataset, LLMCall, Project
from api.routes.deps import OwnedProject, Session


def month_start(now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now(dt.UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(now: dt.datetime | None = None) -> dt.date:
    start = month_start(now)
    return (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    ).date()


@dataclass(frozen=True)
class AIUsage:
    calls: int
    cost_usd: Decimal
    call_limit: int
    budget_usd: float
    resets_on: dt.date

    @property
    def exceeded(self) -> str | None:
        """Why the user is over their limit, or None."""
        if self.call_limit and self.calls >= self.call_limit:
            return f"{self.calls:,} of {self.call_limit:,} AI calls this month"
        if self.budget_usd and self.cost_usd >= Decimal(str(self.budget_usd)):
            return f"${self.cost_usd:.2f} of the ${self.budget_usd:.2f} monthly AI budget"
        return None


async def ai_usage(session: AsyncSession, user_id: int) -> AIUsage:
    row = (
        await session.execute(
            select(func.count(LLMCall.id), func.coalesce(func.sum(LLMCall.cost_usd), 0))
            .join(Project, Project.id == LLMCall.project_id)
            .where(Project.user_id == user_id, LLMCall.created_at >= month_start())
        )
    ).one()
    s = get_settings()
    return AIUsage(
        calls=int(row[0]),
        cost_usd=Decimal(row[1]),
        call_limit=s.monthly_llm_calls,
        budget_usd=s.monthly_llm_budget_usd,
        resets_on=next_month(),
    )


def over_limit_message(usage: AIUsage) -> str | None:
    reason = usage.exceeded
    if reason is None:
        return None
    return (
        f"The monthly AI limit is reached ({reason}). It resets on "
        f"{usage.resets_on:%d %B %Y}. Features that need no AI keep working."
    )


async def require_ai_budget(project: OwnedProject, session: Session) -> None:
    """Dependency: refuse an AI action when the project owner is over their monthly limit."""
    message = over_limit_message(await ai_usage(session, project.user_id))
    if message:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)


WithinAIBudget = Annotated[None, Depends(require_ai_budget)]


async def enforce_ai_budget(session: AsyncSession, user_id: int) -> None:
    """Like require_ai_budget, for endpoints that need AI only on some paths."""
    message = over_limit_message(await ai_usage(session, user_id))
    if message:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)


async def enforce_project_limit(session: AsyncSession, user_id: int) -> None:
    limit = get_settings().max_projects_per_user
    n = await session.scalar(select(func.count(Project.id)).where(Project.user_id == user_id))
    if limit and (n or 0) >= limit:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You have reached the limit of {limit} project{'s' if limit != 1 else ''}. "
            "Delete one to create another.",
        )


async def enforce_dataset_limit(session: AsyncSession, project_id: int) -> None:
    limit = get_settings().max_datasets_per_project
    n = await session.scalar(select(func.count(Dataset.id)).where(Dataset.project_id == project_id))
    if limit and (n or 0) >= limit:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This project has reached the limit of {limit} dataset{'s' if limit != 1 else ''}. "
            "Delete one to add another.",
        )
