from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


client = TestClient(app)


def test_health_and_ready():
    health = client.get("/api/health")
    ready = client.get("/api/ready")

    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert ready.status_code == 200
    assert ready.json()["ok"] is True


def test_search_endpoint():
    response = client.get("/api/search", params={"q": "filter", "limit": 3})

    assert response.status_code == 200
    assert response.json()["count"] == 3


def test_image_upload_rejects_bad_mime_when_index_missing():
    response = client.post(
        "/api/match-image",
        files={"file": ("part.txt", b"not-image", "text/plain")},
    )

    assert response.status_code in {415, 503}


def test_admin_import_requires_api_key():
    response = client.post("/api/admin/import-parts")

    assert response.status_code in {403, 503}


def test_admin_review_endpoints_require_api_key():
    response = client.get("/api/admin/import-runs")

    assert response.status_code in {403, 503}


def test_admin_review_endpoints_accept_api_key(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-key")

    runs = client.get("/api/admin/import-runs", headers={"X-AIBE-API-Key": "test-key"})
    issues = client.get("/api/admin/data-quality/issues", headers={"X-AIBE-API-Key": "test-key"})

    assert runs.status_code == 200
    assert runs.json()["ok"] is True
    assert issues.status_code == 200
    assert issues.json()["ok"] is True
