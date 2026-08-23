import hashlib
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.db.models import AuditEvent, Document, DocumentChunk, DocumentLink, DocumentVersion, EquipmentFamily, EquipmentModel, Manufacturer
from app.schemas.api import DocumentUploadMetadata
from app.services.normalization import clean_text, normalize_label

STOPWORDS = {"what", "where", "when", "which", "with", "from", "this", "that", "does", "about", "error", "code", "the", "and"}
DOCUMENT_TYPES = {
    "service_manual",
    "user_manual",
    "parts_catalog",
    "technical_bulletin",
    "field_modification",
    "safety_notice",
    "eol_notice",
    "eosl_notice",
    "replacement_notice",
    "installation_manual",
    "maintenance_procedure",
    "training_material",
    "other",
}
LIFECYCLE_STATUSES = {"draft", "current", "superseded", "withdrawn"}
READY_STATUSES = {"ready", "completed", "completed_with_errors"}

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


def _checksum_fileobj(fileobj) -> str:
    h = hashlib.sha256()
    while chunk := fileobj.read(1024 * 1024):
        h.update(chunk)
    fileobj.seek(0)
    return h.hexdigest()


def _checksum_filter(checksum: str):
    return or_(DocumentVersion.file_sha256 == checksum, DocumentVersion.file_sha1 == checksum)


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename or "document.pdf").name).strip("._")
    return cleaned or "document.pdf"


def _validate_document_type(document_type: str) -> None:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(422, f"Unsupported document_type: {document_type}")


def _validate_lifecycle_status(status: str) -> None:
    if status not in LIFECYCLE_STATUSES:
        raise HTTPException(422, f"Unsupported lifecycle_status: {status}")


def _resolve_links(db: Session, metadata: DocumentUploadMetadata | Any) -> tuple[int | None, int | None, int | None]:
    manufacturer = None
    if clean_text(metadata.manufacturer):
        manufacturer = db.scalar(select(Manufacturer).where(Manufacturer.normalized_name == normalize_label(metadata.manufacturer)))
    family = None
    if manufacturer and clean_text(metadata.equipment_family):
        family = db.scalar(
            select(EquipmentFamily).where(
                EquipmentFamily.manufacturer_id == manufacturer.id,
                EquipmentFamily.normalized_name == normalize_label(metadata.equipment_family),
            )
        )
    model = None
    if manufacturer and clean_text(metadata.equipment_model):
        model = db.scalar(
            select(EquipmentModel).where(
                EquipmentModel.manufacturer_id == manufacturer.id,
                EquipmentModel.normalized_model_name == normalize_label(metadata.equipment_model),
            )
        )
    return manufacturer.id if manufacturer else None, family.id if family else None, model.id if model else None


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
    _validate_document_type(payload.document_type)
    _validate_lifecycle_status(payload.lifecycle_status)
    checksum = _checksum(path)
    duplicate = db.scalar(select(DocumentVersion).where(_checksum_filter(checksum)))
    manufacturer_id, family_id, model_id = _resolve_links(db, payload)
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
            manufacturer_id=manufacturer_id,
            equipment_family_id=family_id,
            equipment_model_id=model_id,
            manufacturer_text=payload.manufacturer,
            equipment_family_text=payload.equipment_family,
            equipment_model_text=payload.equipment_model,
            language=payload.language,
            access_classification=payload.access_classification,
            source_url=payload.source,
            internal_reference=str(path),
            ingestion_status="pending",
            verification_status=payload.verification_status,
            notes=payload.notes,
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
            expires_at=_parse_date(payload.expiration_or_superseded_at),
            lifecycle_status=payload.lifecycle_status,
            file_sha1=checksum,
            file_sha256=checksum,
            original_filename=path.name,
            mime_type="application/pdf" if path.suffix.lower() == ".pdf" else "text/plain",
            file_size=path.stat().st_size,
            uploaded_at=datetime.utcnow(),
            source_path=str(path),
            duplicate_of_version_id=duplicate.id if duplicate else None,
        )
        db.add(version)
        db.flush()
        _sync_links(db, version.id, manufacturer_id, family_id, model_id)
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
    document.ingestion_status = "completed_with_errors" if errors else "ready"
    document.ingestion_errors = {"items": errors}
    db.add(AuditEvent(action="document_ingested", entity_type="document_version", entity_id=str(version.id), details={"file_sha256": checksum, "errors": errors}))
    db.commit()
    return {
        "ok": True,
        "document_id": document.id,
        "document_version_id": version.id,
        "status": document.ingestion_status,
        "checksum": checksum,
        "file_sha256": checksum,
        "pages": len(pages),
        "duplicate_of_version_id": version.duplicate_of_version_id,
        "errors": errors,
    }


