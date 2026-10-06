"""Sharing a project with co-authors or a supervisor, and comments on its items.

The owner adds people by email as viewers (read and comment) or editors (also change data,
questions and tables). There is no email service: the owner sends the project link, and the
person signs in with the invited address. AI used by editors counts against the owner's
monthly budget, because it is the owner's project.
"""

import datetime as dt
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.auth import CurrentUser
from api.db.models import (
    Comment,
    Insight,
    Paper,
    ProjectMember,
    ResearchQuestion,
    ReviewCell,
    ReviewTable,
    User,
)
from api.routes.deps import MemberProject, OwnerProject, Session, project_role

router = APIRouter(prefix="/projects/{project_id}", tags=["sharing"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TargetType = Literal["project", "rq", "cell", "insight", "paper"]
MAX_MEMBERS = 50


class MemberIn(BaseModel):
    email: str = Field(max_length=320)
    role: Literal["viewer", "editor"] = "viewer"


class MemberRole(BaseModel):
    role: Literal["viewer", "editor"]


class MemberOut(BaseModel):
    id: int | None  # None for the owner
    email: str
    name: str | None
    role: str
    joined: bool  # has signed in since being added


class CommentIn(BaseModel):
    target_type: TargetType = "project"
    target_id: int | None = None
    body: str = Field(min_length=1, max_length=5000)


class CommentPatch(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    resolved: bool | None = None


class CommentOut(BaseModel):
    id: int
    target_type: str
    target_id: int | None
    body: str
    resolved: bool
    author: str
    mine: bool
    created_at: dt.datetime
    edited_at: dt.datetime | None


def _member_out(m: ProjectMember, u: User | None) -> MemberOut:
    return MemberOut(
        id=m.id, email=m.email, name=u.name if u else None, role=m.role, joined=u is not None
    )


# --- members ---------------------------------------------------------------------------------


@router.get("/members")
async def list_members(project: MemberProject, session: Session) -> list[MemberOut]:
    owner = await session.get(User, project.user_id)
    out = [
        MemberOut(
            id=None,
            email=owner.email if owner else "",
            name=owner.name if owner else None,
            role="owner",
            joined=True,
        )
    ]
    rows = await session.execute(
        select(ProjectMember, User)
        .outerjoin(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project.id)
        .order_by(ProjectMember.created_at)
    )
    for m, u in rows:
        out.append(
            MemberOut(
                id=m.id,
                email=m.email,
                name=u.name if u else None,
                role=m.role,
                joined=u is not None,
            )
        )
    return out


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    body: MemberIn, project: OwnerProject, user: CurrentUser, session: Session
) -> MemberOut:
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a valid email address")
    if email == user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You already own this project")
    existing = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.email == email
        )
    )
    if existing is not None:
        existing.role = body.role
        member = existing
    else:
        n = await session.scalar(
            select(func.count(ProjectMember.id)).where(ProjectMember.project_id == project.id)
        )
        if (n or 0) >= MAX_MEMBERS:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"A project can be shared with {MAX_MEMBERS} people"
            )
        known = await session.scalar(select(User).where(User.email == email))
        member = ProjectMember(
            project_id=project.id,
            email=email,
            role=body.role,
            user_id=known.id if known else None,
            invited_by=user.id,
        )
        session.add(member)
    await session.commit()
    await session.refresh(member)
    return _member_out(member, await session.get(User, member.user_id) if member.user_id else None)


@router.patch("/members/{member_id}")
async def change_role(
    member_id: int, body: MemberRole, project: OwnerProject, session: Session
) -> MemberOut:
    m = await session.get(ProjectMember, member_id)
    if m is None or m.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    m.role = body.role
    await session.commit()
    return _member_out(m, await session.get(User, m.user_id) if m.user_id else None)


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    member_id: int, project: MemberProject, user: CurrentUser, session: Session
) -> None:
    """The owner removes anyone; a member can remove themselves (leave the project)."""
    m = await session.get(ProjectMember, member_id)
    if m is None or m.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if project.user_id != user.id and m.email != user.email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project's owner can do this.")
    await session.delete(m)
    await session.commit()


# --- comments --------------------------------------------------------------------------------


async def _check_target(
    session: Session, project_id: int, target_type: str, target_id: int | None
) -> None:
    if target_type == "project":
        if target_id is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project comment has no target")
        return
    if target_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Say what the comment is about")
    if target_type == "rq":
        row = await session.get(ResearchQuestion, target_id)
        ok = row is not None and row.project_id == project_id
    elif target_type == "insight":
        ins = await session.get(Insight, target_id)
        ok = ins is not None and ins.project_id == project_id
    elif target_type == "paper":
        p = await session.get(Paper, target_id)
        ok = p is not None and p.project_id == project_id
    else:  # cell
        cell = await session.get(ReviewCell, target_id)
        table = await session.get(ReviewTable, cell.table_id) if cell is not None else None
        ok = table is not None and table.project_id == project_id
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found in this project")


def _out(c: Comment, author: User | None, user: User) -> CommentOut:
    return CommentOut(
        id=c.id,
        target_type=c.target_type,
        target_id=c.target_id,
        body=c.body,
        resolved=c.resolved,
        author=(author.name or author.email) if author else "Former member",
        mine=c.user_id == user.id,
        created_at=c.created_at,
        edited_at=c.edited_at,
    )


@router.get("/comments")
async def list_comments(
    project: MemberProject,
    user: CurrentUser,
    session: Session,
    target_type: TargetType | None = None,
    target_id: int | None = None,
) -> list[CommentOut]:
    """Comments on the project, oldest first; filter by target to get one thread."""
    q = (
        select(Comment, User)
        .outerjoin(User, User.id == Comment.user_id)
        .where(Comment.project_id == project.id)
    )
    if target_type is not None:
        q = q.where(Comment.target_type == target_type)
    if target_id is not None:
        q = q.where(Comment.target_id == target_id)
    rows = await session.execute(q.order_by(Comment.created_at, Comment.id))
    return [_out(c, a, user) for c, a in rows]


@router.post("/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    body: CommentIn, project: MemberProject, user: CurrentUser, session: Session
) -> CommentOut:
    await _check_target(session, project.id, body.target_type, body.target_id)
    c = Comment(
        project_id=project.id,
        user_id=user.id,
        target_type=body.target_type,
        target_id=body.target_id,
        body=body.body.strip(),
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return _out(c, user, user)


@router.patch("/comments/{comment_id}")
async def update_comment(
    comment_id: int, body: CommentPatch, project: MemberProject, user: CurrentUser,
    session: Session,
) -> CommentOut:  # fmt: skip
    """Authors edit their own text; the author, editors and the owner resolve threads."""
    c = await session.get(Comment, comment_id)
    if c is None or c.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    role = await project_role(session, project, user)
    if body.body is not None:
        if c.user_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only edit your own comments")
        c.body, c.edited_at = body.body.strip(), dt.datetime.now(dt.UTC)
    if body.resolved is not None:
        if c.user_id != user.id and role == "viewer":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only editors and the owner can resolve others' comments"
            )
        c.resolved = body.resolved
    await session.commit()
    await session.refresh(c)
    return _out(c, await session.get(User, c.user_id) if c.user_id else None, user)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: int, project: MemberProject, user: CurrentUser, session: Session
) -> None:
    c = await session.get(Comment, comment_id)
    if c is None or c.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    if c.user_id != user.id and project.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete your own comments")
    await session.delete(c)
    await session.commit()
