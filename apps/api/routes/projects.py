import asyncio
import shutil
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import LockError
from sqlalchemy import select

from api import samples
from api.auth import CurrentUser
from api.db.models import Dataset, Project, ResearchQuestion
from api.limits import enforce_project_limit
from api.routes.deps import PROCESSING, OwnedProject, Queue, Session, duckdb_lock
from api.storage import project_dir, upload_path

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic: str | None = Field(default=None, max_length=5000)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    topic: str | None
    status: str
    share_samples: bool
    created_at: datetime


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    topic: str | None = Field(default=None, max_length=5000)
    share_samples: bool | None = None


@router.get("")
async def list_projects(user: CurrentUser, session: Session) -> list[ProjectOut]:
    rows = await session.scalars(
        select(Project).where(Project.user_id == user.id).order_by(Project.created_at.desc())
    )
    return [ProjectOut.model_validate(p) for p in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, user: CurrentUser, session: Session) -> ProjectOut:
    await enforce_project_limit(session, user.id)
    project = Project(user_id=user.id, title=body.title.strip(), topic=body.topic)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectOut.model_validate(project)


@router.post("/sample", status_code=status.HTTP_201_CREATED)
async def create_sample_project(user: CurrentUser, session: Session, queue: Queue) -> ProjectOut:
    """A ready-made project with a public dataset and three research questions."""
    await enforce_project_limit(session, user.id)
    project = Project(user_id=user.id, title=samples.TITLE, topic=samples.TOPIC)
    session.add(project)
    await session.flush()
    dataset = Dataset(
        project_id=project.id,
        table_name="penguins",
        original_filename="penguins.csv",
        size_bytes=samples.SAMPLE_CSV.stat().st_size,
        status="queued",
    )
    session.add(dataset)
    for i, q in enumerate(samples.QUESTIONS):
        # Queued without a job: the worker assesses waiting questions once the data is ready.
        session.add(
            ResearchQuestion(
                project_id=project.id,
                text=q["text"],
                position=i,
                parsed_json=q["parsed"],
                mapping_json=q["mapping"],
                status="queued",
                version=0,
            )
        )
    await session.flush()
    target = upload_path(project.id, dataset.id)
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(shutil.copyfile, samples.SAMPLE_CSV, target)
    await session.commit()
    await session.refresh(project)
    await queue.enqueue_job("ingest_dataset", dataset.id)
    return ProjectOut.model_validate(project)


@router.get("/{project_id}")
async def get_project(project: OwnedProject) -> ProjectOut:
    return ProjectOut.model_validate(project)


@router.patch("/{project_id}")
async def update_project(
    body: ProjectUpdate, project: OwnedProject, session: Session
) -> ProjectOut:
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None and field != "topic":
            continue
        setattr(project, field, value.strip() if isinstance(value, str) else value)
    await session.commit()
    await session.refresh(project)
    return ProjectOut.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project: OwnedProject, session: Session, queue: Queue) -> None:
    """Delete a project with all its data: DuckDB file, uploads, profiles, queries and traces."""
    processing = await session.scalar(
        select(Dataset.id).where(Dataset.project_id == project.id, Dataset.status.in_(PROCESSING))
    )
    if processing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A dataset is still processing; delete the project after it"
        )
    try:
        async with duckdb_lock(queue, project.id):
            await asyncio.to_thread(shutil.rmtree, project_dir(project.id), ignore_errors=True)
    except LockError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The project is busy; try again shortly"
        ) from exc
    # Datasets, queries, LLM call logs and everything else are removed by ON DELETE CASCADE.
    await session.delete(project)
    await session.commit()
