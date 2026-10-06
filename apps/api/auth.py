"""API authentication.

Users sign in on the web app (Auth.js with Google or GitHub). The web server then calls this API
with a short-lived HS256 JWT signed with API_JWT_SECRET, carrying the user's email and name.
"""

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.db.models import User
from api.db.session import get_session

ISSUER = "rq-lens-web"
AUDIENCE = "rq-lens-api"

bearer = HTTPBearer(auto_error=False)


class TokenClaims(BaseModel):
    email: str
    name: str | None = None


def decode_token(token: str, secret: str) -> TokenClaims:
    """Raise jwt.InvalidTokenError on a bad signature, expiry, issuer, or audience."""
    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer=ISSUER,
        audience=AUDIENCE,
        options={"require": ["exp", "iat", "iss", "aud"]},
    )
    return TokenClaims.model_validate(payload)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    secret = get_settings().api_jwt_secret
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API_JWT_SECRET is not set")
    if credentials is None:
        raise _unauthorized("Missing bearer token")
    try:
        claims = decode_token(credentials.credentials, secret)
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise _unauthorized("Invalid token") from exc

    email = claims.email.strip().lower()
    stmt = (
        insert(User)
        .values(email=email, name=claims.name)
        .on_conflict_do_update(index_elements=[User.email], set_={"name": claims.name})
        .returning(User)
    )
    user = (await session.execute(stmt)).scalar_one()
    await session.commit()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
