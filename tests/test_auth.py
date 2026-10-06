import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from api.auth import AUDIENCE, ISSUER, decode_token
from api.config import get_settings
from api.main import app

SECRET = "test-secret-at-least-32-bytes-long!!"


def make_token(secret: str = SECRET, **overrides: Any) -> str:
    now = int(time.time())
    claims = {"email": "a@example.com", "name": "A", "iat": now, "exp": now + 300}
    claims |= {"iss": ISSUER, "aud": AUDIENCE} | overrides
    return jwt.encode(claims, secret, algorithm="HS256")


def test_valid_token() -> None:
    assert decode_token(make_token(), SECRET).email == "a@example.com"


@pytest.mark.parametrize(
    ("secret", "overrides"),
    [
        ("wrong-secret-at-least-32-bytes-long!", {}),
        (SECRET, {"exp": int(time.time()) - 10}),
        (SECRET, {"aud": "someone-else"}),
        (SECRET, {"iss": "someone-else"}),
    ],
)
def test_rejected_tokens(secret: str, overrides: dict[str, Any]) -> None:
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(make_token(secret, **overrides), SECRET)


@pytest.fixture
def configured_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "api_jwt_secret", SECRET)
    yield


@pytest.mark.usefixtures("configured_secret")
def test_projects_require_token() -> None:
    client = TestClient(app)
    assert client.get("/projects").status_code == 401
    bad = {"Authorization": f"Bearer {make_token('wrong-secret-at-least-32-bytes-long!')}"}
    assert client.get("/projects", headers=bad).status_code == 401
