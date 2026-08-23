from dataclasses import dataclass, field
from datetime import datetime
import csv
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.db.models import (
    AuditEvent,
    DataQualityIssue,
    DataQualityIssueStatus,
    EquipmentFamily,
    EquipmentModel,
    ImportRun,
    ImportRunStatus,
    ImportSourceRow,
    Manufacturer,
    ManufacturerAlias,
    Part,
    PartAlias,
    PartModelCompatibility,
    PartSupersession,
    SourceEvidence,
    SourceType,
)
from app.services.normalization import clean_text, normalize_key, normalize_label


DEFAULT_PARTS_XLSX = BASE_DIR / "AIBE Parts list.xlsx"
IMPORTER_VERSION = "2026-08-23-data-quality-v1"
MODEL_LIKE_PART_NUMBER = re.compile(r"^[A-Z]{1,4}-?\d{1,3}$", re.I)


@dataclass
class ImportReport:
    source_path: str
    import_run_id: int | None = None
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    ambiguous: int = 0
    rejected: int = 0
    changed: int = 0
    validation_errors: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "import_run_id": self.import_run_id,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "ambiguous": self.ambiguous,
            "rejected": self.rejected,
            "changed": self.changed,
            "validation_errors": self.validation_errors,
        }


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str, separators=(",", ":"))


def _sha1_bytes(raw: bytes) -> str:
    return hashlib.sha1(raw).hexdigest()


def _sha1_value(value: Any) -> str:
    return hashlib.sha1(_stable_json(value).encode("utf-8")).hexdigest()


def _issue_fingerprint(issue_type: str, entity_type: str, entity_id: str | None, payload: dict[str, Any]) -> str:
    basis = {"issue_type": issue_type, "entity_type": entity_type, "entity_id": entity_id, "payload": payload}
    return _sha1_value(basis)


def _create_or_update_issue(
    db: Session,
    *,
    issue_type: str,
    entity_type: str,
    entity_id: str | None,
    import_run_id: int,
    source_row_id: int | None,
    source_row: int | None,
    original_values: dict[str, Any] | None,
    conflicting_values: dict[str, Any] | None,
    severity: str,
    suggested_resolution: str,
    evidence: dict[str, Any] | None,
) -> DataQualityIssue:
    payload = {
        "source_row": source_row,
        "original_values": original_values,
        "conflicting_values": conflicting_values,
        "evidence": evidence,
    }
    fingerprint = _issue_fingerprint(issue_type, entity_type, entity_id, payload)
    issue = db.scalar(select(DataQualityIssue).where(DataQualityIssue.fingerprint == fingerprint))
    if issue:
        if issue.status in {DataQualityIssueStatus.resolved, DataQualityIssueStatus.merged, DataQualityIssueStatus.accepted_as_distinct}:
            return issue
        issue.source_import_id = import_run_id
        issue.source_row_id = source_row_id
        issue.updated_at = datetime.utcnow()
        return issue
    issue = DataQualityIssue(
        issue_type=issue_type,
        entity_type=entity_type,
        entity_id=entity_id,
        source_import_id=import_run_id,
        source_row_id=source_row_id,
        source_row=source_row,
        original_values=original_values,
        conflicting_values=conflicting_values,
        severity=severity,
        suggested_resolution=suggested_resolution,
        evidence=evidence,
        audit_history=[{"at": datetime.utcnow().isoformat(), "action": "created", "actor": "importer"}],
        fingerprint=fingerprint,
    )
    db.add(issue)
    db.flush()
    return issue


def _get_or_create_manufacturer(db: Session, raw_brand: str | None, report: ImportReport) -> Manufacturer | None:
    name = clean_text(raw_brand)
    normalized = normalize_label(name)
    if not name or not normalized:
        return None
    existing = db.scalar(select(Manufacturer).where(Manufacturer.normalized_name == normalized))
    if existing:
        return existing
    manufacturer = Manufacturer(name=name, normalized_name=normalized, raw_name=raw_brand)
    db.add(manufacturer)
    db.flush()
    db.add(ManufacturerAlias(manufacturer_id=manufacturer.id, alias=name, normalized_alias=normalized, source="parts_spreadsheet"))
    report.inserted += 1
    return manufacturer


