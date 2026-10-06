"""arq worker. Run with: arq api.worker.WorkerSettings"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

import openai
from arq import Retry
from arq.connections import RedisSettings
from arq.worker import func
from sqlalchemy import delete, or_, select

from api.config import get_settings
from api.db.models import Dataset, DatasetColumn, Project, TableProfile, TableRelationship
from api.db.session import get_sessionmaker
from api.ingest.combine import CombinePlan, SourceTable, join_plan, stack_plan
from api.ingest.loader import LoadReport
from api.ingest.pipeline import run_combine_plan, run_joins, run_load, run_pii, run_profile
from api.insights.jobs import generate_insights
from api.llm.client import LLMClient
from api.profiler.joins import JoinColumn, JoinTable
from api.rq.jobs import TRIES as RQ_TRIES
from api.rq.jobs import assess_rq, suggest_rqs
from api.semantic.describer import column_evidence, describe
from api.storage import project_db_path, upload_path

log = logging.getLogger(__name__)

# Descriptions from these sources are never overwritten by the model.
KEPT_SOURCES = ("user", "dictionary")

DESCRIBE_TRIES = 4
DESCRIBE_RETRY_S = 30
TRANSIENT_LLM_ERRORS = (
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APIConnectionError,
)


async def ping(ctx: dict[str, Any]) -> str:
    return "pong"


async def _set_status(dataset_id: int, status: str, error: str | None = None) -> None:
    async with get_sessionmaker()() as session:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is not None:
            dataset.status = status
            dataset.error = error
            await session.commit()


async def ingest_dataset(ctx: dict[str, Any], dataset_id: int) -> str:
    """Load an uploaded CSV into the project's DuckDB file and profile it."""
    async with get_sessionmaker()() as session:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is None:
            return "missing"
        project_id, table_name = dataset.project_id, dataset.table_name

    async def load(db_path: Path) -> LoadReport:
        return await asyncio.to_thread(
            run_load, db_path, upload_path(project_id, dataset_id), table_name
        )

    return await _build(ctx, dataset_id, project_id, load, detect_joins=True)


async def combine_dataset(ctx: dict[str, Any], dataset_id: int) -> str:
    """Create a combined table (stack or join) from other tables and profile it."""
    async with get_sessionmaker()() as session:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is None:
            return "missing"
        project_id, table_name, spec = dataset.project_id, dataset.table_name, dataset.source_json
        try:
            plan = await _combine_plan(session, project_id, spec or {})
        except ValueError as exc:
            await _set_status(dataset_id, "failed", str(exc))
            return "failed"

    async def load(db_path: Path) -> LoadReport:
        return await asyncio.to_thread(run_combine_plan, db_path, table_name, plan)

    # A combined table overlaps its sources by construction; skip join detection.
    return await _build(ctx, dataset_id, project_id, load, detect_joins=False)


async def _combine_plan(session: Any, project_id: int, spec: dict[str, Any]) -> CombinePlan:
    async def source(dataset_id: int) -> SourceTable:
        d = await session.get(Dataset, dataset_id)
        if d is None or d.project_id != project_id or d.status != "ready":
            raise ValueError("A source dataset is missing or not ready.")
        cols = await session.scalars(
            select(DatasetColumn).where(DatasetColumn.dataset_id == d.id).order_by(DatasetColumn.id)
        )
        return SourceTable(
            dataset_id=d.id,
            table_name=d.table_name,
            label=d.original_filename,
            columns=tuple((c.name, c.original_name or c.name) for c in cols),
        )

    if spec.get("mode") == "stack":
        return stack_plan([await source(i) for i in spec["dataset_ids"]])
    if spec.get("mode") == "join":
        left, right = spec["left"], spec["right"]
        return join_plan(
            await source(left["dataset_id"]),
            await source(right["dataset_id"]),
            left["column"],
            right["column"],
            spec.get("how", "left"),
        )
    raise ValueError("Unknown combine mode.")


