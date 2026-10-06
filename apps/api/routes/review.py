"""Literature review: templates, review tables, cells, re-runs and exports."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from api.auth import CurrentUser
from api.db.models import Paper, ResearchQuestion, ReviewCell, ReviewTable, ReviewTemplate
from api.review import export
from api.review.jobs import queue_cells, table_columns
from api.review.related import question_terms, related_papers
from api.review.templates import (
    BUILTIN,
    DEFAULT_TEMPLATE,
    Template,
    TemplateColumn,
    slug,
    unique_keys,
)
from api.routes.deps import OwnedProject, Queue, Session
from api.routes.papers import PaperOut

templates_router = APIRouter(prefix="/templates", tags=["review"])
router = APIRouter(prefix="/projects/{project_id}/review-tables", tags=["review"])

MAX_COLUMNS = 40


# --- templates -------------------------------------------------------------------------------


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    columns: list[TemplateColumn] = Field(min_length=1, max_length=MAX_COLUMNS)


def _user_template(t: ReviewTemplate) -> Template:
    return Template(
        key=f"user:{t.id}",
        name=t.name,
        description=t.description or "",
        columns=[TemplateColumn.model_validate(c) for c in t.columns_json],
        builtin=False,
        version=t.version,
    )


async def resolve_template(session: Session, user_id: int, key: str) -> Template:
    if key in BUILTIN:
        return BUILTIN[key]
    if key.startswith("user:") and key[5:].isdigit():
        t = await session.get(ReviewTemplate, int(key[5:]))
        if t is not None and t.user_id == user_id:
            return _user_template(t)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")


async def _owned_template(session: Session, user_id: int, template_id: int) -> ReviewTemplate:
    t = await session.get(ReviewTemplate, template_id)
    if t is None or t.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return t


@templates_router.get("")
async def list_templates(user: CurrentUser, session: Session) -> list[Template]:
    own = await session.scalars(
        select(ReviewTemplate).where(ReviewTemplate.user_id == user.id).order_by(ReviewTemplate.id)
    )
    return [*BUILTIN.values(), *(_user_template(t) for t in own)]


@templates_router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(body: TemplateIn, user: CurrentUser, session: Session) -> Template:
    t = ReviewTemplate(
        user_id=user.id,
        name=body.name.strip(),
        description=body.description,
        columns_json=[c.model_dump() for c in unique_keys(body.columns)],
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return _user_template(t)


@templates_router.put("/{template_id}")
async def update_template(
    template_id: int, body: TemplateIn, user: CurrentUser, session: Session
) -> Template:
    """Change a template. Tables already made from it keep their own copy of the columns."""
    t = await _owned_template(session, user.id, template_id)
    t.name, t.description = body.name.strip(), body.description
    t.columns_json = [c.model_dump() for c in unique_keys(body.columns)]
    t.version += 1
    await session.commit()
    await session.refresh(t)
    return _user_template(t)


@templates_router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: int, user: CurrentUser, session: Session) -> None:
    await session.delete(await _owned_template(session, user.id, template_id))
    await session.commit()


# --- tables ----------------------------------------------------------------------------------


class TableIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    template_key: str = DEFAULT_TEMPLATE


class TableSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    template_key: str
    created_at: datetime


class CellOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    paper_id: int
    column_key: str
    status: str
    value_json: Any
    source: str | None
    citations_json: list[dict[str, Any]] | None
    confidence: str | None
    note: str | None
    ai_json: dict[str, Any] | None
    review: str | None
    updated_at: datetime


class TableOut(TableSummary):
    columns: list[TemplateColumn]
    papers: list[PaperOut]
    cells: list[CellOut]


class ColumnIn(BaseModel):
    column: TemplateColumn
    position: int | None = None  # index to insert at; end when omitted


class ColumnUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    instructions: str | None = Field(default=None, max_length=2000)


class ColumnOrder(BaseModel):
    keys: list[str]


class CellEdit(BaseModel):
    value: str | float | list[str] | None


class CellReview(BaseModel):
    decision: Literal["accepted", "rejected"] | None


class RerunIn(BaseModel):
    paper_id: int | None = None
    column_key: str | None = None


async def get_table(project: OwnedProject, table_id: int, session: Session) -> ReviewTable:
    table = await session.get(ReviewTable, table_id)
    if table is None or table.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Table not found")
    return table


async def _ready_paper_ids(session: Session, project_id: int) -> list[int]:
    return list(
        await session.scalars(
            select(Paper.id).where(Paper.project_id == project_id, Paper.status == "ready")
        )
    )


async def _enqueue(
    queue: Queue,
    table_id: int,
    paper_ids: list[int],
    keys: list[str] | None,
    include_user: bool = False,
) -> None:
    for pid in paper_ids:
        await queue.enqueue_job("extract_paper", table_id, pid, keys, include_user)


async def _table_out(session: Session, table: ReviewTable) -> TableOut:
    papers = await session.scalars(
        select(Paper)
        .where(Paper.project_id == table.project_id)
        .order_by(Paper.folder.nulls_first(), Paper.filename, Paper.id)
    )
    cells = await session.scalars(select(ReviewCell).where(ReviewCell.table_id == table.id))
    return TableOut(
        id=table.id,
        name=table.name,
        template_key=table.template_key,
        created_at=table.created_at,
        columns=table_columns(table),
        papers=[PaperOut.model_validate(p) for p in papers],
        cells=[CellOut.model_validate(c) for c in cells],
    )


@router.get("")
async def list_tables(project: OwnedProject, session: Session) -> list[TableSummary]:
    rows = await session.scalars(
        select(ReviewTable).where(ReviewTable.project_id == project.id).order_by(ReviewTable.id)
    )
    return [TableSummary.model_validate(t) for t in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_table(
    body: TableIn, project: OwnedProject, user: CurrentUser, session: Session, queue: Queue
) -> TableOut:
    """Make a table from a template and start filling it for every paper that is ready."""
    template = await resolve_template(session, user.id, body.template_key)
    table = ReviewTable(
        project_id=project.id,
        name=(body.name or "").strip() or template.name,
        template_key=template.key,
        columns_json=[c.model_dump() for c in unique_keys(template.columns)],
    )
    session.add(table)
    await session.flush()
    papers = await _ready_paper_ids(session, project.id)
    await queue_cells(session, table, papers, None)
    await session.commit()
    await session.refresh(table)
    await _enqueue(queue, table.id, papers, None)
    return await _table_out(session, table)


@router.get("/{table_id}")
async def table_detail(project: OwnedProject, table_id: int, session: Session) -> TableOut:
    return await _table_out(session, await get_table(project, table_id, session))


class TableRename(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.patch("/{table_id}")
async def rename_table(
    project: OwnedProject, table_id: int, body: TableRename, session: Session
) -> TableSummary:
    table = await get_table(project, table_id, session)
    table.name = body.name.strip()
    await session.commit()
    await session.refresh(table)
    return TableSummary.model_validate(table)


@router.delete("/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table(project: OwnedProject, table_id: int, session: Session) -> None:
    await session.delete(await get_table(project, table_id, session))
    await session.commit()


# --- columns ---------------------------------------------------------------------------------


@router.post("/{table_id}/columns", status_code=status.HTTP_201_CREATED)
async def add_column(
    project: OwnedProject, table_id: int, body: ColumnIn, session: Session, queue: Queue
) -> TableOut:
    """Add a column; only that column is extracted for the papers."""
    table = await get_table(project, table_id, session)
    columns = table_columns(table)
    if len(columns) >= MAX_COLUMNS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A table has at most {MAX_COLUMNS} columns")
    position = len(columns) if body.position is None else max(0, min(body.position, len(columns)))
    taken = {c.key for c in columns}
    base = new_key = slug(body.column.label)
    n = 2
    while new_key in taken:
        new_key, n = f"{base[:60]}_{n}", n + 1
    columns.insert(position, body.column.model_copy(update={"key": new_key}))
    table.columns_json = [c.model_dump() for c in columns]
    papers = await _ready_paper_ids(session, project.id)
    await queue_cells(session, table, papers, [new_key])
    await session.commit()
    await _enqueue(queue, table.id, papers, [new_key])
    return await _table_out(session, table)


@router.patch("/{table_id}/columns/{key}")
async def update_column(
    project: OwnedProject, table_id: int, key: str, body: ColumnUpdate, session: Session
) -> TableOut:
    """Rename a column or change its instructions. Re-run the column to apply new
    instructions to existing cells."""
    table = await get_table(project, table_id, session)
    columns = table_columns(table)
    col = next((c for c in columns if c.key == key), None)
    if col is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Column not found")
    if body.label is not None:
        col.label = body.label.strip()
    if body.instructions is not None:
        col.instructions = body.instructions
    table.columns_json = [c.model_dump() for c in columns]
    await session.commit()
    return await _table_out(session, table)


@router.put("/{table_id}/columns")
async def reorder_columns(
    project: OwnedProject, table_id: int, body: ColumnOrder, session: Session
) -> TableOut:
    table = await get_table(project, table_id, session)
    columns = {c.key: c for c in table_columns(table)}
    if sorted(body.keys) != sorted(columns):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give every column key exactly once")
    table.columns_json = [columns[k].model_dump() for k in body.keys]
    await session.commit()
    return await _table_out(session, table)


@router.delete("/{table_id}/columns/{key}")
async def delete_column(
    project: OwnedProject, table_id: int, key: str, session: Session
) -> TableOut:
    table = await get_table(project, table_id, session)
    columns = table_columns(table)
    if not any(c.key == key for c in columns):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Column not found")
    if len(columns) == 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A table needs at least one column")
    table.columns_json = [c.model_dump() for c in columns if c.key != key]
    await session.execute(
        delete(ReviewCell).where(ReviewCell.table_id == table.id, ReviewCell.column_key == key)
    )
    await session.commit()
    return await _table_out(session, table)


# --- cells -----------------------------------------------------------------------------------


async def _cell(session: Session, table: ReviewTable, cell_id: int) -> ReviewCell:
    cell = await session.get(ReviewCell, cell_id)
    if cell is None or cell.table_id != table.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cell not found")
    return cell


@router.patch("/{table_id}/cells/{cell_id}")
async def edit_cell(
    project: OwnedProject, table_id: int, cell_id: int, body: CellEdit, session: Session
) -> CellOut:
    """Set a cell by hand. Re-runs never overwrite it; the AI's answer stays in `ai_json`."""
    table = await get_table(project, table_id, session)
    cell = await _cell(session, table, cell_id)
    value = body.value
    if isinstance(value, str):
        value = value.strip() or None
    if isinstance(value, list):
        value = [v.strip() for v in value if v.strip()] or None
    cell.value_json = value
    cell.source = "user"
    cell.citations_json = []  # the AI's citations need not support your value; see ai_json
    cell.status = "done" if value is not None else "not_found"
    cell.note = None if value is not None else "Cleared by you."
    cell.review = None
    cell.version += 1  # a running job must not overwrite the edit
    await session.commit()
    await session.refresh(cell)
    return CellOut.model_validate(cell)