def _get_or_create_model(
    db: Session,
    raw_model: str | None,
    category: str | None,
    manufacturer: Manufacturer | None,
    report: ImportReport,
) -> EquipmentModel | None:
    name = clean_text(raw_model)
    normalized = normalize_label(name)
    if not name or not normalized:
        return None
    manufacturer_id = manufacturer.id if manufacturer else None
    existing = db.scalar(
        select(EquipmentModel).where(
            EquipmentModel.manufacturer_id == manufacturer_id,
            EquipmentModel.normalized_model_name == normalized,
        )
    )
    if existing:
        if category and existing.category != category:
            existing.category = category
            report.updated += 1
        return existing
    family_name = category or name
    family_normalized = normalize_label(family_name) or normalized
    family = db.scalar(
        select(EquipmentFamily).where(
            EquipmentFamily.manufacturer_id == manufacturer_id,
            EquipmentFamily.normalized_name == family_normalized,
        )
    )
    if not family:
        family = EquipmentFamily(
            manufacturer_id=manufacturer_id,
            name=family_name,
            normalized_name=family_normalized,
            raw_name=category or raw_model,
        )
        db.add(family)
        db.flush()
    model = EquipmentModel(
        manufacturer_id=manufacturer_id,
        family_id=family.id,
        model_name=name,
        normalized_model_name=normalized,
        raw_name=raw_model,
        category=category,
    )
    db.add(model)
    db.flush()
    report.inserted += 1
    return model


