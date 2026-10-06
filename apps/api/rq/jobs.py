"""Background jobs for research-question fit (run by the arq worker).

assess_rq: parse, map, measure, decide and explain one research question.
suggest_rqs: suggest research questions the project's data could answer.

A job stores its result only if the question was not edited while it ran (`version`).
"""

import logging
from collections.abc import Sequence
from typing import Any

import openai
from arq import Retry
from fastapi import HTTPException
from sqlalchemy import select, update

from api.agent.context import load_associations, load_project_context
from api.config import get_settings
from api.db.models import Project, Query, ResearchQuestion, RQAssessment
from api.db.session import get_sessionmaker
from api.llm.client import LLMClient
from api.routes.query import execute_logged
from api.rq import writer
from api.rq.pipeline import CONFIG_VERSION, assess
from api.rq.schemas import Mapping, ParsedRQ
from api.semantic.column_retrieval import ColumnRetriever
from api.sql.executor import QueryResult

log = logging.getLogger(__name__)

TRIES = 4
RETRY_S = 30
TRANSIENT = (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError)


def _retriever(client: LLMClient, project_id: int) -> ColumnRetriever | None:
    if not client.embedding_model:
        return None

    async def embed(texts: Sequence[str]) -> list[list[float]]:
        return await client.embed(texts, step="column_retrieval", project_id=project_id)

    return ColumnRetriever(embed)


async def _set(rq_id: int, version: int, **fields: Any) -> bool:
    """Update the question if it is still at `version`. Returns whether it was."""
    async with get_sessionmaker()() as session:
        rq = await session.get(ResearchQuestion, rq_id)
        if rq is None or rq.version != version:
            return False
        for k, v in fields.items():
            setattr(rq, k, v)
        await session.commit()
        return True


async def assess_rq(ctx: dict[str, Any], rq_id: int, version: int) -> str:
    async with get_sessionmaker()() as session:
        rq = await session.get(ResearchQuestion, rq_id)
        if rq is None or rq.version != version:
            return "stale"
        project = await session.get(Project, rq.project_id)
        if project is None:
            return "missing"
        project_ctx = await load_project_context(session, project)
        associations = await load_associations(session, project.id)
        text = rq.text
        parsed = ParsedRQ.model_validate(rq.parsed_json) if rq.parsed_json else None
        mapping = Mapping.model_validate(rq.mapping_json) if rq.mapping_json else None
        rq.status, rq.error = "running", None
        await session.commit()

    if not project_ctx.tables:
        await _set(rq_id, version, status="failed", error="Upload a dataset first.")
        return "failed"
    if not get_settings().llm_api_key and (parsed is None or mapping is None):
        await _set(rq_id, version, status="failed", error="LLM_API_KEY is not set.")
        return "failed"

    redis = ctx["redis"]
    project_id = project_ctx.project_id

    async def execute(sql: str, row_limit: int) -> tuple[int | None, QueryResult]:
        async with get_sessionmaker()() as s:
            try:
                return await execute_logged(project_id, sql, s, redis, row_limit=row_limit)
            except HTTPException as exc:
                return None, QueryResult(sql, [], [], [], 0, False, 0, str(exc.detail))

    client = LLMClient.from_settings()
    try:
        a = await assess(
            client,
            project_ctx,
            text,
            execute,
            parsed=parsed,
            mapping=mapping,
            associations=_associations_for(project_ctx, mapping, associations),
            retriever=_retriever(client, project_id),
        )
    except TRANSIENT as exc:
        attempt = int(ctx.get("job_try", 1))
        if attempt < TRIES:
            delay = RETRY_S * attempt
            await _set(rq_id, version, status="queued",
                       error=f"AI provider busy; retrying in {delay} s")  # fmt: skip
            raise Retry(defer=delay) from exc
        await _set(rq_id, version, status="failed", error=f"AI provider busy: {exc}"[:2000])
        return "failed"
    except Exception as exc:
        log.exception("assess_rq %s failed", rq_id)
        await _set(rq_id, version, status="failed", error=f"{type(exc).__name__}: {exc}"[:2000])
        return "failed"

    async with get_sessionmaker()() as session:
        rq = await session.get(ResearchQuestion, rq_id)
        if rq is None or rq.version != version:
            return "stale"  # edited while running; the newer job will store its result
        assessment = RQAssessment(
            rq_id=rq.id,
            verdict=a.verdict,
            mapped_columns_json=a.mapping.model_dump(mode="json"),
            evidence_json=[r.model_dump(mode="json") for r in a.rules],
            gaps_json=a.gaps(),
            suggested_method=a.writeup.suggested_method or None,
            threats_json=a.writeup.threats,
            config_version=CONFIG_VERSION,
            explanation=a.writeup.explanation,
            rewording=a.writeup.rewording,
            facts_json=a.facts,
            grounding_json=a.grounding,
            explained_by=a.explained_by,
            problems_json=a.problems,
        )
        session.add(assessment)
        await session.flush()
        if a.query_ids:
            await session.execute(
                update(Query)
                .where(Query.id.in_(a.query_ids))
                .values(rq_assessment_id=assessment.id)
            )
        rq.parsed_json = a.parsed.model_dump(mode="json")
        rq.mapping_json = a.mapping.model_dump(mode="json")
        rq.status, rq.error = "done", None
        await session.commit()
    return a.verdict


def _associations_for(
    ctx: Any, mapping: Mapping | None, by_table: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Associations of the table the checks will run on (all tables when unknown)."""
    if mapping is not None:
        for c in mapping.constructs:
            if c.role == "dependent" and c.candidates and c.status != "rejected":
                return by_table.get(c.candidates[0].table, [])
    return [a for rows in by_table.values() for a in rows]


async def suggest_rqs(ctx: dict[str, Any], project_id: int) -> str:
    async with get_sessionmaker()() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return "missing"
        project_ctx = await load_project_context(session, project)
        existing = list(
            await session.scalars(
                select(ResearchQuestion.text)
                .where(ResearchQuestion.project_id == project_id)
                .order_by(ResearchQuestion.position)
            )
        )

    async def fail(message: str) -> str:
        async with get_sessionmaker()() as session:
            project = await session.get(Project, project_id)
            if project is not None:
                project.rq_suggestions_status = "failed"
                project.rq_suggestions_error = message[:2000]
                await session.commit()
        return "failed"

    if not project_ctx.tables:
        return await fail("Upload a dataset first.")
    if not get_settings().llm_api_key:
        return await fail("LLM_API_KEY is not set.")
    client = LLMClient.from_settings()
    try:
        found = await writer.suggest(
            client, project_ctx, existing, _retriever(client, project_id), project_id
        )
    except Exception as exc:
        log.warning("suggest_rqs %s failed: %s", project_id, exc)
        return await fail(f"{type(exc).__name__}: {exc}")

    async with get_sessionmaker()() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return "missing"
        project.rq_suggestions_json = [s.model_dump(mode="json") for s in found]
        project.rq_suggestions_status = "done"
        project.rq_suggestions_error = None
        await session.commit()
    return "done"
