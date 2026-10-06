import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from redis.exceptions import LockError
from sqlalchemy import select

from api.db.models import Dataset, Query
from api.routes.deps import OwnedProject, Queue, Session
from api.sql.executor import QueryResult, run_query
from api.storage import project_db_path

router = APIRouter(prefix="/projects/{project_id}/query", tags=["query"])

LOCK_WAIT_S = 30
PREVIEW_ROWS = 20


class QueryIn(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)


class QueryOut(BaseModel):
    query_id: int
    sql: str
    columns: list[str]
    types: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    error: str | None


async def execute_logged(
    project_id: int,
    sql: str,
    session: Session,
    queue: Queue,
    *,
    message_id: int | None = None,
) -> tuple[int, QueryResult]:
    """Run a guarded query under the project's DuckDB lock and log it in `queries`."""
    tables = list(
        await session.scalars(
            select(Dataset.table_name).where(
                Dataset.project_id == project_id, Dataset.status == "ready"
            )
        )
    )
    # The worker writes the same file; DuckDB does not allow a reader alongside a writer.
    lock = queue.lock(f"rqlens:duckdb:{project_id}", timeout=120, blocking_timeout=LOCK_WAIT_S)
    try:
        async with lock:
            result = await asyncio.to_thread(run_query, project_db_path(project_id), sql, tables)
    except LockError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "A dataset is being updated; try again shortly"
        ) from exc

    logged = Query(
        project_id=project_id,
        message_id=message_id,
        sql=result.sql,
        row_count=None if result.error else result.row_count,
        duration_ms=result.duration_ms,
        error=result.error,
        result_preview_json=None
        if result.error
        else {"columns": result.columns, "rows": result.rows[:PREVIEW_ROWS]},
    )
    session.add(logged)
    await session.commit()
    return logged.id, result


@router.post("")
async def run(body: QueryIn, project: OwnedProject, session: Session, queue: Queue) -> QueryOut:
    query_id, r = await execute_logged(project.id, body.sql, session, queue)
    return QueryOut(
        query_id=query_id,
        sql=r.sql,
        columns=r.columns,
        types=r.types,
        rows=r.rows,
        row_count=r.row_count,
        truncated=r.truncated,
        duration_ms=r.duration_ms,
        error=r.error,
    )