def import_parts_spreadsheet(db: Session, source_path: Path = DEFAULT_PARTS_XLSX) -> ImportReport:
    source_bytes = source_path.read_bytes()
    source_sha1 = _sha1_bytes(source_bytes)
    report = ImportReport(source_path=str(source_path.resolve()))
    import_run = ImportRun(
        source_path=str(source_path.resolve()),
        source_name=source_path.name,
        source_sha1=source_sha1,
        importer_version=IMPORTER_VERSION,
        status=ImportRunStatus.completed,
    )
    db.add(import_run)
    db.flush()
    report.import_run_id = import_run.id
    df = pd.read_excel(source_path)
    imported_at = datetime.utcnow().isoformat()

    for row_number, row in df.iterrows():
        raw = {str(k): clean_text(v) for k, v in row.to_dict().items()}
        source_row_number = int(row_number) + 2
        row_key = f"{source_path.name}:{source_row_number}"
        row_sha1 = _sha1_value(raw)
        previous_row = db.scalar(
            select(ImportSourceRow)
            .where(ImportSourceRow.source_name == source_path.name, ImportSourceRow.source_row == source_row_number)
            .order_by(ImportSourceRow.id.desc())
        )
        previous_row_sha1 = previous_row.row_sha1 if previous_row else None
        part_number = clean_text(raw.get("part number"))
        normalized_part_number = normalize_key(part_number)
        if not part_number or not normalized_part_number:
            report.rejected += 1
            source_row_record = ImportSourceRow(
                import_run_id=import_run.id,
                source_path=str(source_path.resolve()),
                source_name=source_path.name,
                source_sha1=source_sha1,
                source_row=source_row_number,
                row_key=row_key,
                row_sha1=row_sha1,
                previous_row_sha1=previous_row_sha1,
                row_status="rejected",
                rejection_reason="missing_part_number",
                raw_values=raw,
                normalized_values={"part_number": part_number, "normalized_part_number": normalized_part_number},
            )
            db.add(source_row_record)
            db.flush()
            report.validation_errors.append({"row": source_row_number, "error": "missing_part_number", "raw": raw})
            _create_or_update_issue(
                db,
                issue_type="missing_or_invalid_part_number",
                entity_type="import_source_row",
                entity_id=row_key,
                import_run_id=import_run.id,
                source_row_id=source_row_record.id,
                source_row=source_row_number,
                original_values=raw,
                conflicting_values=None,
                severity="high",
                suggested_resolution="Correct the source part number or reject the source row with a documented reason.",
                evidence={"source_name": source_path.name},
            )
            continue

        brand = clean_text(raw.get("Brand"))
        equipment = clean_text(raw.get("Equipment1"))
        category = clean_text(raw.get("EQ category"))
        alternate = clean_text(raw.get("Alternate PN"))
        description = clean_text(raw.get("Description"))
        natural_description = clean_text(raw.get("Natural Description"))
        normalized_values = {
            "part_number": part_number,
            "normalized_part_number": normalized_part_number,
            "manufacturer": brand,
            "normalized_manufacturer": normalize_label(brand),
            "equipment_model": equipment,
            "normalized_equipment_model": normalize_label(equipment),
            "alternate_part_number": alternate,
            "normalized_alternate_part_number": normalize_key(alternate),
            "description": description,
            "natural_description": natural_description,
            "category": category,
        }
        row_changed = bool(previous_row_sha1 and previous_row_sha1 != row_sha1)

        manufacturer = _get_or_create_manufacturer(db, brand, report)
        model = _get_or_create_model(db, equipment, category, manufacturer, report)

        evidence = SourceEvidence(
            source_type=SourceType.spreadsheet,
            internal_reference=f"{source_path.name}:row:{source_row_number}",
            extraction_method="pandas.read_excel",
            imported_at=datetime.utcnow(),
            confidence=0.6,
            notes="Imported from user-provided parts spreadsheet; relationships are not engineer verified.",
        )
        db.add(evidence)
        db.flush()

        source_row_record = ImportSourceRow(
            import_run_id=import_run.id,
            source_path=str(source_path.resolve()),
            source_name=source_path.name,
            source_sha1=source_sha1,
            source_row=source_row_number,
            row_key=row_key,
            row_sha1=row_sha1,
            previous_row_sha1=previous_row_sha1,
            row_status="processing",
            raw_values=raw,
            normalized_values=normalized_values,
            evidence_id=evidence.id,
        )
        db.add(source_row_record)
        db.flush()
        if row_changed:
            report.changed += 1
            _create_or_update_issue(
                db,
                issue_type="changed_source_row",
                entity_type="import_source_row",
                entity_id=row_key,
                import_run_id=import_run.id,
                source_row_id=source_row_record.id,
                source_row=source_row_number,
                original_values=previous_row.raw_values if previous_row else None,
                conflicting_values=raw,
                severity="medium",
                suggested_resolution="Review the changed source row before using it as authoritative technical data.",
                evidence={"previous_row_sha1": previous_row_sha1, "row_sha1": row_sha1},
            )

        part = db.scalar(select(Part).where(Part.normalized_part_number == normalized_part_number))
        provenance = {
            "source_type": "spreadsheet",
            "source": source_path.name,
            "row_number": int(row_number) + 2,
            "imported_at": imported_at,
            "evidence_id": evidence.id,
        }
        if part:
            conflicting_fields = []
            conflicts: dict[str, Any] = {}
            if description and part.description and part.description != description:
                conflicting_fields.append("description")
                conflicts["description"] = {"existing": part.description, "incoming": description}
            if natural_description and part.natural_description and part.natural_description != natural_description:
                conflicting_fields.append("natural_description")
                conflicts["natural_description"] = {"existing": part.natural_description, "incoming": natural_description}
            if conflicting_fields:
                report.ambiguous += 1
                source_row_record.row_status = "ambiguous"
                report.validation_errors.append(
                    {
                        "row": source_row_number,
                        "error": "duplicate_part_conflicting_values",
                        "part_number": part_number,
                        "fields": conflicting_fields,
                    }
                )
                _create_or_update_issue(
                    db,
                    issue_type="duplicate_part_conflicting_description",
                    entity_type="part",
                    entity_id=str(part.id),
                    import_run_id=import_run.id,
                    source_row_id=source_row_record.id,
                    source_row=source_row_number,
                    original_values=part.raw_values,
                    conflicting_values={"incoming_raw": raw, "conflicts": conflicts},
                    severity="high",
                    suggested_resolution="Compare source evidence and either accept as distinct records, choose a canonical value with notes, or explicitly merge.",
                    evidence={
                        "part_number": part_number,
                        "normalized_part_number": normalized_part_number,
                        "manufacturer": brand,
                        "equipment_model": equipment,
                        "alternate_part_number": alternate,
                        "category": category,
                    },
                )
            else:
                changed = False
                if description and part.description != description:
                    part.description = description
                    changed = True
                if natural_description and part.natural_description != natural_description:
                    part.natural_description = natural_description
                    changed = True
                if changed:
                    part.raw_values = raw
                    part.provenance = provenance
                    report.updated += 1
                    source_row_record.row_status = "updated"
                else:
                    report.skipped += 1
                    source_row_record.row_status = "skipped"
            existing_brand = clean_text((part.raw_values or {}).get("Brand"))
            if brand and existing_brand and normalize_label(brand) != normalize_label(existing_brand):
                _create_or_update_issue(
                    db,
                    issue_type="same_part_number_different_manufacturer",
                    entity_type="part",
                    entity_id=str(part.id),
                    import_run_id=import_run.id,
                    source_row_id=source_row_record.id,
                    source_row=source_row_number,
                    original_values=part.raw_values,
                    conflicting_values={"existing_manufacturer": existing_brand, "incoming_manufacturer": brand, "incoming_raw": raw},
                    severity="high",
                    suggested_resolution="Review source evidence before deciding whether these are distinct manufacturer-specific records or a catalog conflict.",
                    evidence={"part_number": part_number, "normalized_part_number": normalized_part_number},
                )
        else:
            part = Part(
                manufacturer_id=manufacturer.id if manufacturer else None,
                part_number=part_number,
                normalized_part_number=normalized_part_number,
                description=description,
                natural_description=natural_description,
                verification_status="source_imported_unverified",
                data_origin="normalized_spreadsheet_import",
                raw_values=raw,
                provenance=provenance,
            )
            db.add(part)
            db.flush()
            report.inserted += 1
            source_row_record.row_status = "inserted"
        source_row_record.part_id = part.id
        if manufacturer and part.manufacturer_id != manufacturer.id and not source_row_record.row_status == "ambiguous":
            part.manufacturer_id = manufacturer.id

        if alternate:
            normalized_alias = normalize_key(alternate)
            if normalized_alias:
                existing_alias = db.scalar(
                    select(PartAlias).where(
                        PartAlias.part_id == part.id,
                        PartAlias.normalized_alias == normalized_alias,
                        PartAlias.alias_type == "alternate",
                    )
                )
                if not existing_alias:
                    db.add(
                        PartAlias(
                            part_id=part.id,
                            alias=alternate,
                            normalized_alias=normalized_alias,
                            alias_type="alternate",
                        )
                    )

        if model:
            existing_compatibility = db.scalar(
                select(PartModelCompatibility).where(
                    PartModelCompatibility.part_id == part.id,
                    PartModelCompatibility.model_id == model.id,
                    PartModelCompatibility.configuration_id.is_(None),
                )
            )
            if not existing_compatibility:
                db.add(PartModelCompatibility(part_id=part.id, model_id=model.id, evidence_id=evidence.id))

        if not brand:
            _create_or_update_issue(
                db,
                issue_type="missing_manufacturer",
                entity_type="part",
                entity_id=str(part.id),
                import_run_id=import_run.id,
                source_row_id=source_row_record.id,
                source_row=source_row_number,
                original_values=raw,
                conflicting_values=None,
                severity="medium",
                suggested_resolution="Add manufacturer from source evidence before treating compatibility as confirmed.",
                evidence={"part_number": part_number},
            )
        if MODEL_LIKE_PART_NUMBER.match(part_number or "") and equipment and normalize_label(part_number) in normalize_label(equipment):
            _create_or_update_issue(
                db,
                issue_type="suspected_model_number_as_part_number",
                entity_type="part",
                entity_id=str(part.id),
                import_run_id=import_run.id,
                source_row_id=source_row_record.id,
                source_row=source_row_number,
                original_values=raw,
                conflicting_values={"equipment_model": equipment, "part_number": part_number},
                severity="medium",
                suggested_resolution="Review whether the source row placed an equipment model in the part-number field.",
                evidence={"part_number": part_number, "equipment_model": equipment},
            )
        if alternate and normalize_key(alternate) == normalized_part_number:
            _create_or_update_issue(
                db,
                issue_type="orphan_or_redundant_alias",
                entity_type="part_alias",
                entity_id=str(part.id),
                import_run_id=import_run.id,
                source_row_id=source_row_record.id,
                source_row=source_row_number,
                original_values=raw,
                conflicting_values={"alternate_part_number": alternate},
                severity="low",
                suggested_resolution="Review whether the alternate part number is a true alias or duplicate entry.",
                evidence={"part_number": part_number},
            )

    import_run.inserted_count = report.inserted
    import_run.updated_count = report.updated
    import_run.skipped_count = report.skipped
    import_run.ambiguous_count = report.ambiguous
    import_run.rejected_count = report.rejected
    import_run.changed_count = report.changed
    import_run.summary = report.as_dict()
    db.add(
        AuditEvent(
            action="parts_spreadsheet_import",
            entity_type="parts",
            entity_id=str(import_run.id),
            details=report.as_dict(),
        )
    )
    db.commit()
    return report