@router.post("/{table_id}/cells/{cell_id}/revert")
async def revert_cell(
    project: OwnedProject, table_id: int, cell_id: int, session: Session
) -> CellOut:
    """Undo a manual edit: go back to the AI's last answer."""
    table = await get_table(project, table_id, session)
    cell = await _cell(session, table, cell_id)
    ai = cell.ai_json
    if not ai:
        raise HTTPException(status.HTTP_409_CONFLICT, "There is no AI answer to go back to")
    cell.value_json = ai.get("value")
    cell.status = ai.get("status", "done")
    cell.source = ai.get("source", "llm")
    cell.citations_json = ai.get("citations") or []
    cell.confidence = ai.get("confidence")
    cell.note = ai.get("note")
    cell.review = None
    cell.version += 1
    await session.commit()
    await session.refresh(cell)
    return CellOut.model_validate(cell)


@router.post("/{table_id}/cells/{cell_id}/review")
async def review_cell(
    project: OwnedProject, table_id: int, cell_id: int, body: CellReview, session: Session
) -> CellOut:
    """Accept or reject an AI value. Rejected values are left out of exports."""
    table = await get_table(project, table_id, session)
    cell = await _cell(session, table, cell_id)
    cell.review = body.decision
    await session.commit()
    await session.refresh(cell)
    return CellOut.model_validate(cell)


