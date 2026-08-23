from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from app.config import settings
from app.db.models import (
    AuditEvent,
    Base,
    DataQualityIssue,
    EquipmentFamily,
    EquipmentModel,
    ImportRun,
    ImportSourceRow,
    Manufacturer,
    Part,
    PartAlias,
    PartModelCompatibility,
)
from app.services.import_parts import DEFAULT_PARTS_XLSX, import_parts_spreadsheet
from app.services.normalization import clean_text, normalize_key


ISSUE_CLASSES = {
    "duplicate_part_conflicting_description": "conflicting information",
    "same_part_number_different_manufacturer": "conflicting information",
    "changed_source_row": "system/import error",
    "missing_or_invalid_part_number": "system/import error",
    "missing_manufacturer": "missing information",
    "suspected_model_number_as_part_number": "possible duplicate",
    "orphan_or_redundant_alias": "possible duplicate",
}


def _safe_database_identity() -> str:
    url = make_url(settings.database_url)
    if url.get_backend_name().startswith("sqlite"):
        return str(url.database)
    return str(url.set(password="***"))


def _latest_migration(db: Session) -> str | None:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None


def _spreadsheet_lineage(path: Path = DEFAULT_PARTS_XLSX) -> dict[str, Any]:
    df = pd.read_excel(path)
    physical_rows = len(df.index) + 1
    data_rows = 0
    blank_rows = 0
    usable_part_numbers = 0
    rows_without_manufacturer = 0
    rows_without_model = 0
    for _idx, row in df.iterrows():
        raw = {str(k): clean_text(v) for k, v in row.to_dict().items()}
        has_any = any(value for value in raw.values())
        if not has_any:
            blank_rows += 1
            continue
        data_rows += 1
        if normalize_key(raw.get("part number")):
            usable_part_numbers += 1
        if not clean_text(raw.get("Brand")):
            rows_without_manufacturer += 1
        if not clean_text(raw.get("Equipment1")):
            rows_without_model += 1
    return {
        "spreadsheet_path": str(path.resolve()),
        "spreadsheet_physical_rows": physical_rows,
        "spreadsheet_data_rows": data_rows,
        "blank_or_ignored_rows": blank_rows,
        "rows_with_usable_part_number": usable_part_numbers,
        "rows_without_manufacturer": rows_without_manufacturer,
        "rows_without_model": rows_without_model,
        "rows_without_usable_part_number": data_rows - usable_part_numbers,
    }


def _issue_identity(issue: DataQualityIssue) -> str:
    evidence = issue.evidence or {}
    conflict = issue.conflicting_values or {}
    key = {
        "issue_type": issue.issue_type,
        "source_row": issue.source_row,
        "entity_type": issue.entity_type,
        "entity_id": issue.entity_id,
        "part_number": normalize_key(evidence.get("part_number")),
        "conflict": conflict.get("conflicts") or conflict.get("incoming_raw") or conflict,
    }
    return json.dumps(key, sort_keys=True, default=str)


