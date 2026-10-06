"""Background jobs for literature tables (run by the arq worker).

extract_paper: fill one paper's cells in one table (all columns, or the given ones).
extract_new_paper: after a paper is read, fill its row in every table of the project.

A job only stores a cell's result if the cell was not edited or re-queued while it ran
(`version`). Cells the user edited keep their value; the AI's answer goes to `ai_json` only.
"""

import dataclasses
import logging
from collections.abc import Sequence
from typing import Any

from arq import Retry
from sqlalchemy import select

from api.config import get_settings
from api.db.models import Paper, Passage, Project, ReviewCell, ReviewTable
from api.db.session import get_sessionmaker
from api.limits import ai_usage, over_limit_message
from api.llm.client import LLMClient
from api.review.extract import CellResult, PaperInput, extract
from api.review.templates import TemplateColumn
from api.rq.jobs import TRANSIENT

log = logging.getLogger(__name__)

TRIES = 4
RETRY_S = 30


def table_columns(table: ReviewTable) -> list[TemplateColumn]:
    return [TemplateColumn.model_validate(c) for c in table.columns_json]


async def extract_paper(
    ctx: dict[str, Any],
    table_id: int,
    paper_id: int,
    keys: list[str] | None = None,
    include_user: bool = False,
) -> str:
    async with get_sessionmaker()() as session:
        table = await session.get(ReviewTable, table_id)
        paper = await session.get(Paper, paper_id)
        if table is None or paper is None or paper.project_id != table.project_id:
            return "missing"
        if paper.status != "ready":
            return "not_ready"
        project = await session.get(Project, table.project_id)
        assert project is not None
        columns = [c for c in table_columns(table) if keys is None or c.key in keys]
        cells = {
            c.column_key: c
            for c in await session.scalars(
                select(ReviewCell).where(
                    ReviewCell.table_id == table_id, ReviewCell.paper_id == paper_id
                )
            )
        }
        target: list[TemplateColumn] = []
        for col in columns:
            cell = cells.get(col.key)
            if cell is None:
                cell = ReviewCell(table_id=table_id, paper_id=paper_id, column_key=col.key)
                session.add(cell)
                cells[col.key] = cell
            if cell.source == "user" and not include_user:
                continue
            if cell.source != "user":
                cell.status = "running"
            target.append(col)
        await session.flush()
        versions = {k: c.version for k, c in cells.items()}
        passages = list(
            await session.scalars(
                select(Passage).where(Passage.paper_id == paper_id).order_by(Passage.ordinal)
            )
        )
        paper_in = PaperInput(
            passages,
            paper.title,
            list(paper.authors_json or []) or None,
            paper.year,
            paper.venue,
            paper.doi,
        )
        reason = (
            "LLM_API_KEY is not set."
            if not get_settings().llm_api_key
            else over_limit_message(await ai_usage(session, project.user_id))
        )
        await session.commit()
    if not target:
        return "nothing"

    client = LLMClient.from_settings() if reason is None else None
    embed = None
    if client is not None and client.embedding_model:
        llm = client

        async def embed(texts: Sequence[str]) -> list[list[float]]:
            return await llm.embed(texts, step="review_retrieval", project_id=table.project_id)

    try:
        result = await extract(
            client,
            target,
            paper_in,
            project_id=table.project_id,
            embed=embed,
            no_ai_reason=reason or "",
        )
    except TRANSIENT as exc:
        attempt = int(ctx.get("job_try", 1))
        if attempt < TRIES:
            delay = RETRY_S * attempt
            await _mark(table_id, paper_id, target, versions, "queued",
                        f"AI provider busy; retrying in {delay} s")  # fmt: skip
            raise Retry(defer=delay) from exc
        await _mark(table_id, paper_id, target, versions, "failed", f"AI provider busy: {exc}")
        return "failed"
    except Exception as exc:
        log.exception("extract_paper %s/%s failed", table_id, paper_id)
        await _mark(table_id, paper_id, target, versions, "failed", f"{type(exc).__name__}: {exc}")
        return "failed"

    await _store(table_id, paper_id, result.cells, versions)
    return "done"


async def _mark(
    table_id: int,
    paper_id: int,
    columns: Sequence[TemplateColumn],
    versions: dict[str, int],
    status: str,
    note: str,
) -> None:
    async with get_sessionmaker()() as session:
        for cell in await _cells(session, table_id, paper_id, [c.key for c in columns]):
            if cell.version == versions.get(cell.column_key) and cell.source != "user":
                cell.status, cell.note = status, note[:2000]
        await session.commit()


async def _cells(session: Any, table_id: int, paper_id: int, keys: list[str]) -> list[ReviewCell]:
    return list(
        await session.scalars(
            select(ReviewCell).where(
                ReviewCell.table_id == table_id,
                ReviewCell.paper_id == paper_id,
                ReviewCell.column_key.in_(keys),
            )
        )
    )


async def _store(
    table_id: int, paper_id: int, results: Sequence[CellResult], versions: dict[str, int]
) -> None:
    async with get_sessionmaker()() as session:
        cells = {
            c.column_key: c
            for c in await _cells(session, table_id, paper_id, [r.column_key for r in results])
        }
        for r in results:
            cell = cells.get(r.column_key)
            if cell is None or cell.version != versions.get(r.column_key):
                continue  # edited or re-queued while the job ran
            snapshot = dataclasses.asdict(r)
            cell.ai_json = snapshot
            if cell.source == "user":
                continue  # the user's value stays
            cell.status = r.status
            cell.value_json = r.value
            cell.source = r.source
            cell.citations_json = r.citations
            cell.confidence = r.confidence
            cell.note = r.note
            cell.review = None
        await session.commit()


async def extract_new_paper(ctx: dict[str, Any], paper_id: int) -> str:
    """Queue a newly read paper's row in every literature table of its project."""
    async with get_sessionmaker()() as session:
        paper = await session.get(Paper, paper_id)
        if paper is None:
            return "missing"
        tables = list(
            await session.scalars(
                select(ReviewTable).where(ReviewTable.project_id == paper.project_id)
            )
        )
        for table in tables:
            await queue_cells(session, table, [paper_id], None)
        await session.commit()
    for table in tables:
        await ctx["redis"].enqueue_job("extract_paper", table.id, paper_id)
    return f"queued in {len(tables)} tables"


async def queue_cells(
    session: Any,
    table: ReviewTable,
    paper_ids: Sequence[int],
    keys: Sequence[str] | None,
    *,
    include_user: bool = False,
) -> int:
    """Create or reset the cells to (re)extract, bumping their version. Returns how many."""
    columns = [c.key for c in table_columns(table) if keys is None or c.key in keys]
    existing = {
        (c.paper_id, c.column_key): c
        for c in await session.scalars(
            select(ReviewCell).where(
                ReviewCell.table_id == table.id, ReviewCell.paper_id.in_(paper_ids)
            )
        )
    }
    n = 0
    for pid in paper_ids:
        for key in columns:
            cell = existing.get((pid, key))
            if cell is None:
                session.add(
                    ReviewCell(table_id=table.id, paper_id=pid, column_key=key, status="queued")
                )
                n += 1
                continue
            if cell.source == "user" and not include_user:
                continue
            cell.version += 1
            if cell.source != "user":
                cell.status, cell.note = "queued", None
            n += 1
    return n