@router.post("/{table_id}/rerun", status_code=status.HTTP_202_ACCEPTED)
async def rerun(
    project: OwnedProject, table_id: int, body: RerunIn, session: Session, queue: Queue
) -> dict[str, int]:
    """Re-extract a cell (paper and column), a paper's row, a column, or the whole table.
    Cells you edited keep your value; a single-cell re-run refreshes the AI's answer beside it.
    """
    table = await get_table(project, table_id, session)
    papers = await _ready_paper_ids(session, project.id)
    if body.paper_id is not None:
        if body.paper_id not in papers:
            raise HTTPException(status.HTTP_409_CONFLICT, "That paper is not ready")
        papers = [body.paper_id]
    keys = None
    if body.column_key is not None:
        if body.column_key not in {c.key for c in table_columns(table)}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Column not found")
        keys = [body.column_key]
    single = body.paper_id is not None and body.column_key is not None
    n = await queue_cells(session, table, papers, keys, include_user=single)
    await session.commit()
    await _enqueue(queue, table.id, papers, keys, include_user=single)
    return {"cells": n, "papers": len(papers)}


# --- research questions ----------------------------------------------------------------------


class RelatedOut(BaseModel):
    rq_id: int
    terms: list[str]
    papers: list[dict[str, Any]]  # paper_id, score, matched_terms, cells


