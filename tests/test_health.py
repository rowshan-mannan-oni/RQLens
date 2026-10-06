from fastapi.testclient import TestClient

from api.main import app


def test_live() -> None:
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
