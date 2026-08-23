from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings


client = TestClient(app)
FIXTURES = Path(__file__).resolve().parent / "fixtures"
HEADERS = {"X-AIBE-API-Key": "test-key"}


def _ingest(path, title="TM-100 Service Manual", revision="B", document_type="service_manual", effective_at="2026-01-01"):
    return client.post(
        "/api/documents/ingest",
        headers=HEADERS,
        json={
            "path": str(path),
            "manufacturer": "GE Healthcare",
            "equipment_model": "TM-100",
            "document_type": document_type,
            "title": title,
            "document_number": "TM100-SVC",
            "revision": revision,
            "published_at": effective_at,
            "effective_at": effective_at,
            "language": "en",
            "source": "internal fixture",
            "access_classification": "non_confidential_fixture",
        },
    )


def _enable_admin():
    settings.api_key = "test-key"


def test_document_ingestion_duplicate_detection():
    _enable_admin()
    first = _ingest(FIXTURES / "ge_monitor_service_manual_rev_b.txt")
    second = _ingest(FIXTURES / "ge_monitor_service_manual_rev_b.txt")

    assert first.status_code == 200
    assert first.json()["pages"] == 3
    assert second.status_code == 200
    assert second.json()["checksum"] == first.json()["checksum"]


def test_qa_requires_context():
    response = client.post("/api/documents/qa", json={"question": "What is ERR-101?"})

    assert response.status_code == 200
    assert "manufacturer" in response.json()["missing_information"]


def test_qa_cites_document_revision_page_and_section():
    _enable_admin()
    _ingest(FIXTURES / "ge_monitor_service_manual_rev_b.txt")
    response = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-100", "question": "ERR-101 flow sensor voltage"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["evidence"]
    assert payload["evidence"][0]["document_title"] == "TM-100 Service Manual"
    assert payload["evidence"][0]["revision"] == "B"
    assert payload["evidence"][0]["page"] == 2


def test_qa_refuses_to_invent_unsupported_evidence():
    response = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-100", "question": "What is ZX-999?"},
    )

    assert response.status_code == 200
    assert "will not invent" in response.json()["answer"]


def test_conflicting_documents_are_reported():
    _enable_admin()
    _ingest(FIXTURES / "ge_monitor_service_manual_rev_b.txt")
    _ingest(FIXTURES / "ge_monitor_bulletin.txt", title="TB-77", revision="1", document_type="technical_bulletin")
    response = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-100", "question": "ERR-101 replace sensor"},
    )

    assert response.status_code == 200
    assert response.json()["conflicts"]


def test_troubleshooting_case_logs_safe_response():
    _enable_admin()
    _ingest(FIXTURES / "ge_monitor_service_manual_rev_b.txt")
    response = client.post(
        "/api/troubleshooting/cases",
        json={
            "manufacturer": "GE Healthcare",
            "model": "TM-100",
            "error_code": "ERR-101",
            "symptom_description": "flow sensor fault after transport",
            "software_version": "2.1",
            "reviewed_by": "nk",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["possible_causes"]
    assert payload["relevant_documents"]
    assert "decision support" in payload["safety_notice"]
    assert any("patient-safe" in item for item in payload["stop_escalation_conditions"])
