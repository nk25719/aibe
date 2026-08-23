from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import DataQualityIssueStatus
from app.db.session import get_db
from app.schemas.api import ImportReportResponse
from app.security import require_admin
from app.services.import_parts import (
    export_issues,
    import_parts_spreadsheet,
    list_data_quality_issues,
    list_import_runs,
    resolve_data_quality_issue,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.post("/import-parts", response_model=ImportReportResponse)
def import_parts(db: Session = Depends(get_db)):
    report = import_parts_spreadsheet(db)
    return {"ok": True, "report": report.as_dict()}


@router.get("/import-runs")
def import_runs(db: Session = Depends(get_db)):
    return {"ok": True, "runs": list_import_runs(db)}


@router.get("/data-quality/issues")
def data_quality_issues(
    status: str | None = Query(default=None),
    issue_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return {"ok": True, "issues": list_data_quality_issues(db, status=status, issue_type=issue_type)}


class ResolveIssueRequest(BaseModel):
    status: DataQualityIssueStatus
    resolution_selected: str = Field(min_length=1, max_length=100)
    resolution_notes: str = Field(min_length=1, max_length=2000)
    resolved_by: str = Field(min_length=1, max_length=255)
    evidence: dict | None = None


@router.post("/data-quality/issues/{issue_id}/resolve")
def resolve_issue(issue_id: int, payload: ResolveIssueRequest, db: Session = Depends(get_db)):
    try:
        issue = resolve_data_quality_issue(
            db,
            issue_id,
            status=payload.status,
            resolution_selected=payload.resolution_selected,
            resolution_notes=payload.resolution_notes,
            resolved_by=payload.resolved_by,
            evidence=payload.evidence,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Data-quality issue not found.")
    return {"ok": True, "issue": issue}


@router.get("/data-quality/issues/export")
def export_data_quality_issues(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    issues = list_data_quality_issues(db, status=status)
    media_type = "application/json" if format == "json" else "text/csv"
    extension = "json" if format == "json" else "csv"
    return Response(
        export_issues(issues, format),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="aibe-data-quality-issues.{extension}"'},
    )
