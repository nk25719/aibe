from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import catalog_query


client = TestClient(app)


def test_health_and_ready():
    health = client.get("/api/health")
    ready = client.get("/api/ready")

    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert ready.status_code == 200
    assert ready.json()["ok"] is True


def test_search_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "enable_legacy_search_fallback", False)

    response = client.get("/api/search", params={"q": "filter", "limit": 3})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 3
    assert payload["source"] == "normalized_catalog"
    assert payload["legacy_fallback_used"] is False


def test_clients_cannot_enable_legacy_fallback_with_query_param(monkeypatch):
    monkeypatch.setattr(settings, "enable_legacy_search_fallback", False)
    legacy_called = False

    def fake_legacy_search(query, limit=20, offset=0):
        nonlocal legacy_called
        legacy_called = True
        return [{"id": 9999, "part_number": "LEGACY-ONLY", "description": "Legacy-only test part"}]

    monkeypatch.setattr(catalog_query.legacy_search, "search_parts", fake_legacy_search)

    response = client.get(
        "/api/search",
        params={"q": "legacy-only-no-hit", "enable_legacy_fallback": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "normalized_catalog"
    assert payload["legacy_fallback_used"] is False
    assert payload["results"] == []
    assert legacy_called is False


def test_server_config_enables_labeled_legacy_fallback(monkeypatch):
    monkeypatch.setattr(settings, "enable_legacy_search_fallback", True)

    def fake_legacy_search(query, limit=20, offset=0):
        return [{"id": 9999, "part_number": "LEGACY-ONLY", "description": "Legacy-only test part"}]

    monkeypatch.setattr(catalog_query.legacy_search, "search_parts", fake_legacy_search)

    response = client.get("/api/search", params={"q": "legacy-only-no-hit"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["source"] == "legacy_fallback"
    assert payload["legacy_fallback_used"] is True
    assert payload["results"][0]["data_origin"] == "legacy_parts_db_fallback"
    assert payload["results"][0]["legacy_fallback_used"] is True


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
