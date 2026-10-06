"""Background job: generate a project's insights (run by the arq worker)."""

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select, update

from api.agent.context import load_associations, load_project_context
from api.config import get_settings
from api.db.models import Insight, InsightRun, Project, Query, ResearchQuestion, RQAssessment
from api.db.session import get_sessionmaker
from api.insights.pipeline import CONFIG_VERSION, Question, generate
from api.llm.client import LLMClient
from api.routes.query import execute_logged
from api.rq.schemas import Mapping
from api.sql.executor import QueryResult

log = logging.getLogger(__name__)


async def _finish(run_id: int, **fields: Any) -> None:
    async with get_sessionmaker()() as session:
        run = await session.get(InsightRun, run_id)
        if run is not None:
            for k, v in fields.items():
                setattr(run, k, v)
            await session.commit()


async def generate_insights(ctx: dict[str, Any], run_id: int) -> str:
    async with get_sessionmaker()() as session:
        run = await session.get(InsightRun, run_id)
        if run is None:
            return "missing"
        project = await session.get(Project, run.project_id)
        if project is None:
            return "missing"
        project_ctx = await load_project_context(session, project)
        associations = await load_associations(session, project.id)
        questions = []
        for rq in await session.scalars(
            select(ResearchQuestion)
            .where(ResearchQuestion.project_id == project.id)
            .order_by(ResearchQuestion.position, ResearchQuestion.id)
        ):
            latest = await session.scalar(
                select(RQAssessment)
                .where(RQAssessment.rq_id == rq.id)
                .order_by(RQAssessment.id.desc())
                .limit(1)
            )
            questions.append(
                Question(
                    id=rq.id,
                    text=rq.text,
                    mapping=Mapping.model_validate(rq.mapping_json) if rq.mapping_json else None,
                    rules=list(latest.evidence_json or []) if latest else [],
                )
            )
        run.status = "running"
        await session.commit()

    if not project_ctx.tables:
        await _finish(run_id, status="failed", error="Upload a dataset first.")
        return "failed"

    redis, project_id = ctx["redis"], project_ctx.project_id

    async def execute(sql: str, row_limit: int) -> tuple[int | None, QueryResult]:
        async with get_sessionmaker()() as s:
            try:
                return await execute_logged(project_id, sql, s, redis, row_limit=row_limit)
            except HTTPException as exc:
                return None, QueryResult(sql, [], [], [], 0, False, 0, str(exc.detail))

    client = LLMClient.from_settings() if get_settings().llm_api_key else None
    try:
        g = await generate(
            project_ctx, execute, questions=questions, associations=associations, client=client
        )
    except Exception as exc:
        log.exception("generate_insights %s failed", run_id)
        await _finish(run_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:2000])
        return "failed"

    async with get_sessionmaker()() as session:
        for x in g.insights:
            insight = Insight(
                project_id=project_id,
                run_id=run_id,
                rq_id=x.rq_id,
                title=x.title[:300],
                statement=x.statement,
                kind=x.kind,
                status=x.status,
                effect_size=x.effect_size,
                p_value=x.p_value,
                p_adjusted=x.p_adjusted,
                score=x.score,
                sql=x.sql,
                result_json=x.result,
                chart_json=x.chart,
                caveats_json=x.caveats,
                spec_json=x.spec,
                query_ids_json=x.query_ids,
                grounding_json=x.grounding,
                written_by=x.written_by,
            )
            session.add(insight)
            await session.flush()
            if x.kind == "analysis" and x.query_ids:
                await session.execute(
                    update(Query).where(Query.id.in_(x.query_ids)).values(insight_id=insight.id)
                )
        run = await session.get(InsightRun, run_id)
        if run is not None:
            run.status = "done"
            run.planned = g.planned
            run.failed_json = g.failed
            run.dropped_json = g.dropped
            run.used_llm = client is not None
            run.config_version = CONFIG_VERSION
        # Earlier runs are replaced by this one.
        old = select(InsightRun.id).where(
            InsightRun.project_id == project_id, InsightRun.id != run_id
        )
        await session.execute(delete(Insight).where(Insight.run_id.in_(old)))
        await session.execute(
            delete(InsightRun).where(InsightRun.project_id == project_id, InsightRun.id != run_id)
        )
        await session.commit()
    return "done"
