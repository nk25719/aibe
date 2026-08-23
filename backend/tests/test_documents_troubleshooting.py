from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.config import settings
from app.db.session import SessionLocal
from app.db.models import AuditEvent
from app.services import documents as document_service


client = TestClient(app)
FIXTURES = Path(__file__).resolve().parent / "fixtures"
HEADERS = {"X-AIBE-API-Key": "test-key"}


def _ingest(path, title="TM-100 Service Manual", revision="B", document_type="service_manual", effective_at="2026-01-01", lifecycle_status="current", verification_status="verified", model="TM-100"):
    return client.post(
        "/api/documents/ingest",
        headers=HEADERS,
        json={
            "path": str(path),
            "manufacturer": "GE Healthcare",
            "equipment_model": model,
            "document_type": document_type,
            "title": title,
            "document_number": "TM100-SVC",
            "revision": revision,
            "published_at": effective_at,
            "effective_at": effective_at,
            "lifecycle_status": lifecycle_status,
            "verification_status": verification_status,
            "language": "en",
            "source": "internal fixture",
            "access_classification": "non_confidential_fixture",
        },
    )


def _enable_admin():
    settings.api_key = "test-key"


def _pdf(name="manual.pdf"):
    return {"file": (name, f"%PDF-1.4\n% fixture pdf {name}\n%%EOF\n".encode(), "application/pdf")}


def _upload_pdf(monkeypatch, title="TM-200 Service Manual", revision="A", document_type="service_manual", model="TM-200", status="current", pdf_name=None):
    monkeypatch.setattr(
        document_service,
        "_extract_text_pages",
        lambda _path: (
            [
                {"page": 1, "text": "Safety Overview\nUse lockout tagout before service.", "method": "pdf_text"},
                {"page": 2, "text": "ERR-202\nFor TM-200, ERR-202 indicates a pump calibration fault.", "method": "pdf_text"},
                {"page": 3, "text": "Parts\nPump module PM-202 is the replacement part.", "method": "pdf_text"},
            ],
            [],
        ),
    )
    return client.post(
        "/api/documents/upload",
        headers=HEADERS,
        files=_pdf(pdf_name or f"{title}-{revision}.pdf"),
        data={
            "title": title,
            "document_type": document_type,
            "manufacturer": "GE Healthcare",
            "equipment_model": model,
            "document_number": "TM200-SVC",
            "revision": revision,
            "effective_at": "2026-01-01",
            "lifecycle_status": status,
            "verification_status": "verified",
            "uploaded_by": "nk",
            "source_url": "https://example.invalid/tm200",
        },
    )


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
    assert payload["evidence"][0]["lifecycle_status"] == "current"
    assert payload["evidence"][0]["verification_status"] == "verified"
    assert payload["evidence"][0]["authoritative"] is True


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


def test_valid_pdf_upload_preserves_page_citations(monkeypatch):
    _enable_admin()
    response = _upload_pdf(monkeypatch)

    assert response.status_code == 200
    payload = response.json()
    assert payload["pages"] == 3
    assert payload["status"] == "ready"

    qa = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-200", "question": "ERR-202 pump calibration"},
    )
    evidence = qa.json()["evidence"][0]
    assert evidence["document_version_id"] == payload["document_version_id"]
    assert evidence["page_number"] == 2
    assert evidence["document_number"] == "TM200-SVC"
    assert evidence["retrieval_score"] >= 4


def test_invalid_type_and_oversized_upload_are_rejected(monkeypatch):
    _enable_admin()
    bad_type = client.post(
        "/api/documents/upload",
        headers=HEADERS,
        files={"file": ("manual.txt", b"text", "text/plain")},
        data={"title": "Bad", "document_type": "service_manual", "manufacturer": "GE Healthcare"},
    )
    assert bad_type.status_code == 415

    monkeypatch.setattr(settings, "max_upload_bytes", 5)
    too_large = client.post(
        "/api/documents/upload",
        headers=HEADERS,
        files=_pdf("large.pdf"),
        data={"title": "Large", "document_type": "service_manual", "manufacturer": "GE Healthcare"},
    )
    assert too_large.status_code == 413


def test_checksum_duplicate_detection(monkeypatch):
    _enable_admin()
    first = _upload_pdf(monkeypatch, title="TM-201 Service Manual", revision="A", model="TM-201", pdf_name="same.pdf")
    second = _upload_pdf(monkeypatch, title="TM-201 Service Manual", revision="B", model="TM-201", pdf_name="same.pdf")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(first.json()["file_sha256"]) == 64
    assert first.json()["file_sha256"] == first.json()["checksum"]
    assert second.json()["duplicate_of_version_id"] == first.json()["document_version_id"]