def _issue_summary(db: Session) -> dict[str, Any]:
    issues = db.query(DataQualityIssue).all()
    open_issues = [issue for issue in issues if getattr(issue.status, "value", issue.status) == "open"]
    by_type = Counter(issue.issue_type for issue in open_issues)
    by_severity = Counter(issue.severity for issue in open_issues)
    by_import = Counter(str(issue.source_import_id) for issue in open_issues)
    manufacturer = Counter()
    model = Counter()
    duplicates = defaultdict(list)
    for issue in open_issues:
        evidence = issue.evidence or {}
        manufacturer[clean_text(evidence.get("manufacturer")) or "unknown"] += 1
        model[clean_text(evidence.get("equipment_model")) or "unknown"] += 1
        duplicates[_issue_identity(issue)].append(issue.id)
    duplicate_groups = [ids for ids in duplicates.values() if len(ids) > 1]
    type_details = {}
    total = len(open_issues) or 1
    for issue_type, count in by_type.items():
        blocks_search = issue_type in {"missing_or_invalid_part_number", "same_part_number_different_manufacturer"}
        blocks_identification = issue_type in {"missing_or_invalid_part_number", "duplicate_part_conflicting_description", "same_part_number_different_manufacturer"}
        evidence_requirement = {
            "duplicate_part_conflicting_description": "Requires engineer, steward, or manufacturer evidence before choosing a canonical value.",
            "same_part_number_different_manufacturer": "Requires manufacturer or authoritative source evidence before merge or canonicalization.",
            "missing_manufacturer": "Requires source-backed steward review; do not auto-fill from guesswork.",
            "orphan_or_redundant_alias": "May be auto-suggested, but still needs steward review before mutation.",
            "suspected_model_number_as_part_number": "Requires source-backed steward or engineer review.",
            "missing_or_invalid_part_number": "Requires source correction or documented rejection.",
            "changed_source_row": "Requires source-row review to determine whether the change is expected.",
        }.get(issue_type, "Requires steward review.")
        type_details[issue_type] = {
            "count": count,
            "percentage": round(count / total * 100, 2),
            "category": ISSUE_CLASSES.get(issue_type, "unverified information"),
            "blocks_search": blocks_search,
            "blocks_identification": blocks_identification,
            "automatic_resolution_possible": issue_type in {"orphan_or_redundant_alias"},
            "requires_manual_source_evidence": issue_type
            in {"duplicate_part_conflicting_description", "same_part_number_different_manufacturer", "missing_manufacturer", "suspected_model_number_as_part_number"},
            "evidence_requirement": evidence_requirement,
        }
    return {
        "total_issues": len(issues),
        "open_issues": len(open_issues),
        "by_type": dict(sorted(by_type.items())),
        "by_type_details": type_details,
        "by_severity": dict(sorted(by_severity.items())),
        "by_source_import": dict(sorted(by_import.items())),
        "by_manufacturer": dict(manufacturer.most_common()),
        "by_equipment_model": dict(model.most_common()),
        "duplicate_issue_groups": duplicate_groups,
        "duplicate_issue_group_count": len(duplicate_groups),
        "blocking_ambiguity_count": sum(
            1
            for issue in open_issues
            if issue.issue_type == "duplicate_part_conflicting_description"
        ),
        "multiple_issues_per_source_row": {
            str(row): count
            for row, count in Counter(issue.source_row for issue in open_issues if issue.source_row).items()
            if count > 1
        },
    }


def _latest_import_counts(db: Session, spreadsheet: dict[str, Any]) -> dict[str, Any]:
    latest = db.query(ImportRun).order_by(ImportRun.id.desc()).first()
    if not latest:
        return {
            "import_run_id": None,
            "spreadsheet_data_rows": spreadsheet["spreadsheet_data_rows"],
            "accepted_rows": 0,
            "inserted_rows": 0,
            "updated_rows": 0,
            "skipped_rows": 0,
            "ambiguous_rows": 0,
            "rejected_rows": 0,
            "source_rows_created": 0,
        }
    rows = db.query(ImportSourceRow).filter_by(import_run_id=latest.id)
    return {
        "import_run_id": latest.id,
        "created_at": latest.created_at.isoformat(),
        "source_name": latest.source_name,
        "spreadsheet_data_rows": spreadsheet["spreadsheet_data_rows"],
        "accepted_rows": rows.filter(ImportSourceRow.row_status.in_(["inserted", "updated", "skipped"])).count(),
        "inserted_rows": rows.filter_by(row_status="inserted").count(),
        "updated_rows": rows.filter_by(row_status="updated").count(),
        "skipped_rows": rows.filter_by(row_status="skipped").count(),
        "ambiguous_rows": rows.filter_by(row_status="ambiguous").count(),
        "rejected_rows": rows.filter_by(row_status="rejected").count(),
        "source_rows_created": rows.count(),
    }


def _historical_import_counts(db: Session) -> dict[str, Any]:
    return {
        "import_run_count": db.query(ImportRun).count(),
        "total_preserved_source_rows": db.query(ImportSourceRow).count(),
        "total_audit_events": db.query(AuditEvent).count(),
    }


def _canonical_catalog_counts(db: Session) -> dict[str, Any]:
    return {
        "unique_parts": db.query(Part).count(),
        "unique_normalized_part_numbers": len({part.normalized_part_number for part in db.query(Part).all()}),
        "aliases": db.query(PartAlias).count(),
        "manufacturers": db.query(Manufacturer).count(),
        "equipment_families": db.query(EquipmentFamily).count(),
        "models": db.query(EquipmentModel).count(),
        "compatibility_links": db.query(PartModelCompatibility).count(),
        "parts_without_manufacturer": db.query(Part).filter(Part.manufacturer_id.is_(None)).count(),
    }


