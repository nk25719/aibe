import json
import os
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config


BASE = Path(__file__).resolve().parent


def _prepare_database(tmpdir: Path) -> str:
    database_url = f"sqlite:///{tmpdir / 'aibe_document_evaluation.db'}"
    os.environ["DATABASE_URL"] = database_url
    config = Config(str(BASE / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.set_main_option("script_location", str(BASE / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return database_url


def seed(db, fixture, DocumentIngestRequest, ingest_document):
    for item in fixture["seed_documents"]:
        ingest_document(
            db,
            DocumentIngestRequest(
                path=str(BASE / item["path"]),
                manufacturer=item["manufacturer"],
                equipment_model=item.get("equipment_model"),
                equipment_family=item.get("equipment_family"),
                document_type=item["document_type"],
                title=item["title"],
                document_number=item.get("document_number"),
                revision=item["revision"],
                published_at=item.get("published_at"),
                effective_at=item.get("effective_at"),
                lifecycle_status=item.get("lifecycle_status", "draft"),
                verification_status=item.get("verification_status", "unverified"),
                language=item.get("language", "en"),
                source=item.get("source"),
                access_classification=item.get("access_classification", "non_confidential_fixture"),
            ),
        )


def run_evaluation() -> dict:
    fixture = json.loads((BASE / "eval_documents.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="aibe-doc-eval-") as tmp:
        database_url = _prepare_database(Path(tmp))

        from app.db.session import SessionLocal
        from app.schemas.api import DocumentIngestRequest, TechnicalQuestionRequest, TroubleshootingRequest
        from app.services.documents import answer_question, ingest_document
        from app.services.troubleshooting import create_troubleshooting_case

        cases = fixture["cases"] if isinstance(fixture, dict) else fixture
        retrieval_hit = citation_doc = citation_revision = citation_page = unsupported_correct = cross_model_clean = separation_ok = 0
        by_category = {}
        with SessionLocal() as db:
            seed(db, fixture, DocumentIngestRequest, ingest_document)
            results = []
            for item in cases:
                response = answer_question(
                    db,
                    TechnicalQuestionRequest(**{k: v for k, v in item.items() if k in {"question", "manufacturer", "model"}}),
                )
                first = response["evidence"][0] if response["evidence"] else None
                expected_document = item["expected_document"]
                expected_revision = item.get("expected_revision")
                expected_page = item.get("expected_page")
                doc_ok = bool(first and first["document_title"] == expected_document) if expected_document else first is None
                revision_ok = bool(first and first["revision"] == expected_revision) if expected_revision else first is None
                page_ok = bool(first and first["page"] == expected_page) if expected_page else first is None
                unsupported_ok = bool(
                    item.get("unsupported")
                    and not response["evidence"]
                    and ("not invent" in response["answer"].lower() or response["missing_information"])
                )
                retrieval_hit += int(bool(first) == bool(expected_document))
                citation_doc += int(doc_ok)
                citation_revision += int(revision_ok)
                citation_page += int(page_ok)
                unsupported_correct += int(unsupported_ok)
                if item.get("category") == "wrong_equipment_model":
                    cross_model_clean += int(not response["evidence"])
                separation_ok += int(
                    all("extracted_fact" in evidence for evidence in response["evidence"])
                    and isinstance(response["inferences"], list)
                )
                category = item["category"]
                bucket = by_category.setdefault(category, {"cases": 0, "document_hits": 0})
                bucket["cases"] += 1
                bucket["document_hits"] += int(doc_ok)
                results.append(
                    {
                        "case_id": item["case_id"],
                        "category": category,
                        "document_ok": doc_ok,
                        "revision_ok": revision_ok,
                        "page_ok": page_ok,
                        "first_evidence": first,
                    }
                )
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
        total = len(cases) or 1
        unsupported_total = max(1, sum(1 for case in cases if case.get("unsupported")))
        wrong_model_total = max(1, sum(1 for case in cases if case.get("category") == "wrong_equipment_model"))
        for bucket in by_category.values():
            bucket["citation_document_accuracy"] = bucket["document_hits"] / bucket["cases"]
        return {
            "dataset": fixture.get("dataset", {}) if isinstance(fixture, dict) else {},
            "database_url": database_url,
            "database_is_temporary": True,
            "retrieval_cases": len(cases),
            "retrieval_hit_rate": retrieval_hit / total,
            "citation_document_accuracy": citation_doc / total,
            "citation_revision_accuracy": citation_revision / total,
            "citation_page_accuracy": citation_page / total,
            "unsupported_question_refusal_accuracy": unsupported_correct / unsupported_total,
            "cross_model_contamination_rate": 1 - (cross_model_clean / wrong_model_total),
            "fact_inference_separation_rate": separation_ok / total,
            "troubleshooting_evidence_count": len(trouble["relevant_documents"]),
            "per_category": by_category,
            "note": "Small non-confidential fixtures; not production retrieval accuracy.",
            "results": results,
        }


def main():
    print(json.dumps(run_evaluation(), indent=2))


if __name__ == "__main__":
    main()
