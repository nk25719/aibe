from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import ImportReportResponse
from app.security import require_admin
from app.services.import_parts import import_parts_spreadsheet

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.post("/import-parts", response_model=ImportReportResponse)
def import_parts(db: Session = Depends(get_db)):
    report = import_parts_spreadsheet(db)
    return {"ok": True, "report": report.as_dict()}