def run_isolated_idempotency_check(runs: int = 3) -> dict[str, Any]:
    with NamedTemporaryFile(prefix="aibe-audit-", suffix=".db") as tmp:
        engine = create_engine(f"sqlite:///{tmp.name}", future=True)
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine, future=True)
        snapshots = []
        for _index in range(runs):
            with SessionLocal() as db:
                report = import_parts_spreadsheet(db)
                snapshots.append(
                    {
                        "report": report.as_dict(),
                        "import_runs": db.query(ImportRun).count(),
                        "source_rows": db.query(ImportSourceRow).count(),
                        "canonical_parts": db.query(Part).count(),
                        "aliases": db.query(PartAlias).count(),
                        "compatibility_links": db.query(PartModelCompatibility).count(),
                        "open_issues": db.query(DataQualityIssue).filter(DataQualityIssue.status == "open").count(),
                        "audit_events": db.query(AuditEvent).count(),
                    }
                )
        first = snapshots[0]
        last = snapshots[-1]
        return {
            "runs": runs,
            "snapshots": snapshots,
            "passed": (
                first["canonical_parts"] == last["canonical_parts"]
                and first["aliases"] == last["aliases"]
                and first["compatibility_links"] == last["compatibility_links"]
                and first["open_issues"] == last["open_issues"]
                and last["import_runs"] == runs
                and last["source_rows"] == first["source_rows"] * runs
            ),
            "policy": "Import runs and source rows are append-only audit records; canonical parts, aliases, compatibility links, and identical open issues must not duplicate.",
        }


def build_catalog_audit_report(db: Session, include_idempotency: bool = False) -> dict[str, Any]:
    from reconcile_catalog import build_reconciliation_report

    spreadsheet = _spreadsheet_lineage()
    issues = _issue_summary(db)
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "database": {"identity": _safe_database_identity(), "latest_migration": _latest_migration(db)},
        "latest_import": _latest_import_counts(db, spreadsheet),
        "historical_imports": _historical_import_counts(db),
        "canonical_catalog": _canonical_catalog_counts(db),
        "spreadsheet": spreadsheet,
        "issues": issues,
        "legacy_comparison": build_reconciliation_report(),
        "definitions": {
            "spreadsheet_physical_rows": "Header row plus rows read from the spreadsheet worksheet.",
            "spreadsheet_data_rows": "Nonblank spreadsheet rows.",
            "latest_import.accepted_rows": "Rows in the latest import run with inserted, updated, or skipped row status.",
            "latest_import.inserted_rows": "Rows in the latest import run that created a canonical normalized part.",
            "latest_import.updated_rows": "Rows in the latest import run that updated an existing canonical normalized part.",
            "latest_import.skipped_rows": "Rows in the latest import run that matched existing canonical data and did not change it.",
            "latest_import.ambiguous_rows": "Rows in the latest import run preserved for review because they conflict with canonical data.",
            "latest_import.rejected_rows": "Rows in the latest import run rejected with a recorded reason.",
            "latest_import.source_rows_created": "ImportSourceRow records created by the latest import run only.",
            "historical_imports.total_preserved_source_rows": "All ImportSourceRow records across every import run; this is intentionally cumulative.",
            "canonical_catalog.unique_parts": "Unique operational Part records in the normalized database.",
            "aliases": "PartAlias records linked to canonical parts.",
            "compatibility_links": "PartModelCompatibility records linked to canonical parts and equipment models.",
            "open_data_quality_issue_count": "DataQualityIssue records with status open.",
            "blocking_ambiguity_count": "Open duplicate/conflicting-description issues that block authoritative identification until reviewed.",
        },
        "historical_notes": [
            "The previous 147-inserted report cannot be reconciled with the current 133-row spreadsheet as a row count unless historical evidence establishes that it included multiple entity types, such as manufacturers, models, families, and parts.",
        ],
    }
    if include_idempotency:
        report["idempotency_check"] = run_isolated_idempotency_check()
    return report
