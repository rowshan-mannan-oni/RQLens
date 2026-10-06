import asyncio
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import LockError
from sqlalchemy import select

from api.config import get_settings
from api.db.models import Dataset, DatasetColumn, TableProfile
from api.ingest.names import sanitize_identifier
from api.ingest.pipeline import drop_table
from api.limits import WithinAIBudget, enforce_dataset_limit
from api.routes.deps import PROCESSING, OwnedProject, Queue, Session, duckdb_lock
from api.semantic.dictionary import DictionaryError, match_entries, parse_dictionary
from api.storage import project_db_path, upload_path, uploads_dir

router = APIRouter(prefix="/projects/{project_id}/datasets", tags=["datasets"])


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    table_name: str
    original_filename: str
    status: str
    error: str | None
    row_count: int | None
    column_count: int | None
    size_bytes: int
    describe_status: str | None
    describe_error: str | None
    kind: str
    source_json: dict[str, Any] | None
    created_at: datetime


class ColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    original_name: str | None
    physical_type: str
    semantic_type: str | None
    description: str | None
    description_source: str | None
    description_confidence: str | None
    is_pii: bool
    pii_reason: str | None
    profile_json: dict[str, Any] | None


class ColumnUpdate(BaseModel):
    # Empty or null clears the description so the model may describe the column again.
    description: str | None = Field(default=None, max_length=2000)


class DictionaryResult(BaseModel):
    matched: int
    unmatched: list[str]


class DatasetProfileOut(BaseModel):
    dataset: DatasetOut
    table: dict[str, Any] | None
    warnings: list[dict[str, Any]]
    columns: list[ColumnOut]


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    project: OwnedProject, session: Session, queue: Queue, request: Request, file: UploadFile
) -> DatasetOut:
    await enforce_dataset_limit(session, project.id)
    limit = get_settings().max_upload_bytes
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only .csv files are accepted")
    if file.size is not None and file.size > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"File is larger than {limit // 2**20} MB"
        )

    directory = uploads_dir(project.id)
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f"tmp-{uuid.uuid4().hex}.csv"
    await asyncio.to_thread(_save, file, tmp)
    size = tmp.stat().st_size
    if size == 0:
        tmp.unlink()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")

    taken = set(
        await session.scalars(select(Dataset.table_name).where(Dataset.project_id == project.id))
    )
    table_name = sanitize_identifier(Path(filename).stem, taken, fallback="table")
    dataset = Dataset(
        project_id=project.id,
        table_name=table_name,
        original_filename=filename[:500],
        size_bytes=size,
        status="queued",
    )
    session.add(dataset)
    await session.flush()
    tmp.rename(upload_path(project.id, dataset.id))
    await session.commit()
    await session.refresh(dataset)

    await queue.enqueue_job("ingest_dataset", dataset.id)
    return DatasetOut.model_validate(dataset)


def _save(file: UploadFile, path: Path) -> None:
    file.file.seek(0)
    with path.open("wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)


@router.get("")
async def list_datasets(project: OwnedProject, session: Session) -> list[DatasetOut]:
    rows = await session.scalars(
        select(Dataset).where(Dataset.project_id == project.id).order_by(Dataset.id)
    )
    return [DatasetOut.model_validate(d) for d in rows]


@router.get("/{dataset_id}/profile")
async def get_profile(
    dataset_id: int, project: OwnedProject, session: Session
) -> DatasetProfileOut:
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None or dataset.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")

    table = await session.scalar(
        select(TableProfile)
        .where(TableProfile.dataset_id == dataset.id)
        .order_by(TableProfile.id.desc())
        .limit(1)
    )
    columns = await session.scalars(
        select(DatasetColumn)
        .where(DatasetColumn.dataset_id == dataset.id)
        .order_by(DatasetColumn.id)
    )
    return DatasetProfileOut(
        dataset=DatasetOut.model_validate(dataset),
        table=table.profile_json if table else None,
        warnings=(table.warnings_json or []) if table else [],
        columns=[ColumnOut.model_validate(c) for c in columns],
    )


async def _owned_dataset(dataset_id: int, project_id: int, session: Session) -> Dataset:
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None or dataset.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    return dataset


@router.patch("/{dataset_id}/columns/{column_id}")
async def update_column(
    dataset_id: int, column_id: int, body: ColumnUpdate, project: OwnedProject, session: Session
) -> ColumnOut:
    await _owned_dataset(dataset_id, project.id, session)
    column = await session.get(DatasetColumn, column_id)
    if column is None or column.dataset_id != dataset_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Column not found")
    text = (body.description or "").strip()
    column.description = text or None
    column.description_source = "user" if text else None
    column.description_confidence = None
    await session.commit()
    return ColumnOut.model_validate(column)


@router.post("/{dataset_id}/dictionary")
async def upload_dictionary(
    dataset_id: int, project: OwnedProject, session: Session, file: UploadFile
) -> DictionaryResult:
    """Apply a data dictionary CSV. Its descriptions replace model-written ones."""
    await _owned_dataset(dataset_id, project.id, session)
    raw = await file.read(MAX_DICTIONARY_BYTES + 1)
    if len(raw) > MAX_DICTIONARY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Dictionary is larger than 5 MB")
    try:
        entries = parse_dictionary(raw)
    except DictionaryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    columns = (
        await session.scalars(select(DatasetColumn).where(DatasetColumn.dataset_id == dataset_id))
    ).all()
    matched, unmatched = match_entries(entries, [(c.name, c.original_name) for c in columns])
    for c in columns:
        if c.name in matched and c.description_source != "user":
            c.description = matched[c.name]
            c.description_source = "dictionary"
            c.description_confidence = None
    await session.commit()
    return DictionaryResult(matched=len(matched), unmatched=unmatched)


@router.post("/{dataset_id}/describe", status_code=status.HTTP_202_ACCEPTED)
async def redescribe(
    dataset_id: int, project: OwnedProject, session: Session, queue: Queue, _: WithinAIBudget
) -> DatasetOut:
    """Ask the model again for columns without a user or dictionary description."""
    dataset = await _owned_dataset(dataset_id, project.id, session)
    if dataset.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "The dataset is not ready yet")
    dataset.describe_status = "pending"
    dataset.describe_error = None
    await session.commit()
    await queue.enqueue_job("describe_dataset", dataset.id)
    return DatasetOut.model_validate(dataset)


MAX_DICTIONARY_BYTES = 5 * 1024 * 1024


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: int, project: OwnedProject, session: Session, queue: Queue
) -> None:
    """Delete a dataset: its DuckDB table, uploaded file, profile, descriptions and links.

    Combined datasets built from it are kept; they are stored as their own tables.
    """
    dataset = await _owned_dataset(dataset_id, project.id, session)
    if dataset.status in PROCESSING:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This dataset is still processing; delete it when it is done"
        )
    try:
        async with duckdb_lock(queue, project.id):
            await asyncio.to_thread(drop_table, project_db_path(project.id), dataset.table_name)
    except LockError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The project is busy; try again shortly"
        ) from exc
    upload_path(project.id, dataset.id).unlink(missing_ok=True)
    # Columns, profiles and links are removed by ON DELETE CASCADE.
    await session.delete(dataset)
    await session.commit()
