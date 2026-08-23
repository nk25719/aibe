from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import TroubleshootingRequest, TroubleshootingResponse
from app.services.troubleshooting import create_troubleshooting_case

router = APIRouter(prefix="/troubleshooting")


@router.post("/cases", response_model=TroubleshootingResponse)
def create_case(payload: TroubleshootingRequest, db: Session = Depends(get_db)):
    return create_troubleshooting_case(db, payload)
