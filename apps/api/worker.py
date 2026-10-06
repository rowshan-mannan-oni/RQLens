"""arq worker. Run with: arq api.worker.WorkerSettings"""

import asyncio
import logging
from typing import Any, ClassVar

from arq.connections import RedisSettings
from sqlalchemy import delete, or_, select

from api.config import get_settings
from api.db.models import Dataset, DatasetColumn, Project, TableProfile, TableRelationship
from api.db.session import get_sessionmaker
from api.ingest.pipeline import run_joins, run_load, run_profile
from api.profiler.joins import JoinColumn, JoinTable
from api.storage import project_db_path, upload_path

log = logging.getLogger(__name__)


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

    db_path = project_db_path(project_id)
    # DuckDB allows one writer per file: serialise jobs per project.
    lock = ctx["redis"].lock(f"rqlens:duckdb:{project_id}", timeout=3600, blocking_timeout=3600)
    try:
        async with lock:
            await _set_status(dataset_id, "loading")
            report = await asyncio.to_thread(
                run_load, db_path, upload_path(project_id, dataset_id), table_name
            )
            await _set_status(dataset_id, "profiling")
            profile = await asyncio.to_thread(run_profile, db_path, report)
            new_table = JoinTable(
                dataset_id=dataset_id,
                table_name=table_name,
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
        log.exception("ingest_dataset %s failed", dataset_id)
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
        project.duckdb_path = str(db_path)
        await session.commit()
    return "ready"


async def _ready_tables(project_id: int, exclude_dataset_id: int) -> list[JoinTable]:
    """Other profiled tables in the project, for join detection."""
    async with get_sessionmaker()() as session:
        datasets = (
            await session.scalars(
                select(Dataset).where(
                    Dataset.project_id == project_id,
                    Dataset.status == "ready",
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
    functions: ClassVar[list[Any]] = [ping, ingest_dataset]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 1  # a CSV that fails to load will fail again; the error is stored instead
    job_timeout = 3600