def _sync_links(db: Session, version_id: int, manufacturer_id: int | None, family_id: int | None, model_id: int | None, part_ids: list[int] | None = None) -> None:
    if manufacturer_id:
        db.add(DocumentLink(document_version_id=version_id, manufacturer_id=manufacturer_id, link_type="manufacturer"))
    if family_id:
        db.add(DocumentLink(document_version_id=version_id, manufacturer_id=manufacturer_id, link_type="equipment_family"))
    if model_id:
        db.add(DocumentLink(document_version_id=version_id, manufacturer_id=manufacturer_id, model_id=model_id, link_type="equipment_model"))
    for part_id in part_ids or []:
        db.add(DocumentLink(document_version_id=version_id, manufacturer_id=manufacturer_id, model_id=model_id, part_id=part_id, link_type="part"))


def upload_document(db: Session, upload: UploadFile, metadata: DocumentUploadMetadata) -> dict[str, Any]:
    _validate_document_type(metadata.document_type)
    _validate_lifecycle_status(metadata.lifecycle_status)
    filename = _safe_filename(upload.filename or "document.pdf")
    if not filename.lower().endswith(".pdf") or upload.content_type not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(415, "Only PDF uploads are supported in this milestone.")
    checksum = _checksum_fileobj(upload.file)
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    if size > settings.max_upload_bytes:
        raise HTTPException(413, f"Upload exceeds configured MAX_UPLOAD_BYTES limit of {settings.max_upload_bytes}.")
    duplicate = db.scalar(select(DocumentVersion).where(_checksum_filter(checksum)))
    if duplicate:
        doc = db.get(Document, duplicate.document_id)
        return _ingest_response(doc, duplicate, checksum, duplicate.duplicate_of_version_id or duplicate.id, [])
    settings.document_upload_dir.mkdir(parents=True, exist_ok=True)
    stored = settings.document_upload_dir / f"{checksum[:16]}-{filename}"
    with stored.open("wb") as fh:
        shutil.copyfileobj(upload.file, fh)
    response = ingest_document(
        db,
        SimpleNamespace(
            **metadata.model_dump(),
            path=str(stored),
            source=metadata.source_url,
            access_classification="internal",
        ),
    )
    version = db.get(DocumentVersion, response["document_version_id"])
    version.original_filename = filename
    version.mime_type = upload.content_type
    version.file_size = size
    version.uploaded_by = metadata.uploaded_by
    version.uploaded_at = datetime.utcnow()
    db.add(AuditEvent(actor=metadata.uploaded_by, action="document_uploaded", entity_type="document_version", entity_id=str(version.id), details={"filename": filename, "file_sha256": checksum}))
    db.commit()
    return response


def _version_payload(version: DocumentVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "revision": version.revision,
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "effective_at": version.effective_at.isoformat() if version.effective_at else None,
        "expiration_or_superseded_at": version.expires_at.isoformat() if version.expires_at else None,
        "lifecycle_status": version.lifecycle_status,
        "is_current": version.lifecycle_status == "current",
        "superseded_by_version_id": version.superseded_by_version_id,
        "original_filename": version.original_filename,
        "mime_type": version.mime_type,
        "file_size": version.file_size,
        "uploaded_at": version.uploaded_at.isoformat() if version.uploaded_at else None,
        "uploaded_by": version.uploaded_by,
        "duplicate_of_version_id": version.duplicate_of_version_id,
        "file_sha256": version.file_sha256 or version.file_sha1,
    }


def _document_payload(db: Session, doc: Document, include_versions: bool = True) -> dict[str, Any]:
    versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == doc.id).order_by(DocumentVersion.effective_at.desc().nullslast(), DocumentVersion.id.desc())).all()
    current = [v for v in versions if v.lifecycle_status == "current"]
    latest = current[0] if len(current) == 1 else (versions[0] if versions else None)
    return {
        "id": doc.id,
        "title": doc.title,
        "document_type": doc.document_type,
        "document_number": doc.document_number,
        "manufacturer": doc.manufacturer_text,
        "equipment_family": doc.equipment_family_text,
        "equipment_model": doc.equipment_model_text,
        "language": doc.language,
        "source_url": doc.source_url,
        "ingestion_status": doc.ingestion_status,
        "ingestion_errors": doc.ingestion_errors,
        "verification_status": doc.verification_status,
        "notes": doc.notes,
        "conflicting_current_revisions": len(current) > 1,
        "current_version_id": latest.id if latest and latest.lifecycle_status == "current" else None,
        "versions": [_version_payload(v) for v in versions] if include_versions else [],
    }