async def _build(
    ctx: dict[str, Any],
    dataset_id: int,
    project_id: int,
    load: Callable[[Path], Awaitable[LoadReport]],
    *,
    detect_joins: bool,
) -> str:
    """Load (or create) the table, profile it, detect personal data and joins, and store it."""
    db_path = project_db_path(project_id)
    # DuckDB allows one writer per file: serialise jobs per project.
    lock = ctx["redis"].lock(f"rqlens:duckdb:{project_id}", timeout=3600, blocking_timeout=3600)
    try:
        async with lock:
            await _set_status(dataset_id, "loading")
            report = await load(db_path)
            await _set_status(dataset_id, "profiling")
            profile = await asyncio.to_thread(run_profile, db_path, report)
            pii = await asyncio.to_thread(run_pii, db_path, profile, report.table_name)
            joins: list[dict[str, Any]] = []
            if detect_joins:
                new_table = JoinTable(
                    dataset_id=dataset_id,
                    table_name=report.table_name,
                    columns=tuple(
                        JoinColumn(
                            name=r.column.name,
                            physical_type=r.column.physical_type,
                            semantic_type=r.profile["semantic_type"],
                            distinct=r.profile["distinct"],
                            uniqueness=r.profile["uniqueness"],
                        )
                        for r in profile.columns
                    ),
                )
                joins = await asyncio.to_thread(
                    run_joins, db_path, new_table, await _ready_tables(project_id, dataset_id)
                )
    except Exception as exc:
        log.exception("building dataset %s failed", dataset_id)
        await _set_status(dataset_id, "failed", f"{type(exc).__name__}: {exc}"[:2000])
        return "failed"

    async with get_sessionmaker()() as session:
        dataset = await session.get(Dataset, dataset_id)
        project = await session.get(Project, project_id)
        if dataset is None or project is None:
            return "missing"
        # Re-running a job replaces earlier results.
        await session.execute(delete(DatasetColumn).where(DatasetColumn.dataset_id == dataset_id))
        await session.execute(delete(TableProfile).where(TableProfile.dataset_id == dataset_id))
        await session.execute(
            delete(TableRelationship).where(
                or_(
                    TableRelationship.left_dataset_id == dataset_id,
                    TableRelationship.right_dataset_id == dataset_id,
                )
            )
        )
        session.add_all(TableRelationship(project_id=project_id, **j) for j in joins)
        session.add_all(
            DatasetColumn(
                dataset_id=dataset_id,
                name=r.column.name,
                original_name=r.column.original_name,
                physical_type=r.column.physical_type,
                semantic_type=r.profile["semantic_type"],
                profile_json=r.profile,
                is_pii=pii[r.column.name].is_pii,
                pii_reason=pii[r.column.name].reason,
            )
            for r in profile.columns
        )
        session.add(
            TableProfile(
                dataset_id=dataset_id,
                profile_json=profile.table,
                warnings_json=profile.warnings,
            )
        )
        dataset.row_count = report.row_count
        dataset.column_count = len(report.columns)
        dataset.load_warnings_json = report.warnings
        dataset.status = "ready"
        dataset.error = None
        dataset.describe_status = "pending"
        dataset.describe_error = None
        project.duckdb_path = str(db_path)
        await session.commit()

    await ctx["redis"].enqueue_job("describe_dataset", dataset_id)
    return "ready"


