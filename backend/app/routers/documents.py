from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import DocumentIngestRequest, DocumentIngestResponse, TechnicalQuestionRequest, TechnicalQuestionResponse
from app.security import require_admin
from app.services.documents import answer_question, ingest_document

router = APIRouter(prefix="/documents")


@router.post("/ingest", response_model=DocumentIngestResponse, dependencies=[Depends(require_admin)])
def ingest(payload: DocumentIngestRequest, db: Session = Depends(get_db)):
    return ingest_document(db, payload)


@router.post("/qa", response_model=TechnicalQuestionResponse)
def qa(payload: TechnicalQuestionRequest, db: Session = Depends(get_db)):
    return answer_question(db, payload)
