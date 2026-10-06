from typing import Annotated

from arq import ArqRedis
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUser
from api.db.models import Project
from api.db.session import get_session

Session = Annotated[AsyncSession, Depends(get_session)]


async def get_owned_project(project_id: int, user: CurrentUser, session: Session) -> Project:
    project = await session.get(Project, project_id)
    # 404 rather than 403 so other users' project IDs are not revealed.
    if project is None or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


OwnedProject = Annotated[Project, Depends(get_owned_project)]


def get_queue(request: Request) -> ArqRedis:
    queue: ArqRedis = request.app.state.queue
    return queue


Queue = Annotated[ArqRedis, Depends(get_queue)]