async def describe_dataset(ctx: dict[str, Any], dataset_id: int) -> str:
    """Write LLM descriptions for columns that have none from the user or a dictionary."""
    settings = get_settings()
    async with get_sessionmaker()() as session:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is None:
            return "missing"
        project = await session.get(Project, dataset.project_id)
        if project is None:
            return "missing"
        if not settings.llm_api_key:
            dataset.describe_status = "skipped"
            dataset.describe_error = "LLM_API_KEY is not set"
            await session.commit()
            return "skipped"
        columns = (
            await session.scalars(
                select(DatasetColumn)
                .where(DatasetColumn.dataset_id == dataset_id)
                .order_by(DatasetColumn.id)
            )
        ).all()
        evidence = [
            column_evidence(
                c.name,
                c.original_name,
                c.semantic_type,
                c.is_pii,
                c.profile_json or {},
                project.share_samples,
            )
            for c in columns
            if c.description_source not in KEPT_SOURCES
        ]
        filename, topic, project_id = dataset.original_filename, project.topic, project.id
        dataset.describe_status = "running"
        dataset.describe_error = None
        await session.commit()

    try:
        found = (
            await describe(
                LLMClient.from_settings(),
                filename=filename,
                project_topic=topic,
                columns=evidence,
                project_id=project_id,
            )
            if evidence
            else {}
        )
    except TRANSIENT_LLM_ERRORS as exc:
        # Free tiers often answer "busy" (429/503); try again later instead of failing.
        attempt = int(ctx.get("job_try", 1))
        if attempt < DESCRIBE_TRIES:
            delay = DESCRIBE_RETRY_S * attempt
            log.warning("describe_dataset %s: provider busy, retry in %ss", dataset_id, delay)
            async with get_sessionmaker()() as session:
                dataset = await session.get(Dataset, dataset_id)
                if dataset is not None:
                    dataset.describe_status = "pending"
                    dataset.describe_error = f"AI provider busy; retrying in {delay} s"
                    await session.commit()
            raise Retry(defer=delay) from exc
        return await _describe_failed(dataset_id, exc)
    except Exception as exc:
        return await _describe_failed(dataset_id, exc)

    async with get_sessionmaker()() as session:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is None:
            return "missing"
        for c in await session.scalars(
            select(DatasetColumn).where(DatasetColumn.dataset_id == dataset_id)
        ):
            d = found.get(c.name)
            # Re-check: the user may have edited a description while the model was running.
            if d is not None and c.description_source not in KEPT_SOURCES:
                c.description = d.description
                c.description_source = "llm"
                c.description_confidence = d.confidence
        dataset.describe_status = "done"
        await session.commit()
    return "done"


async def _describe_failed(dataset_id: int, exc: Exception) -> str:
    log.error("describe_dataset %s failed: %s", dataset_id, exc)
    async with get_sessionmaker()() as session:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is not None:
            dataset.describe_status = "failed"
            dataset.describe_error = f"{type(exc).__name__}: {exc}"[:2000]
            await session.commit()
    return "failed"


async def _ready_tables(project_id: int, exclude_dataset_id: int) -> list[JoinTable]:
    """Other profiled tables in the project, for join detection."""
    async with get_sessionmaker()() as session:
        datasets = (
            await session.scalars(
                select(Dataset).where(
                    Dataset.project_id == project_id,
                    Dataset.status == "ready",
                    Dataset.kind == "upload",
                    Dataset.id != exclude_dataset_id,
                )
            )
        ).all()
        tables = []
        for d in datasets:
            columns = await session.scalars(
                select(DatasetColumn).where(DatasetColumn.dataset_id == d.id)
            )
            tables.append(
                JoinTable(
                    dataset_id=d.id,
                    table_name=d.table_name,
                    columns=tuple(
                        JoinColumn(
                            name=c.name,
                            physical_type=c.physical_type,
                            semantic_type=c.semantic_type or "",
                            distinct=(c.profile_json or {}).get("distinct", 0),
                            uniqueness=(c.profile_json or {}).get("uniqueness", 0.0),
                        )
                        for c in columns
                    ),
                )
            )
        return tables


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        ingest_dataset,
        combine_dataset,
        func(describe_dataset, max_tries=DESCRIBE_TRIES),
        func(assess_rq, max_tries=RQ_TRIES),
        suggest_rqs,
        generate_insights,
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 1  # a CSV that fails to load will fail again; the error is stored instead
    job_timeout = 3600
