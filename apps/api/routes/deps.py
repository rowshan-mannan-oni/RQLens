from typing import Annotated, Any

from arq import ArqRedis
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUser
from api.db.models import Project, ProjectMember, User
from api.db.session import get_session

Session = Annotated[AsyncSession, Depends(get_session)]

# Owners can do everything; editors can change data, questions, tables and comments; viewers can
# read everything and comment. Sharing and deleting the project are for the owner only.
ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}
READ_METHODS = ("GET", "HEAD", "OPTIONS")


async def project_role(session: AsyncSession, project: Project, user: User) -> str | None:
    if project.user_id == user.id:
        return "owner"
    member = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.email == user.email
        )
    )
    if member is None:
        return None
    if member.user_id is None:
        member.user_id = user.id  # first visit after the invitation
        await session.commit()
    return member.role


async def _project(project_id: int, user: User, session: AsyncSession, need: str) -> Project:
    project = await session.get(Project, project_id)
    role = await project_role(session, project, user) if project is not None else None
    # 404 rather than 403 so other users' project IDs are not revealed.
    if project is None or role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if ROLE_RANK[role] < ROLE_RANK[need]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the project's owner can do this."
            if need == "owner"
            else "You can view and comment on this project but not change it. "
            "Ask its owner for editor access.",
        )
    return project


async def get_owned_project(
    project_id: int, user: CurrentUser, session: Session, request: Request
) -> Project:
    """The project, if the user may do this request: any member may read, editors and the
    owner may change it."""
    need = "viewer" if request.method in READ_METHODS else "editor"
    return await _project(project_id, user, session, need)


async def get_member_project(project_id: int, user: CurrentUser, session: Session) -> Project:
    """Any member, whatever the method (for comments)."""
    return await _project(project_id, user, session, "viewer")


async def get_owner_project(project_id: int, user: CurrentUser, session: Session) -> Project:
    return await _project(project_id, user, session, "owner")


OwnedProject = Annotated[Project, Depends(get_owned_project)]
MemberProject = Annotated[Project, Depends(get_member_project)]
OwnerProject = Annotated[Project, Depends(get_owner_project)]


def get_queue(request: Request) -> ArqRedis:
    queue: ArqRedis = request.app.state.queue
    return queue


Queue = Annotated[ArqRedis, Depends(get_queue)]

# A dataset in one of these states is being written by the worker.
PROCESSING = ("queued", "loading", "profiling")


def duckdb_lock(queue: ArqRedis, project_id: int, wait_s: float = 30) -> Any:
    """The per-project lock the worker holds while it writes the project's DuckDB file."""
    return queue.lock(f"rqlens:duckdb:{project_id}", timeout=300, blocking_timeout=wait_s)