def test_revision_preservation_and_current_preference(monkeypatch):
    _enable_admin()
    rev_a = _upload_pdf(monkeypatch, title="TM-202 Service Manual", revision="A", model="TM-202", status="superseded")
    monkeypatch.setattr(
        document_service,
        "_extract_text_pages",
        lambda _path: ([{"page": 2, "text": "ERR-303\nFor TM-202, ERR-303 requires current revision procedure.", "method": "pdf_text"}], []),
    )
    rev_b = client.post(
        "/api/documents/upload",
        headers=HEADERS,
        files={"file": ("tm202-b.pdf", b"%PDF-1.4\nrev b\n%%EOF\n", "application/pdf")},
        data={
            "title": "TM-202 Service Manual",
            "document_type": "service_manual",
            "manufacturer": "GE Healthcare",
            "equipment_model": "TM-202",
            "document_number": "TM202-SVC",
            "revision": "B",
            "effective_at": "2026-02-01",
            "lifecycle_status": "current",
            "verification_status": "verified",
        },
    )

    assert rev_a.status_code == 200
    assert rev_b.status_code == 200
    assert rev_a.json()["document_version_id"] != rev_b.json()["document_version_id"]

    qa = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-202", "question": "ERR-303 current revision"},
    )
    assert qa.json()["evidence"][0]["revision"] == "B"
    assert qa.json()["evidence"][0]["is_current"] is True


def test_draft_is_excluded_from_normal_engineer_answers():
    _enable_admin()
    _ingest(
        FIXTURES / "ge_monitor_service_manual_rev_b.txt",
        title="TM-300 Draft Service Manual",
        revision="DRAFT",
        lifecycle_status="draft",
        verification_status="verified",
        model="TM-DRAFT",
    )

    response = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-DRAFT", "question": "ERR-101 flow sensor voltage"},
    )

    assert response.status_code == 200
    assert response.json()["evidence"] == []
    assert "will not invent" in response.json()["answer"]


def test_withdrawn_is_excluded_from_normal_and_historical_answers():
    _enable_admin()
    _ingest(
        FIXTURES / "ge_monitor_service_manual_rev_b.txt",
        title="TM-301 Withdrawn Service Manual",
        revision="W",
        lifecycle_status="withdrawn",
        verification_status="verified",
        model="TM-WITHDRAWN",
    )

    response = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-WITHDRAWN", "question": "ERR-101 flow sensor voltage", "include_historical": True},
    )

    assert response.status_code == 200
    assert response.json()["evidence"] == []


def test_failed_or_processing_documents_are_excluded():
    _enable_admin()
    ingested = _ingest(
        FIXTURES / "ge_monitor_service_manual_rev_b.txt",
        title="TM-305 Failed Ingest Manual",
        revision="A",
        lifecycle_status="current",
        verification_status="verified",
        model="TM-305",
    )
    with SessionLocal() as db:
        from app.db.models import Document

        doc = db.get(Document, ingested.json()["document_id"])
        doc.ingestion_status = "failed"
        db.commit()

    response = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-305", "question": "ERR-101 flow sensor voltage"},
    )

    assert response.status_code == 200
    assert response.json()["evidence"] == []


def test_superseded_is_excluded_when_current_evidence_exists():
    _enable_admin()
    _ingest(
        FIXTURES / "ge_monitor_service_manual_rev_a.txt",
        title="TM-302 Service Manual",
        revision="A",
        lifecycle_status="superseded",
        verification_status="verified",
        effective_at="2025-01-01",
        model="TM-302",
    )
    _ingest(
        FIXTURES / "ge_monitor_service_manual_rev_b.txt",
        title="TM-302 Service Manual",
        revision="B",
        lifecycle_status="current",
        verification_status="verified",
        effective_at="2026-01-01",
        model="TM-302",
    )

    response = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-302", "question": "ERR-101 flow sensor voltage"},
    )

    assert response.status_code == 200
    assert response.json()["evidence"][0]["revision"] == "B"
    assert all(item["lifecycle_status"] == "current" for item in response.json()["evidence"])


def test_superseded_historical_evidence_is_labeled_when_requested():
    _enable_admin()
    _ingest(
        FIXTURES / "ge_monitor_service_manual_rev_b.txt",
        title="TM-303 Service Manual",
        revision="A",
        lifecycle_status="superseded",
        verification_status="verified",
        model="TM-303",
    )

    response = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-303", "question": "ERR-101 flow sensor voltage", "include_historical": True},
    )

    evidence = response.json()["evidence"][0]
    assert evidence["lifecycle_status"] == "superseded"
    assert evidence["evidence_status"] == "historical"
    assert evidence["authoritative"] is False
    assert "Historical superseded evidence" in evidence["warning"]


