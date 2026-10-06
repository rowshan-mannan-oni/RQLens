from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from api.db.models import Dataset, DatasetColumn
from api.ingest.names import sanitize_identifier
from api.profiler.compare import CompareColumn, CompareTable, compare
from api.routes.datasets import DatasetOut
from api.routes.deps import OwnedProject, Queue, Session
from api.routes.relationships import RelationshipOut, list_relationships

router = APIRouter(prefix="/projects/{project_id}", tags=["combine"])

MAX_SELECTED = 20


class CompareOut(BaseModel):
    comparison: dict[str, Any]
    links: list[RelationshipOut]


class JoinSide(BaseModel):
    dataset_id: int
    column: str


class CombineIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    mode: Literal["stack", "join"]
    dataset_ids: list[int] = Field(default_factory=list, max_length=MAX_SELECTED)
    left: JoinSide | None = None
    right: JoinSide | None = None
    how: Literal["left", "inner"] = "left"

    @model_validator(mode="after")
    def check_mode(self) -> "CombineIn":
        if self.mode == "stack" and len(set(self.dataset_ids)) < 2:
            raise ValueError("Stacking needs at least two different datasets.")
        if self.mode == "join":
            if self.left is None or self.right is None:
                raise ValueError("A join needs a left and a right key.")
            if self.left.dataset_id == self.right.dataset_id:
                raise ValueError("A join needs two different datasets.")
        return self


async def _ready_datasets(project_id: int, ids: list[int], session: Session) -> list[Dataset]:
    rows = (
        await session.scalars(
            select(Dataset).where(Dataset.project_id == project_id, Dataset.id.in_(ids))
        )
    ).all()
    found = {d.id: d for d in rows}
    if set(ids) - set(found):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    not_ready = [d.original_filename for d in rows if d.status != "ready"]
    if not_ready:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Not ready yet: {', '.join(not_ready)}")
    return [found[i] for i in ids]


@router.get("/compare")
async def compare_datasets(
    project: OwnedProject,
    session: Session,
    ids: Annotated[str, Query(description="Comma-separated dataset IDs")],
) -> CompareOut:
    try:
        wanted = list(dict.fromkeys(int(x) for x in ids.split(",") if x.strip()))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid dataset IDs") from exc
    if not 1 <= len(wanted) <= MAX_SELECTED:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Select 1 to {MAX_SELECTED} datasets"
        )
    datasets = await _ready_datasets(project.id, wanted, session)

    tables = []
    for d in datasets:
        cols = await session.scalars(
            select(DatasetColumn).where(DatasetColumn.dataset_id == d.id).order_by(DatasetColumn.id)
        )
        tables.append(
            CompareTable(
                dataset_id=d.id,
                label=d.original_filename,
                row_count=d.row_count or 0,
                columns=tuple(
                    CompareColumn(
                        name=c.name,
                        original_name=c.original_name or c.name,
                        physical_type=c.physical_type,
                        semantic_type=c.semantic_type or "",
                        profile=c.profile_json or {},
                    )
                    for c in cols
                ),
            )
        )

    selected = set(wanted)
    links = [
        r
        for r in await list_relationships(project, session)
        if r.left.dataset_id in selected and r.right.dataset_id in selected
    ]
    return CompareOut(comparison=compare(tables), links=links)


@router.post("/combined", status_code=status.HTTP_201_CREATED)
async def create_combined(
    body: CombineIn, project: OwnedProject, session: Session, queue: Queue
) -> DatasetOut:
    if body.mode == "stack":
        ids = list(dict.fromkeys(body.dataset_ids))
        spec: dict[str, Any] = {"mode": "stack", "dataset_ids": ids}
    else:
        assert body.left is not None and body.right is not None
        ids = [body.left.dataset_id, body.right.dataset_id]
        spec = {
            "mode": "join",
            "left": body.left.model_dump(),
            "right": body.right.model_dump(),
            "how": body.how,
        }
    datasets = await _ready_datasets(project.id, ids, session)

    if body.mode == "join":
        assert body.left is not None and body.right is not None
        for side in (body.left, body.right):
            exists = await session.scalar(
                select(DatasetColumn.id).where(
                    DatasetColumn.dataset_id == side.dataset_id, DatasetColumn.name == side.column
                )
            )
            if exists is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown column '{side.column}'"
                )

    taken = set(
        await session.scalars(select(Dataset.table_name).where(Dataset.project_id == project.id))
    )
    dataset = Dataset(
        project_id=project.id,
        table_name=sanitize_identifier(body.name, taken, fallback="combined"),
        original_filename=body.name.strip(),
        size_bytes=0,
        status="queued",
        kind="combined",
        source_json=spec | {"labels": [d.original_filename for d in datasets]},
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    await queue.enqueue_job("combine_dataset", dataset.id)
    return DatasetOut.model_validate(dataset)