def list_import_runs(db: Session) -> list[dict[str, Any]]:
    runs = db.scalars(select(ImportRun).order_by(ImportRun.id.desc())).all()
    return [
        {
            "id": run.id,
            "created_at": run.created_at.isoformat(),
            "source_name": run.source_name,
            "source_sha1": run.source_sha1,
            "status": run.status.value,
            "inserted": run.inserted_count,
            "updated": run.updated_count,
            "skipped": run.skipped_count,
            "ambiguous": run.ambiguous_count,
            "rejected": run.rejected_count,
            "changed": run.changed_count,
        }
        for run in runs
    ]


def list_data_quality_issues(db: Session, status: str | None = None, issue_type: str | None = None) -> list[dict[str, Any]]:
    stmt = select(DataQualityIssue).order_by(DataQualityIssue.id.desc())
    if status:
        stmt = stmt.where(DataQualityIssue.status == DataQualityIssueStatus(status))
    if issue_type:
        stmt = stmt.where(DataQualityIssue.issue_type == issue_type)
    issues = db.scalars(stmt).all()
    rows_by_id = {
        row.id: row
        for row in db.scalars(
            select(ImportSourceRow).where(ImportSourceRow.id.in_([i.source_row_id for i in issues if i.source_row_id]))
        ).all()
    } if issues else {}
    return [
        {
            "id": issue.id,
            "created_at": issue.created_at.isoformat(),
            "updated_at": issue.updated_at.isoformat(),
            "issue_type": issue.issue_type,
            "entity_type": issue.entity_type,
            "entity_id": issue.entity_id,
            "source_import_id": issue.source_import_id,
            "source_row": issue.source_row,
            "severity": issue.severity,
            "status": issue.status.value,
            "suggested_resolution": issue.suggested_resolution,
            "resolution_selected": issue.resolution_selected,
            "resolution_notes": issue.resolution_notes,
            "resolved_by": issue.resolved_by,
            "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None,
            "original_values": issue.original_values,
            "conflicting_values": issue.conflicting_values,
            "evidence": issue.evidence,
            "audit_history": issue.audit_history or [],
            "source_row_values": rows_by_id.get(issue.source_row_id).raw_values if issue.source_row_id in rows_by_id else None,
            "normalized_values": rows_by_id.get(issue.source_row_id).normalized_values if issue.source_row_id in rows_by_id else None,
        }
        for issue in issues
    ]


