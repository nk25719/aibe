from pathlib import Path

import pandas as pd

from app.config import settings
from app.db.models import AuditEvent, DataQualityIssue, ImportRun, ImportSourceRow, Part, PartAlias, PartModelCompatibility
from app.services.catalog_audit import build_catalog_audit_report, run_isolated_idempotency_check
from app.services.catalog_query import CatalogSearchParams, search_catalog
from app.services.import_parts import import_parts_spreadsheet


def test_catalog_audit_metric_definitions(db_session):
    import_parts_spreadsheet(db_session)

    report = build_catalog_audit_report(db_session)

    assert set(["latest_import", "historical_imports", "canonical_catalog"]).issubset(report)
    assert report["latest_import"]["spreadsheet_data_rows"] >= report["canonical_catalog"]["unique_parts"]
    assert report["latest_import"]["source_rows_created"] == 133
    assert report["latest_import"]["inserted_rows"] == 123
    assert report["latest_import"]["updated_rows"] == 0
    assert report["latest_import"]["skipped_rows"] == 6
    assert report["latest_import"]["ambiguous_rows"] == 4
    assert report["latest_import"]["rejected_rows"] == 0
    assert report["latest_import"]["accepted_rows"] == 129
    assert report["historical_imports"]["total_preserved_source_rows"] == db_session.query(ImportSourceRow).count()
    assert report["canonical_catalog"]["unique_parts"] == db_session.query(Part).count()
    assert report["canonical_catalog"]["aliases"] == db_session.query(PartAlias).count()
    assert report["canonical_catalog"]["compatibility_links"] == db_session.query(PartModelCompatibility).count()
    assert report["issues"]["blocking_ambiguity_count"] == 4
    assert report["issues"]["by_type_details"]["duplicate_part_conflicting_description"]["requires_manual_source_evidence"] is True
    assert report["issues"]["by_type_details"]["missing_manufacturer"]["requires_manual_source_evidence"] is True
    assert report["issues"]["by_type_details"]["orphan_or_redundant_alias"]["requires_manual_source_evidence"] is False
    assert "historical_imports.total_preserved_source_rows" in report["definitions"]


def test_latest_import_metrics_do_not_use_cumulative_source_rows(db_session):
    import_parts_spreadsheet(db_session)
    import_parts_spreadsheet(db_session)

    report = build_catalog_audit_report(db_session)

    assert report["latest_import"]["source_rows_created"] == 133
    assert report["latest_import"]["inserted_rows"] == 0
    assert report["latest_import"]["updated_rows"] == 0
    assert report["latest_import"]["skipped_rows"] == 129
    assert report["latest_import"]["ambiguous_rows"] == 4
    assert report["historical_imports"]["total_preserved_source_rows"] == 266
    assert report["latest_import"]["source_rows_created"] != report["historical_imports"]["total_preserved_source_rows"]


def test_isolated_repeated_import_is_idempotent():
    result = run_isolated_idempotency_check(runs=3)

    assert result["passed"] is True
    assert result["snapshots"][0]["canonical_parts"] == result["snapshots"][-1]["canonical_parts"]
    assert result["snapshots"][0]["aliases"] == result["snapshots"][-1]["aliases"]
    assert result["snapshots"][0]["compatibility_links"] == result["snapshots"][-1]["compatibility_links"]
    assert result["snapshots"][0]["open_issues"] == result["snapshots"][-1]["open_issues"]
    assert result["snapshots"][-1]["import_runs"] == 3


def test_changed_spreadsheet_row_is_detected_in_isolated_db(db_session, tmp_path):
    path = tmp_path / "parts.xlsx"
    pd.DataFrame([{"part number": "PN-100", "Description": "Original", "Brand": "Maker"}]).to_excel(path, index=False)
    import_parts_spreadsheet(db_session, Path(path))

    pd.DataFrame([{"part number": "PN-100", "Description": "Original", "Brand": "Changed Maker"}]).to_excel(path, index=False)
    report = import_parts_spreadsheet(db_session, Path(path))

    assert report.changed == 1
    assert db_session.query(DataQualityIssue).filter_by(issue_type="changed_source_row").count() == 1


def test_normalized_search_does_not_need_legacy_db(db_session, monkeypatch):
    import_parts_spreadsheet(db_session)
    monkeypatch.setattr(settings, "legacy_parts_db_path", Path("/tmp/aibe-missing-parts.db"))

    response = search_catalog(db_session, CatalogSearchParams(q="755534", manufacturer="GE Healthcare", enable_legacy_fallback=False))

    assert response["source"] == "normalized_catalog"
    assert response["results"][0]["part_number"] == "755534-HEL"
    assert db_session.query(AuditEvent).filter_by(action="legacy_search_fallback_used").count() == 0