@router.get("/{table_id}/related")
async def related(project: OwnedProject, table_id: int, session: Session, rq_id: int) -> RelatedOut:
    """Papers whose problem, questions or findings relate to a research question."""
    table = await get_table(project, table_id, session)
    rq = await session.get(ResearchQuestion, rq_id)
    if rq is None or rq.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Research question not found")
    rq_terms = question_terms(rq.text, rq.parsed_json)
    papers = await session.execute(
        select(Paper.id, Paper.title).where(Paper.project_id == project.id, Paper.status == "ready")
    )
    cells = list(await session.scalars(select(ReviewCell).where(ReviewCell.table_id == table.id)))
    columns = {c.key: c.label for c in table_columns(table) if c.metadata is None}
    found = related_papers(rq_terms, [(p.id, p.title) for p in papers], cells, columns)
    return RelatedOut(
        rq_id=rq.id,
        terms=sorted(rq_terms),
        papers=[
            {"paper_id": r.paper_id, "score": r.score, "matched_terms": r.matched_terms,
             "cells": r.cells}
            for r in found
        ],
    )  # fmt: skip


# --- export ----------------------------------------------------------------------------------


@router.get("/{table_id}/export")
async def export_table(
    project: OwnedProject,
    table_id: int,
    session: Session,
    format: Annotated[Literal["csv", "xlsx", "md", "bib"], Query()] = "csv",
) -> Response:
    out = await _table_out(session, await get_table(project, table_id, session))
    data = export.TableData(
        name=out.name,
        columns=out.columns,
        papers=[p.model_dump() for p in out.papers if p.status == "ready"],
        cells=[c.model_dump() for c in out.cells],
    )
    body, media = export.render(data, format)
    filename = f"{export.slug(out.name)}.{format}"
    return Response(
        body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
