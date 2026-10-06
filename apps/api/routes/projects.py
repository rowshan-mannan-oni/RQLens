from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from api.auth import CurrentUser
from api.db.models import Project
from api.routes.deps import OwnedProject, Session

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
    created_at: datetime


@router.get("")
async def list_projects(user: CurrentUser, session: Session) -> list[ProjectOut]:
    rows = await session.scalars(
        select(Project).where(Project.user_id == user.id).order_by(Project.created_at.desc())
    )
    return [ProjectOut.model_validate(p) for p in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, user: CurrentUser, session: Session) -> ProjectOut:
    project = Project(user_id=user.id, title=body.title.strip(), topic=body.topic)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("/{project_id}")
async def get_project(project: OwnedProject) -> ProjectOut:
    return ProjectOut.model_validate(project)
