from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import (
    DocumentIngestRequest,
    DocumentIngestResponse,
    DocumentListResponse,
    DocumentStateChangeRequest,
    DocumentTypeLiteral,
    DocumentUploadMetadata,
    TechnicalQuestionRequest,
    TechnicalQuestionResponse,
)
from app.security import require_admin
from app.services.documents import (
    answer_question,
    change_document_version_state,
    get_document,
    get_ingestion_status,
    ingest_document,
    list_documents,
    list_versions,
    upload_document,
)

router = APIRouter(prefix="/documents")


@router.get("", response_model=DocumentListResponse)
def list_library_documents(
    q: str | None = None,
    manufacturer: str | None = None,
    model: str | None = None,
    document_type: DocumentTypeLiteral | None = None,
    revision: str | None = None,
    lifecycle_status: str | None = Query(default=None, pattern="^(draft|current|superseded|withdrawn)$"),
    verification_status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return list_documents(
        db,
        {
            "q": q,
            "manufacturer": manufacturer,
            "model": model,
            "document_type": document_type,
            "revision": revision,
            "lifecycle_status": lifecycle_status,
            "verification_status": verification_status,
            "limit": limit,
            "offset": offset,
        },
    )


@router.get("/{document_id}")
def document_metadata(document_id: int, db: Session = Depends(get_db)):
    return get_document(db, document_id)


@router.get("/{document_id}/versions")
def document_versions(document_id: int, db: Session = Depends(get_db)):
    return list_versions(db, document_id)


@router.get("/{document_id}/ingestion-status")
def document_ingestion_status(document_id: int, db: Session = Depends(get_db)):
    return get_ingestion_status(db, document_id)


@router.post("/upload", response_model=DocumentIngestResponse, dependencies=[Depends(require_admin)])
def upload(
    file: UploadFile = File(...),
    title: str = Form(...),
    document_type: DocumentTypeLiteral = Form(...),
    manufacturer: str = Form(...),
    equipment_family: str | None = Form(default=None),
    equipment_model: str | None = Form(default=None),
    document_number: str | None = Form(default=None),
    revision: str = Form(default="unknown"),
    published_at: str | None = Form(default=None),
    effective_at: str | None = Form(default=None),
    expiration_or_superseded_at: str | None = Form(default=None),
    lifecycle_status: str = Form(default="draft"),
    language: str = Form(default="en"),
    source_url: str | None = Form(default=None),
    verification_status: str = Form(default="unverified"),
    notes: str | None = Form(default=None),
    uploaded_by: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    metadata = DocumentUploadMetadata(
        title=title,
        document_type=document_type,
        manufacturer=manufacturer,
        equipment_family=equipment_family,
        equipment_model=equipment_model,
        document_number=document_number,
        revision=revision,
        published_at=published_at,
        effective_at=effective_at,
        expiration_or_superseded_at=expiration_or_superseded_at,
        lifecycle_status=lifecycle_status,
        language=language,
        source_url=source_url,
        verification_status=verification_status,
        notes=notes,
        uploaded_by=uploaded_by,
    )
    return upload_document(db, file, metadata)


@router.post("/ingest", response_model=DocumentIngestResponse, dependencies=[Depends(require_admin)])
def ingest(payload: DocumentIngestRequest, db: Session = Depends(get_db)):
    return ingest_document(db, payload)


@router.post("/qa", response_model=TechnicalQuestionResponse)
def qa(payload: TechnicalQuestionRequest, db: Session = Depends(get_db)):
    return answer_question(db, payload)


@router.post("/versions/{version_id}/state", dependencies=[Depends(require_admin)])
def update_version_state(version_id: int, payload: DocumentStateChangeRequest, db: Session = Depends(get_db)):
    return change_document_version_state(db, version_id, payload)
