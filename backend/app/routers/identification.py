from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import CandidateActionRequest, CandidateActionResponse, IdentificationCaseResponse
from app.services.identification import CaseInput, create_identification_case, record_candidate_action

router = APIRouter(prefix="/identification")


@router.post("/cases", response_model=IdentificationCaseResponse)
async def create_case(
    manufacturer: str = Form(..., min_length=1, max_length=255),
    equipment_family: str | None = Form(default=None, max_length=255),
    equipment_model: str | None = Form(default=None, max_length=255),
    description: str | None = Form(default=None, max_length=1000),
    visible_markings: str | None = Form(default=None, max_length=1000),
    component_location: str | None = Form(default=None, max_length=1000),
    opened_by: str | None = Form(default=None, max_length=255),
    top_k: int = Query(5, ge=1, le=10),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    return await create_identification_case(
        db,
        CaseInput(
            manufacturer=manufacturer,
            equipment_family=equipment_family,
            equipment_model=equipment_model,
            description=description,
            visible_markings=visible_markings,
            component_location=component_location,
            opened_by=opened_by,
            top_k=top_k,
        ),
        files,
    )


@router.post("/cases/{case_id}/candidates/{candidate_id}/action", response_model=CandidateActionResponse)
def candidate_action(case_id: int, candidate_id: int, payload: CandidateActionRequest, db: Session = Depends(get_db)):
    return record_candidate_action(db, case_id, candidate_id, payload.action, payload.user, payload.notes)
