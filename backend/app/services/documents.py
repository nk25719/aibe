import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.db.models import AuditEvent, Document, DocumentChunk, DocumentVersion
from app.services.normalization import clean_text, normalize_label

STOPWORDS = {"what", "where", "when", "which", "with", "from", "this", "that", "does", "about", "error", "code", "the", "and"}

def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_text_pages(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception as exc:
            raise HTTPException(503, f"PDF extraction unavailable: {exc}")
        reader = PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            method = "pdf_text"
            if not text.strip():
                method = "ocr_unavailable"
                errors.append(f"page {i}: no embedded text; OCR fallback unavailable in this environment")
            pages.append({"page": i, "text": text, "method": method})
        return pages, errors
    text = path.read_text(encoding="utf-8")
    raw_pages = re.split(r"\n-{3,}\s*PAGE\s+\d+\s*-{3,}\n", text, flags=re.I)
    return [{"page": i, "text": page.strip(), "method": "text"} for i, page in enumerate(raw_pages, start=1) if page.strip()], errors


def _section_for(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and len(stripped) < 120:
            return stripped
    return None


def ingest_document(db: Session, payload) -> dict[str, Any]:
    path = Path(payload.path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists() or not path.is_file():
        raise HTTPException(404, f"Document not found: {path}")
    checksum = _checksum(path)
    duplicate = db.scalar(select(DocumentVersion).where(DocumentVersion.file_sha1 == checksum))
    document = db.scalar(
        select(Document).where(
            Document.title == payload.title,
            Document.document_number == payload.document_number,
            Document.manufacturer_text == payload.manufacturer,
        )
    )
    if not document:
        document = Document(
            title=payload.title,
            document_type=payload.document_type,
            document_number=payload.document_number,
            manufacturer_text=payload.manufacturer,
            equipment_family_text=payload.equipment_family,
            equipment_model_text=payload.equipment_model,
            language=payload.language,
            access_classification=payload.access_classification,
            source_url=payload.source,
            internal_reference=str(path),
            ingestion_status="pending",
        )
        db.add(document)
        db.flush()
    version = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id, DocumentVersion.revision == payload.revision))
    if not version:
        version = DocumentVersion(
            document_id=document.id,
            revision=payload.revision,
            published_at=_parse_date(payload.published_at),
            effective_at=_parse_date(payload.effective_at),
            file_sha1=checksum,
            source_path=str(path),
            duplicate_of_version_id=duplicate.id if duplicate else None,
        )
        db.add(version)
        db.flush()
    pages, errors = _extract_text_pages(path)
    if not db.scalar(select(DocumentChunk).where(DocumentChunk.document_version_id == version.id)):
        for index, page in enumerate(pages):
            figures = re.findall(r"(?:figure|fig\.)\s*([A-Za-z0-9.-]+)", page["text"], flags=re.I)
            tables = re.findall(r"(?:table)\s*([A-Za-z0-9.-]+)", page["text"], flags=re.I)
            db.add(
                DocumentChunk(
                    document_version_id=version.id,
                    page_number=page["page"],
                    chunk_index=index,
                    section=_section_for(page["text"]),
                    text=page["text"],
                    search_text=page["text"].lower(),
                    extraction_method=page["method"],
                    figure_refs={"items": figures},
                    tables={"items": tables},
                )
            )
    document.ingestion_status = "completed_with_errors" if errors else "completed"
    document.ingestion_errors = {"items": errors}
    db.add(AuditEvent(action="document_ingested", entity_type="document_version", entity_id=str(version.id), details={"checksum": checksum, "errors": errors}))
    db.commit()
    return {
        "ok": True,
        "document_id": document.id,
        "document_version_id": version.id,
        "status": document.ingestion_status,
        "checksum": checksum,
        "pages": len(pages),
        "duplicate_of_version_id": version.duplicate_of_version_id,
        "errors": errors,
    }


def retrieve_chunks(db: Session, question: str, manufacturer: str | None, model: str | None, include_historical: bool = False, limit: int = 5):
    terms = {t.lower() for t in re.findall(r"[a-zA-Z0-9-]{3,}", question)}
    terms = {term for term in terms if term not in STOPWORDS}
    docs = db.execute(
        select(DocumentChunk, DocumentVersion, Document)
        .select_from(DocumentChunk)
        .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
    ).all()
    scored = []
    for chunk, version, doc in docs:
        if manufacturer and not normalize_label(doc.manufacturer_text) == normalize_label(manufacturer):
            continue
        if model and doc.equipment_model_text and normalize_label(doc.equipment_model_text) != normalize_label(model):
            continue
        text = chunk.search_text or (chunk.text or "").lower()
        score = sum(1 for term in terms if term in text)
        if not include_historical and doc.ingestion_status != "completed":
            score -= 1
        if score > 0:
            scored.append((score, chunk, version, doc))
    scored.sort(key=lambda item: (item[0], item[2].effective_at or item[2].published_at or date.min), reverse=True)
    return scored[:limit]


def answer_question(db: Session, payload) -> dict[str, Any]:
    missing = []
    if not clean_text(payload.manufacturer):
        missing.append("manufacturer")
    if not clean_text(payload.model):
        missing.append("equipment model")
    warnings = []
    if not payload.model:
        warnings.append("Model/configuration/serial range/hardware/software applicability is unresolved.")
    if missing:
        return {"ok": True, "answer": "More context is required before retrieving applicable technical evidence.", "missing_information": missing, "evidence": [], "inferences": [], "warnings": warnings, "conflicts": []}
    hits = retrieve_chunks(db, payload.question, payload.manufacturer, payload.model, payload.include_historical)
    evidence = [
        {
            "document_title": doc.title,
            "revision": version.revision,
            "page": chunk.page_number,
            "section": chunk.section,
            "extracted_fact": (chunk.text or "")[:500],
            "document_type": doc.document_type,
        }
        for _score, chunk, version, doc in hits
    ]
    if not evidence:
        return {"ok": True, "answer": "No source evidence was found. AIBE will not invent a procedure, part number, error code, or citation.", "missing_information": [], "evidence": [], "inferences": [], "warnings": warnings, "conflicts": []}
    return {
        "ok": True,
        "answer": "Relevant source excerpts were found. Review the cited pages before applying any service action.",
        "missing_information": [],
        "evidence": evidence,
        "inferences": ["Applicability depends on the exact model, configuration, serial range, hardware, and software version."],
        "warnings": warnings,
        "conflicts": _detect_conflicts(evidence),
    }


def _detect_conflicts(evidence):
    joined = "\n".join(item["extracted_fact"].lower() for item in evidence)
    if "do not replace" in joined and "replace" in joined:
        return [{"type": "procedure_conflict", "detail": "Retrieved evidence contains both replacement and non-replacement language."}]
    return []