def resolve_data_quality_issue(
    db: Session,
    issue_id: int,
    *,
    status: DataQualityIssueStatus,
    resolution_selected: str,
    resolution_notes: str,
    resolved_by: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue = db.get(DataQualityIssue, issue_id)
    if not issue:
        raise ValueError("issue_not_found")
    if status == DataQualityIssueStatus.merged:
        raise ValueError("merge_preview_required")
    applied_change = _apply_resolution_to_catalog(
        db,
        issue,
        resolution_selected=resolution_selected,
        resolution_notes=resolution_notes,
        evidence=evidence or {},
    )
    now = datetime.utcnow()
    issue.status = status
    issue.resolution_selected = resolution_selected
    issue.resolution_notes = resolution_notes
    issue.resolved_by = resolved_by
    issue.resolved_at = now
    issue.evidence = {**(issue.evidence or {}), **(evidence or {})}
    history = list(issue.audit_history or [])
    history.append(
        {
            "at": now.isoformat(),
            "action": "resolved",
            "status": status.value,
            "resolution_selected": resolution_selected,
            "resolved_by": resolved_by,
            "notes": resolution_notes,
            "applied_change": applied_change,
        }
    )
    issue.audit_history = history
    db.add(AuditEvent(actor=resolved_by, action="data_quality_issue_resolved", entity_type="data_quality_issue", entity_id=str(issue.id), details=history[-1]))
    db.commit()
    return next(item for item in list_data_quality_issues(db, status=status.value) if item["id"] == issue_id)


def _apply_resolution_to_catalog(
    db: Session,
    issue: DataQualityIssue,
    *,
    resolution_selected: str,
    resolution_notes: str,
    evidence: dict[str, Any],
) -> dict[str, Any] | None:
    if issue.entity_type != "part" or not issue.entity_id:
        return None
    part = db.get(Part, int(issue.entity_id))
    if not part:
        return None
    if resolution_selected in {"accepted_as_distinct", "ignored_with_reason", "note_only"}:
        return None
    if resolution_selected == "canonical_description":
        value = clean_text(evidence.get("canonical_description") or evidence.get("canonical_value") or resolution_notes)
        if not value:
            raise ValueError("missing_canonical_description")
        before = part.description
        part.description = value
        part.verification_status = "administrator_resolved"
        part.provenance = {**(part.provenance or {}), "resolution_issue_id": issue.id}
        return {"field": "description", "before": before, "after": value}
    if resolution_selected == "canonical_part_number":
        value = clean_text(evidence.get("canonical_part_number") or evidence.get("canonical_value"))
        normalized = normalize_key(value)
        if not value or not normalized:
            raise ValueError("missing_canonical_part_number")
        existing = db.scalar(
            select(Part).where(
                (Part.normalized_part_number == normalized) | (Part.part_number == value),
                Part.id != part.id,
            )
        )
        if existing and existing.manufacturer_id != part.manufacturer_id:
            raise ValueError("cross_manufacturer_merge_forbidden")
        before = part.part_number
        part.part_number = value
        part.normalized_part_number = normalized
        part.verification_status = "administrator_resolved"
        return {"field": "part_number", "before": before, "after": value}
    if resolution_selected == "add_alias":
        value = clean_text(evidence.get("alias") or evidence.get("canonical_value"))
        normalized = normalize_key(value)
        if not value or not normalized:
            raise ValueError("missing_alias")
        existing = db.scalar(
            select(PartAlias).where(
                PartAlias.part_id == part.id,
                PartAlias.normalized_alias == normalized,
                PartAlias.alias_type == "reviewed_alias",
            )
        )
        if not existing:
            db.add(PartAlias(part_id=part.id, alias=value, normalized_alias=normalized, alias_type="reviewed_alias"))
        part.verification_status = "administrator_resolved"
        return {"field": "alias", "after": value}
    return None


def preview_merge_resolution(db: Session, issue_id: int, target_part_id: int) -> dict[str, Any]:
    issue = db.get(DataQualityIssue, issue_id)
    if not issue or issue.entity_type != "part" or not issue.entity_id:
        raise ValueError("issue_not_found")
    source = db.get(Part, int(issue.entity_id))
    target = db.get(Part, target_part_id)
    if not source or not target:
        raise ValueError("part_not_found")
    if source.manufacturer_id and target.manufacturer_id and source.manufacturer_id != target.manufacturer_id:
        raise ValueError("cross_manufacturer_merge_forbidden")
    return {
        "ok": True,
        "allowed": True,
        "source_part": {"id": source.id, "part_number": source.part_number, "manufacturer_id": source.manufacturer_id},
        "target_part": {"id": target.id, "part_number": target.part_number, "manufacturer_id": target.manufacturer_id},
        "would_preserve_source_rows": True,
        "would_move_aliases": True,
        "requires_explicit_followup": True,
    }


def validate_supersession(db: Session, old_part_id: int, new_part_id: int) -> None:
    if old_part_id == new_part_id:
        raise ValueError("supersession_loop_forbidden")
    seen = {old_part_id}
    current = new_part_id
    while current:
        if current in seen:
            raise ValueError("supersession_loop_forbidden")
        seen.add(current)
        link = db.scalar(select(PartSupersession).where(PartSupersession.old_part_id == current))
        current = link.new_part_id if link else None


def export_issues(issues: list[dict[str, Any]], fmt: str) -> str:
    if fmt == "json":
        return json.dumps({"issues": issues}, indent=2, sort_keys=True)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "issue_type", "entity_type", "entity_id", "source_import_id", "source_row", "severity", "status", "suggested_resolution"])
    writer.writeheader()
    for issue in issues:
        writer.writerow({key: issue.get(key) for key in writer.fieldnames})
    return output.getvalue()