def list_documents(db: Session, filters: dict[str, Any]) -> dict[str, Any]:
    stmt = select(Document)
    if filters.get("manufacturer"):
        stmt = stmt.where(Document.manufacturer_text.ilike(f"%{filters['manufacturer']}%"))
    if filters.get("model"):
        stmt = stmt.where(Document.equipment_model_text.ilike(f"%{filters['model']}%"))
    if filters.get("document_type"):
        stmt = stmt.where(Document.document_type == filters["document_type"])
    if filters.get("verification_status"):
        stmt = stmt.where(Document.verification_status == filters["verification_status"])
    if filters.get("q"):
        q = f"%{filters['q']}%"
        stmt = stmt.where(or_(Document.title.ilike(q), Document.document_number.ilike(q)))
    docs = db.scalars(stmt.order_by(Document.title, Document.id)).all()
    if filters.get("revision") or filters.get("lifecycle_status"):
        filtered = []
        for doc in docs:
            vstmt = select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
            if filters.get("revision"):
                vstmt = vstmt.where(DocumentVersion.revision == filters["revision"])
            if filters.get("lifecycle_status"):
                vstmt = vstmt.where(DocumentVersion.lifecycle_status == filters["lifecycle_status"])
            if db.scalar(vstmt):
                filtered.append(doc)
        docs = filtered
    total = len(docs)
    offset = filters.get("offset", 0)
    limit = filters.get("limit", 50)
    return {"ok": True, "count": len(docs[offset : offset + limit]), "total": total, "limit": limit, "offset": offset, "documents": [_document_payload(db, doc, include_versions=False) for doc in docs[offset : offset + limit]]}


def get_document(db: Session, document_id: int) -> dict[str, Any]:
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found.")
    return {"ok": True, "document": _document_payload(db, doc)}


def list_versions(db: Session, document_id: int) -> dict[str, Any]:
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found.")
    return {"ok": True, "document_id": document_id, "versions": _document_payload(db, doc)["versions"]}


def get_ingestion_status(db: Session, document_id: int) -> dict[str, Any]:
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found.")
    return {"ok": True, "document_id": document_id, "ingestion_status": doc.ingestion_status, "ingestion_errors": doc.ingestion_errors}


def change_document_version_state(db: Session, version_id: int, payload) -> dict[str, Any]:
    version = db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(404, "Document version not found.")
    if payload.superseded_by_version_id == version_id:
        raise HTTPException(400, "A document version cannot supersede itself.")
    if payload.superseded_by_version_id and _would_create_cycle(db, version_id, payload.superseded_by_version_id):
        raise HTTPException(400, "Circular document supersession is not allowed.")
    doc = db.get(Document, version.document_id)
    action = payload.status
    if action == "verified":
        doc.verification_status = "verified"
    elif action == "current":
        version.lifecycle_status = "current"
    elif action == "superseded":
        version.lifecycle_status = "superseded"
        version.superseded_by_version_id = payload.superseded_by_version_id
    elif action == "withdrawn":
        version.lifecycle_status = "withdrawn"
    db.add(AuditEvent(actor=payload.actor, action=f"document_version_{action}", entity_type="document_version", entity_id=str(version.id), details={"notes": payload.notes, "superseded_by_version_id": payload.superseded_by_version_id}))
    db.commit()
    return {"ok": True, "document": _document_payload(db, doc)}


def _would_create_cycle(db: Session, version_id: int, next_id: int) -> bool:
    seen = {version_id}
    current = db.get(DocumentVersion, next_id)
    while current:
        if current.id in seen:
            return True
        seen.add(current.id)
        current = db.get(DocumentVersion, current.superseded_by_version_id) if current.superseded_by_version_id else None
    return False


def retrieve_chunks(db: Session, question: str, manufacturer: str | None, model: str | None, include_historical: bool = False, limit: int = 5, _historical_fallback: bool = False):
    terms = {t.lower() for t in re.findall(r"[a-zA-Z0-9-]{3,}", question)}
    terms = {term for term in terms if term not in STOPWORDS}
    docs = db.execute(
        select(DocumentChunk, DocumentVersion, Document)
        .select_from(DocumentChunk)
        .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
    ).all()
    exact_terms = {term for term in terms if re.search(r"\d", term)}
    scored = []
    for chunk, version, doc in docs:
        if manufacturer and not normalize_label(doc.manufacturer_text) == normalize_label(manufacturer):
            continue
        if model and normalize_label(doc.equipment_model_text) != normalize_label(model):
            continue
        if doc.ingestion_status not in READY_STATUSES:
            continue
        if version.lifecycle_status == "withdrawn":
            continue
        if not include_historical and version.lifecycle_status != "current":
            continue
        if include_historical and version.lifecycle_status == "draft":
            continue
        if doc.verification_status not in {"verified", "source_imported_unverified", "unverified"}:
            continue
        text = chunk.search_text or (chunk.text or "").lower()
        if exact_terms and not any(term in text for term in exact_terms):
            continue
        score = sum(1 for term in terms if term in text)
        score += sum(3 for term in exact_terms if term in text)
        if version.lifecycle_status == "current":
            score += 2
        if doc.verification_status == "verified":
            score += 1
        if score > 0:
            if version.lifecycle_status == "superseded":
                evidence_scope = "historical"
            elif doc.verification_status != "verified":
                evidence_scope = "provisional"
            else:
                evidence_scope = "current_verified"
            scored.append((score, chunk, version, doc, evidence_scope))
    if not scored and not include_historical:
        return retrieve_chunks(db, question, manufacturer, model, include_historical=True, limit=limit, _historical_fallback=True)
    scored.sort(key=lambda item: (item[0], item[2].effective_at or item[2].published_at or date.min), reverse=True)
    return scored[:limit]


