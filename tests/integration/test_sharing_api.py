"""Sharing and comments against a running API (Postgres, Redis).

Skipped unless RQLENS_API_URL is set, for example:

    RQLENS_API_URL=http://localhost:8000 API_JWT_SECRET=... pytest tests/integration

The owner account (owner@example.org) gets a fresh project; three other accounts play a
viewer, an editor and a stranger.
"""

import os
import time

import httpx
import jwt
import pytest

URL = os.environ.get("RQLENS_API_URL")
pytestmark = pytest.mark.skipif(not URL, reason="needs a running API (RQLENS_API_URL)")


def client(email: str, name: str) -> httpx.Client:
    now = int(time.time())
    claims = {"email": email, "name": name, "iss": "rq-lens-web", "aud": "rq-lens-api",
              "iat": now, "exp": now + 600}  # fmt: skip
    tok = jwt.encode(claims, os.environ.get("API_JWT_SECRET", ""), algorithm="HS256")
    return httpx.Client(base_url=URL or "", headers={"Authorization": "Bearer " + tok}, timeout=30)


def test_roles_and_comments() -> None:
    owner = client("owner@example.org", "Owner")
    viewer = client("supervisor@uni.edu", "Dr Supervisor")
    editor = client("coauthor@uni.edu", "Co Author")
    stranger = client("other@x.com", "Other")
    P = owner.post("/projects", json={"title": "Sharing test"}).json()["id"]
    rq0 = owner.post(f"/projects/{P}/rqs", json={"text": "Does sleep affect grades?"})
    assert rq0.status_code == 201
    checks = []

    def check(label, got, want):
        checks.append((label, got == want, got))

    check("viewer cannot see before invite", viewer.get(f"/projects/{P}").status_code, 404)
    check(
        "owner adds viewer",
        owner.post(
            f"/projects/{P}/members", json={"email": "Supervisor@Uni.edu", "role": "viewer"}
        ).status_code,
        201,
    )
    check(
        "owner adds editor",
        owner.post(
            f"/projects/{P}/members", json={"email": "coauthor@uni.edu", "role": "editor"}
        ).status_code,
        201,
    )
    check(
        "bad email", owner.post(f"/projects/{P}/members", json={"email": "nope"}).status_code, 400
    )
    check(
        "viewer lists shared project",
        [(p["id"], p["role"], p["owner"]) for p in viewer.get("/projects").json() if p["id"] == P],
        [(P, "viewer", "Owner")],
    )
    check("viewer reads project role", viewer.get(f"/projects/{P}").json()["role"], "viewer")
    check("viewer reads RQs", viewer.get(f"/projects/{P}/rqs").status_code, 200)
    r = viewer.post(f"/projects/{P}/rqs", json={"text": "Does the viewer get to add this?"})
    check(
        "viewer cannot add RQ",
        (r.status_code, "view and comment" in r.json()["detail"]),
        (403, True),
    )
    check(
        "viewer cannot share",
        viewer.post(f"/projects/{P}/members", json={"email": "x@y.com"}).status_code,
        403,
    )
    check(
        "editor adds RQ",
        editor.post(
            f"/projects/{P}/rqs", json={"text": "Do editors get to add research questions?"}
        ).status_code,
        201,
    )
    check("editor cannot delete project", editor.delete(f"/projects/{P}").status_code, 403)
    check("stranger 404", stranger.get(f"/projects/{P}/rqs").status_code, 404)
    rq = owner.get(f"/projects/{P}/rqs").json()["questions"][0]["id"]
    c1 = viewer.post(
        f"/projects/{P}/comments",
        json={"target_type": "rq", "target_id": rq, "body": "Is the sample large enough?"},
    )
    check("viewer comments on RQ", c1.status_code, 201)
    check(
        "comment on other project's item refused",
        viewer.post(
            f"/projects/{P}/comments", json={"target_type": "rq", "target_id": 999999, "body": "x"}
        ).status_code,
        404,
    )
    c2 = owner.post(f"/projects/{P}/comments", json={"body": "Welcome to the project"}).json()
    check(
        "viewer cannot resolve owner's comment",
        viewer.patch(f"/projects/{P}/comments/{c2['id']}", json={"resolved": True}).status_code,
        403,
    )
    check(
        "editor resolves it",
        editor.patch(f"/projects/{P}/comments/{c2['id']}", json={"resolved": True}).json()[
            "resolved"
        ],
        True,
    )
    check(
        "viewer edits own comment",
        viewer.patch(
            f"/projects/{P}/comments/{c1.json()['id']}", json={"body": "Is n large enough?"}
        ).json()["body"],
        "Is n large enough?",
    )
    check(
        "owner cannot edit viewer's text",
        owner.patch(f"/projects/{P}/comments/{c1.json()['id']}", json={"body": "x"}).status_code,
        403,
    )
    thread = owner.get(
        f"/projects/{P}/comments", params={"target_type": "rq", "target_id": rq}
    ).json()
    check(
        "thread",
        [(c["author"], c["body"], c["mine"]) for c in thread],
        [("Dr Supervisor", "Is n large enough?", False)],
    )
    members = owner.get(f"/projects/{P}/members").json()
    check(
        "members",
        [(m["email"], m["role"], m["joined"]) for m in members],
        [
            ("owner@example.org", "owner", True),
            ("supervisor@uni.edu", "viewer", True),
            ("coauthor@uni.edu", "editor", True),
        ],
    )
    mid = next(m["id"] for m in members if m["role"] == "editor")
    check(
        "owner makes editor a viewer",
        owner.patch(f"/projects/{P}/members/{mid}", json={"role": "viewer"}).json()["role"],
        "viewer",
    )
    check(
        "demoted editor can no longer add",
        editor.post(
            f"/projects/{P}/rqs", json={"text": "Another question from the demoted?"}
        ).status_code,
        403,
    )
    vid = next(m["id"] for m in members if m["email"] == "supervisor@uni.edu")
    check("viewer leaves", viewer.delete(f"/projects/{P}/members/{vid}").status_code, 204)
    check("left viewer loses access", viewer.get(f"/projects/{P}").status_code, 404)
    check(
        "viewer's comment kept",
        any(c["body"] == "Is n large enough?" for c in owner.get(f"/projects/{P}/comments").json()),
        True,
    )
    owner.delete(f"/projects/{P}/members/{mid}")
    owner.delete(f"/projects/{P}")
    assert not [c[0] for c in checks if not c[1]], [c for c in checks if not c[1]]
