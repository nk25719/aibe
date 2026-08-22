from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.db.models import (
    AuditEvent,
    EquipmentFamily,
    EquipmentModel,
    Manufacturer,
    ManufacturerAlias,
    Part,
    PartAlias,
    SourceEvidence,
    SourceType,
)
from app.services.normalization import clean_text, normalize_key, normalize_label


DEFAULT_PARTS_XLSX = BASE_DIR / "AIBE Parts list.xlsx"


@dataclass
class ImportReport:
    source_path: str
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    ambiguous: int = 0
    rejected: int = 0
    validation_errors: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "ambiguous": self.ambiguous,
            "rejected": self.rejected,
            "validation_errors": self.validation_errors,
        }


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
    report = ImportReport(source_path=str(source_path.resolve()))
    df = pd.read_excel(source_path)
    imported_at = datetime.utcnow().isoformat()

    for row_number, row in df.iterrows():
        raw = {str(k): clean_text(v) for k, v in row.to_dict().items()}
        part_number = clean_text(raw.get("part number"))
        normalized_part_number = normalize_key(part_number)
        if not part_number or not normalized_part_number:
            report.rejected += 1
            report.validation_errors.append({"row": int(row_number) + 2, "error": "missing_part_number", "raw": raw})
            continue

        brand = clean_text(raw.get("Brand"))
        equipment = clean_text(raw.get("Equipment1"))
        category = clean_text(raw.get("EQ category"))
        alternate = clean_text(raw.get("Alternate PN"))
        description = clean_text(raw.get("Description"))
        natural_description = clean_text(raw.get("Natural Description"))

        manufacturer = _get_or_create_manufacturer(db, brand, report)
        _get_or_create_model(db, equipment, category, manufacturer, report)

        evidence = SourceEvidence(
            source_type=SourceType.spreadsheet,
            internal_reference=f"{source_path.name}:row:{int(row_number) + 2}",
            extraction_method="pandas.read_excel",
            imported_at=datetime.utcnow(),
            confidence=0.6,
            notes="Imported from user-provided parts spreadsheet; relationships are not engineer verified.",
        )
        db.add(evidence)
        db.flush()

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
            if description and part.description and part.description != description:
                conflicting_fields.append("description")
            if natural_description and part.natural_description and part.natural_description != natural_description:
                conflicting_fields.append("natural_description")
            if conflicting_fields:
                report.ambiguous += 1
                report.validation_errors.append(
                    {
                        "row": int(row_number) + 2,
                        "error": "duplicate_part_conflicting_values",
                        "part_number": part_number,
                        "fields": conflicting_fields,
                    }
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
                else:
                    report.skipped += 1
        else:
            part = Part(
                part_number=part_number,
                normalized_part_number=normalized_part_number,
                description=description,
                natural_description=natural_description,
                raw_values=raw,
                provenance=provenance,
            )
            db.add(part)
            db.flush()
            report.inserted += 1

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

    db.add(
        AuditEvent(
            action="parts_spreadsheet_import",
            entity_type="parts",
            details=report.as_dict(),
        )
    )
    db.commit()
    return report