def _conflicting_current_revisions(db: Session, manufacturer: str | None, model: str | None) -> list[dict[str, Any]]:
    rows = db.execute(select(Document, DocumentVersion).join(DocumentVersion, DocumentVersion.document_id == Document.id).where(DocumentVersion.lifecycle_status == "current")).all()
    grouped: dict[tuple[Any, ...], list[tuple[Document, DocumentVersion]]] = {}
    for doc, version in rows:
        if manufacturer and normalize_label(doc.manufacturer_text) != normalize_label(manufacturer):
            continue
        if model and normalize_label(doc.equipment_model_text) != normalize_label(model):
            continue
        key = (doc.document_number, normalize_label(doc.manufacturer_text), normalize_label(doc.equipment_model_text))
        grouped.setdefault(key, []).append((doc, version))
    conflicts = []
    for (_doc_number, _manufacturer, _model), items in grouped.items():
        revisions = {version.revision for _doc, version in items}
        if len(items) > 1 and len(revisions) > 1:
            conflicts.append({"type": "conflicting_current_revisions", "document_number": items[0][0].document_number, "revisions": sorted(revisions)})
    return conflicts


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
    conflicts = _conflicting_current_revisions(db, payload.manufacturer, payload.model)
    evidence = [
        {
            "document_id": doc.id,
            "document_version_id": version.id,
            "document_title": doc.title,
            "title": doc.title,
            "document_number": doc.document_number,
            "revision": version.revision,
            "document_type": doc.document_type,
            "manufacturer": doc.manufacturer_text,
            "equipment_model": doc.equipment_model_text,
            "page": chunk.page_number,
            "page_number": chunk.page_number,
            "section": chunk.section,
            "section_heading": chunk.section,
            "extracted_fact": (chunk.text or "")[:500],
            "excerpt": (chunk.text or "")[:500],
            "lifecycle_status": version.lifecycle_status,
            "is_current": version.lifecycle_status == "current",
            "verification_status": doc.verification_status,
            "evidence_status": evidence_scope,
            "authoritative": evidence_scope == "current_verified",
            "warning": _evidence_warning(version.lifecycle_status, doc.verification_status),
            "source_url": doc.source_url,
            "retrieval_score": score,
        }
        for _score, chunk, version, doc, evidence_scope in hits
        for score in [_score]
    ]
    if not evidence:
        return {"ok": True, "answer": "No source evidence was found. AIBE will not invent a procedure, part number, error code, or citation.", "missing_information": [], "evidence": [], "inferences": [], "warnings": warnings, "conflicts": conflicts}
    return {
        "ok": True,
        "answer": "Relevant source excerpts were found. Review the cited pages before applying any service action.",
        "missing_information": [],
        "evidence": evidence,
        "inferences": ["Applicability depends on the exact model, configuration, serial range, hardware, and software version."],
        "warnings": warnings,
        "conflicts": conflicts + _detect_conflicts(evidence),
    }


def _evidence_warning(lifecycle_status: str, verification_status: str) -> str | None:
    if lifecycle_status == "superseded":
        return "Historical superseded evidence. Do not treat as current authority without review."
    if verification_status != "verified":
        return "Provisional unverified evidence. Qualified review is required before use."
    return None


def _detect_conflicts(evidence):
    joined = "\n".join(item["extracted_fact"].lower() for item in evidence)
    if "do not replace" in joined and "replace" in joined:
        return [{"type": "procedure_conflict", "detail": "Retrieved evidence contains both replacement and non-replacement language."}]
    return []


def _ingest_response(doc: Document | None, version: DocumentVersion, checksum: str, duplicate_of_version_id: int | None, errors: list[str]) -> dict[str, Any]:
    return {
        "ok": True,
        "document_id": version.document_id if not doc else doc.id,
        "document_version_id": version.id,
        "status": doc.ingestion_status if doc else "ready",
        "checksum": checksum,
        "file_sha256": checksum,
        "pages": 0,
        "duplicate_of_version_id": duplicate_of_version_id,
        "errors": errors,
    }
