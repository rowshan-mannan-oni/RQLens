import asyncio
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from api.config import get_settings
from api.db.models import Dataset, DatasetColumn, TableProfile
from api.ingest.names import sanitize_identifier
from api.routes.deps import OwnedProject, Queue, Session
from api.storage import upload_path, uploads_dir

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
    created_at: datetime


class ColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    original_name: str | None
    physical_type: str
    semantic_type: str | None
    profile_json: dict[str, Any] | None


class DatasetProfileOut(BaseModel):
    dataset: DatasetOut
    table: dict[str, Any] | None
    warnings: list[dict[str, Any]]
    columns: list[ColumnOut]


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    project: OwnedProject, session: Session, queue: Queue, request: Request, file: UploadFile
) -> DatasetOut:
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
