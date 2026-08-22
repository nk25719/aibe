import json
from pathlib import Path

from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.schemas.api import DocumentIngestRequest, TechnicalQuestionRequest, TroubleshootingRequest
from app.services.documents import answer_question, ingest_document
from app.services.troubleshooting import create_troubleshooting_case


BASE = Path(__file__).resolve().parent


def seed(db):
    for path, title, revision, doc_type in [
        ("tests/fixtures/ge_monitor_service_manual_rev_b.txt", "TM-100 Service Manual", "B", "service_manual"),
        ("tests/fixtures/ge_monitor_bulletin.txt", "TB-77", "1", "technical_bulletin"),
    ]:
        ingest_document(
            db,
            DocumentIngestRequest(
                path=str(BASE / path),
                manufacturer="GE Healthcare",
                equipment_model="TM-100",
                document_type=doc_type,
                title=title,
                document_number=title,
                revision=revision,
                published_at="2026-01-01",
                effective_at="2026-01-01",
                language="en",
                source="internal fixture",
                access_classification="non_confidential_fixture",
            ),
        )


def main():
    Base.metadata.create_all(bind=engine)
    fixture = json.loads((BASE / "eval_documents.json").read_text(encoding="utf-8"))
    correct = 0
    unsupported_correct = 0
    with SessionLocal() as db:
        seed(db)
        results = []
        for item in fixture:
            response = answer_question(db, TechnicalQuestionRequest(**{k: v for k, v in item.items() if k in {"question", "manufacturer", "model"}}))
            first = response["evidence"][0] if response["evidence"] else None
            ok = (
                (first is None and item["expected_document"] is None)
                or (first and first["document_title"] == item["expected_document"] and first["page"] == item["expected_page"])
            )
            correct += int(ok)
            unsupported_correct += int(first is None and item["expected_document"] is None)
            results.append({"question": item["question"], "ok": ok, "first_evidence": first})
        trouble = create_troubleshooting_case(
            db,
            TroubleshootingRequest(
                manufacturer="GE Healthcare",
                model="TM-100",
                error_code="ERR-101",
                symptom_description="flow sensor fault after transport",
                software_version="2.1",
            ),
        )
    print(
        json.dumps(
            {
                "retrieval_cases": len(fixture),
                "citation_accuracy": correct / len(fixture),
                "unsupported_refusal_cases_correct": unsupported_correct,
                "troubleshooting_evidence_count": len(trouble["relevant_documents"]),
                "note": "Tiny non-confidential fixtures; not production retrieval accuracy.",
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
