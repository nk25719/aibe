from pathlib import Path

import pandas as pd

from app.db.models import AuditEvent, DataQualityIssue, DataQualityIssueStatus, ImportRun, ImportSourceRow, Part
from app.services.import_parts import import_parts_spreadsheet
from app.services.import_parts import resolve_data_quality_issue
from app.services.normalization import normalize_key


def test_parts_import_is_idempotent(db_session):
    first = import_parts_spreadsheet(db_session)
    first_count = db_session.query(Part).count()
    second = import_parts_spreadsheet(db_session)
    second_count = db_session.query(Part).count()

    assert first.rejected == 0
    assert first_count == 123
    assert second_count == first_count
    assert second.inserted == 0
    assert second.rejected == 0
    assert db_session.query(ImportRun).count() == 2
    assert db_session.query(ImportSourceRow).count() >= first_count * 2


def test_part_number_normalization_prevents_duplicate_parts():
    assert normalize_key(" M1115795-S ") == normalize_key("m1115795-s")


def test_duplicate_conflicts_create_review_issues(db_session, tmp_path):
    path = tmp_path / "parts.xlsx"
    pd.DataFrame(
        [
            {"part number": "2066261-085", "Description": "Cable A", "Brand": "GE Healthcare", "Equipment1": "TM-100"},
            {"part number": "2066261-085", "Description": "Cable B", "Brand": "GE Healthcare", "Equipment1": "TM-100"},
            {"part number": "M-10", "Description": "Motor filter", "Brand": "Acme", "Equipment1": "Vent A"},
            {"part number": "M-10", "Description": "Model M-10", "Brand": "Acme", "Equipment1": "Vent B"},
        ]
    ).to_excel(path, index=False)

    report = import_parts_spreadsheet(db_session, Path(path))

    issues = db_session.query(DataQualityIssue).order_by(DataQualityIssue.id).all()
    assert report.ambiguous == 2
    assert {issue.issue_type for issue in issues} == {"duplicate_part_conflicting_description"}
    assert any(issue.evidence["part_number"] == "2066261-085" for issue in issues)
    assert any(issue.evidence["part_number"] == "M-10" for issue in issues)
    assert db_session.query(ImportSourceRow).count() == 4


def test_changed_source_row_detection(db_session, tmp_path):
    path = tmp_path / "parts.xlsx"
    pd.DataFrame([{"part number": "PN-1", "Description": "Original", "Brand": "Maker"}]).to_excel(path, index=False)
    import_parts_spreadsheet(db_session, Path(path))

    pd.DataFrame([{"part number": "PN-1", "Description": "Original", "Brand": "Changed Maker"}]).to_excel(path, index=False)
    report = import_parts_spreadsheet(db_session, Path(path))

    assert report.changed == 1
    assert db_session.query(DataQualityIssue).filter_by(issue_type="changed_source_row").count() == 1


def test_data_quality_resolution_creates_audit_event(db_session, tmp_path):
    path = tmp_path / "parts.xlsx"
    pd.DataFrame(
        [
            {"part number": "PN-2", "Description": "One", "Brand": "Maker"},
            {"part number": "PN-2", "Description": "Two", "Brand": "Maker"},
        ]
    ).to_excel(path, index=False)
    import_parts_spreadsheet(db_session, Path(path))
    issue = db_session.query(DataQualityIssue).one()

    resolved = resolve_data_quality_issue(
        db_session,
        issue.id,
        status=DataQualityIssueStatus.accepted_as_distinct,
        resolution_selected="accepted_as_distinct",
        resolution_notes="Descriptions refer to distinct field usages in the fixture.",
        resolved_by="data-steward",
    )

    assert resolved["status"] == "accepted_as_distinct"
    assert db_session.query(AuditEvent).filter_by(action="data_quality_issue_resolved").count() == 1
