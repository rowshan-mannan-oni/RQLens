"""Papers for the literature review: upload PDFs, read their passages, serve the file."""

import asyncio
import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from api.config import get_settings
from api.db.models import Paper, Passage
from api.limits import enforce_paper_limit
from api.routes.deps import OwnedProject, Queue, Session
from api.storage import paper_path, papers_dir

router = APIRouter(prefix="/projects/{project_id}/papers", tags=["papers"])

PDF_MAGIC = b"%PDF-"


class PaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    folder: str | None
    size_bytes: int
    status: str
    error: str | None
    page_count: int | None
    passage_count: int | None
    title: str | None
    authors_json: list[str] | None
    year: int | None
    venue: str | None
    doi: str | None
    metadata_source_json: dict[str, str] | None
    ocr_pages_json: list[int] | None
    created_at: datetime


class PaperDetail(PaperOut):
    pages_json: list[list[float]] | None
    sections_json: list[dict[str, Any]] | None


class PassageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ordinal: int
    label: str
    page: int
    section: str | None
    section_kind: str
    kind: str
    text: str
    rects_json: list[list[float]]


class PaperUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=1000)
    authors: list[str] | None = Field(default=None, max_length=200)
    year: int | None = Field(default=None, ge=1500, le=2100)
    venue: str | None = Field(default=None, max_length=1000)
    doi: str | None = Field(default=None, max_length=300)


async def get_paper(project: OwnedProject, paper_id: int, session: Session) -> Paper:
    paper = await session.get(Paper, paper_id)
    if paper is None or paper.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Paper not found")
    return paper


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_paper(
    project: OwnedProject,
    session: Session,
    queue: Queue,
    file: UploadFile,
    folder: Annotated[str | None, Form(max_length=500)] = None,
) -> PaperOut:
    """Upload one PDF. A folder upload sends each PDF with its subfolder path in `folder`."""
    await enforce_paper_limit(session, project.id)
    limit = get_settings().max_paper_bytes
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only .pdf files are accepted")
    if file.size is not None and file.size > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"File is larger than {limit // 2**20} MB"
        )

    directory = papers_dir(project.id)
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f"tmp-{uuid.uuid4().hex}.pdf"
    try:
        size, digest, head = await asyncio.to_thread(_save, file, tmp, limit)
    except ValueError as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    if not head.startswith(PDF_MAGIC):
        tmp.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is not a PDF")

    duplicate = await session.scalar(
        select(Paper).where(Paper.project_id == project.id, Paper.sha256 == digest)
    )
    if duplicate is not None:
        tmp.unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Already in this project as {duplicate.filename}"
        )

    clean_folder = "/".join(p for p in (folder or "").replace("\\", "/").split("/") if p)
    paper = Paper(
        project_id=project.id,
        filename=filename[:500],
        folder=clean_folder or None,
        sha256=digest,
        size_bytes=size,
        status="queued",
    )
    session.add(paper)
    await session.flush()
    tmp.rename(paper_path(project.id, paper.id))
    await session.commit()
    await session.refresh(paper)
    await queue.enqueue_job("parse_paper", paper.id)
    return PaperOut.model_validate(paper)


def _save(file: UploadFile, path: Path, limit: int) -> tuple[int, str, bytes]:
    """Copy the upload to disk; returns its size, SHA-256 and first bytes."""
    file.file.seek(0)
    digest = hashlib.sha256()
    size = 0
    head = b""
    with path.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            if not head:
                head = chunk[:8]
            size += len(chunk)
            if size > limit:
                raise ValueError(f"File is larger than {limit // 2**20} MB")
            digest.update(chunk)
            out.write(chunk)
    return size, digest.hexdigest(), head


@router.get("")
async def list_papers(project: OwnedProject, session: Session) -> list[PaperOut]:
    rows = await session.scalars(
        select(Paper)
        .where(Paper.project_id == project.id)
        .order_by(Paper.folder.nulls_first(), Paper.filename, Paper.id)
    )
    return [PaperOut.model_validate(p) for p in rows]


@router.get("/{paper_id}")
async def paper_detail(project: OwnedProject, paper_id: int, session: Session) -> PaperDetail:
    return PaperDetail.model_validate(await get_paper(project, paper_id, session))


@router.get("/{paper_id}/passages")
async def paper_passages(
    project: OwnedProject, paper_id: int, session: Session
) -> list[PassageOut]:
    paper = await get_paper(project, paper_id, session)
    rows = await session.scalars(
        select(Passage).where(Passage.paper_id == paper.id).order_by(Passage.ordinal)
    )
    return [PassageOut.model_validate(p) for p in rows]


@router.get("/{paper_id}/file")
async def paper_file(project: OwnedProject, paper_id: int, session: Session) -> FileResponse:
    paper = await get_paper(project, paper_id, session)
    path = paper_path(project.id, paper.id)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The PDF file is missing")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=paper.filename,
        content_disposition_type="inline",
    )


@router.patch("/{paper_id}")
async def update_paper(
    project: OwnedProject, paper_id: int, body: PaperUpdate, session: Session
) -> PaperOut:
    """Correct the paper's metadata. Corrected fields are marked as set by the user."""
    paper = await get_paper(project, paper_id, session)
    sources = dict(paper.metadata_source_json or {})
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if isinstance(value, str):
            value = value.strip() or None
        if field == "authors":
            value = [a.strip() for a in value or [] if a.strip()] or None
            paper.authors_json = value
        else:
            setattr(paper, field, value)
        if value is None:
            sources.pop(field, None)
        else:
            sources[field] = "user"
    paper.metadata_source_json = sources
    await session.commit()
    await session.refresh(paper)
    return PaperOut.model_validate(paper)


@router.post("/{paper_id}/reparse", status_code=status.HTTP_202_ACCEPTED)
async def reparse_paper(
    project: OwnedProject, paper_id: int, session: Session, queue: Queue
) -> PaperOut:
    paper = await get_paper(project, paper_id, session)
    if paper.status in ("queued", "parsing"):
        raise HTTPException(status.HTTP_409_CONFLICT, "The paper is already being read")
    paper.status, paper.error = "queued", None
    await session.commit()
    await session.refresh(paper)
    await queue.enqueue_job("parse_paper", paper.id)
    return PaperOut.model_validate(paper)


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paper(project: OwnedProject, paper_id: int, session: Session) -> None:
    """Delete a paper with its passages and review cells."""
    paper = await get_paper(project, paper_id, session)
    path = paper_path(project.id, paper.id)
    await session.delete(paper)
    await session.commit()
    path.unlink(missing_ok=True)
