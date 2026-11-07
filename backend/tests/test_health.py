from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_is_ok() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["firestore_disabled"] is True
    assert body["gemini_mode"] == "mock"