def test_unverified_current_evidence_is_labeled_provisional():
    _enable_admin()
    _ingest(
        FIXTURES / "ge_monitor_service_manual_rev_b.txt",
        title="TM-304 Provisional Service Manual",
        revision="A",
        lifecycle_status="current",
        verification_status="unverified",
        model="TM-304",
    )

    response = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-304", "question": "ERR-101 flow sensor voltage"},
    )

    evidence = response.json()["evidence"][0]
    assert evidence["verification_status"] == "unverified"
    assert evidence["evidence_status"] == "provisional"
    assert evidence["authoritative"] is False
    assert "Provisional unverified evidence" in evidence["warning"]


def test_withdrawn_versions_are_excluded_and_superseded_can_fill_no_current_gap(monkeypatch):
    _enable_admin()
    uploaded = _upload_pdf(monkeypatch, title="TM-203 Service Manual", revision="A", model="TM-203", status="superseded")

    current_only = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-203", "question": "ERR-202"},
    )

    assert current_only.json()["evidence"]
    assert current_only.json()["evidence"][0]["lifecycle_status"] == "superseded"

    withdrawn = client.post(
        f"/api/documents/versions/{uploaded.json()['document_version_id']}/state",
        headers=HEADERS,
        json={"status": "withdrawn", "actor": "nk"},
    )
    assert withdrawn.status_code == 200
    after_withdrawal = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-203", "question": "ERR-202", "include_historical": True},
    )
    assert after_withdrawal.json()["evidence"] == []


def test_manufacturer_model_filtering_and_part_number_retrieval(monkeypatch):
    _enable_admin()
    _upload_pdf(monkeypatch, title="TM-204 Service Manual", revision="A", model="TM-204")

    wrong_model = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-999", "question": "PM-202 replacement part"},
    )
    right_model = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-204", "question": "PM-202 replacement part"},
    )

    assert wrong_model.json()["evidence"] == []
    assert right_model.json()["evidence"][0]["page_number"] == 3


def test_conflicting_current_revision_warning(monkeypatch):
    _enable_admin()
    _upload_pdf(monkeypatch, title="TM-205 Service Manual", revision="A", model="TM-205")
    monkeypatch.setattr(
        document_service,
        "_extract_text_pages",
        lambda _path: ([{"page": 2, "text": "ERR-202\nFor TM-205, use revised procedure.", "method": "pdf_text"}], []),
    )
    client.post(
        "/api/documents/upload",
        headers=HEADERS,
        files={"file": ("tm205-b.pdf", b"%PDF-1.4\nrev b unique\n%%EOF\n", "application/pdf")},
        data={
            "title": "TM-205 Service Manual",
            "document_type": "service_manual",
            "manufacturer": "GE Healthcare",
            "equipment_model": "TM-205",
            "document_number": "TM200-SVC",
            "revision": "B",
            "lifecycle_status": "current",
            "verification_status": "verified",
        },
    )

    response = client.post(
        "/api/documents/qa",
        json={"manufacturer": "GE Healthcare", "model": "TM-205", "question": "ERR-202"},
    )

    assert any(item["type"] == "conflicting_current_revisions" for item in response.json()["conflicts"])


def test_protected_mutation_audit_event_and_listing_filters(monkeypatch):
    _enable_admin()
    uploaded = _upload_pdf(monkeypatch, title="TM-206 Parts Catalog", revision="A", document_type="parts_catalog", model="TM-206", status="draft")
    version_id = uploaded.json()["document_version_id"]

    denied = client.post(f"/api/documents/versions/{version_id}/state", json={"status": "current", "actor": "nk"})
    allowed = client.post(
        f"/api/documents/versions/{version_id}/state",
        headers=HEADERS,
        json={"status": "current", "actor": "nk", "notes": "fixture current"},
    )
    listed = client.get("/api/documents", params={"document_type": "parts_catalog", "model": "TM-206", "limit": 1})
    status = client.get(f"/api/documents/{uploaded.json()['document_id']}/ingestion-status")

    assert denied.status_code in {403, 503}
    assert allowed.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["limit"] == 1
    assert status.json()["ingestion_status"] == "ready"
    with SessionLocal() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "document_version_current").order_by(AuditEvent.id.desc()))
        assert event is not None


def test_self_supersession_is_rejected(monkeypatch):
    _enable_admin()
    uploaded = _upload_pdf(monkeypatch, title="TM-207 Notice", revision="A", document_type="replacement_notice", model="TM-207", status="current")
    version_id = uploaded.json()["document_version_id"]

    response = client.post(
        f"/api/documents/versions/{version_id}/state",
        headers=HEADERS,
        json={"status": "superseded", "actor": "nk", "superseded_by_version_id": version_id},
    )

    assert response.status_code == 400
