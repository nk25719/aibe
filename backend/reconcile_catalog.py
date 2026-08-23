import json

from sqlalchemy import select

from app.db.models import DataQualityIssue, ImportSourceRow, Part
from app.db.session import SessionLocal
from app.services.legacy_search import get_legacy_conn
from app.services.normalization import normalize_key, normalize_label


def main() -> None:
    with get_legacy_conn() as conn:
        legacy_rows = [dict(row) for row in conn.execute("SELECT rowid AS id, * FROM parts")]
    legacy_by_part = {}
    for row in legacy_rows:
        key = normalize_key(row.get("part_number"))
        if key:
            legacy_by_part.setdefault(key, []).append(row)

    with SessionLocal() as db:
        normalized = db.scalars(select(Part)).all()
        normalized_by_part = {part.normalized_part_number: part for part in normalized}
        missing_normalized = sorted(set(legacy_by_part) - set(normalized_by_part))
        only_normalized = sorted(set(normalized_by_part) - set(legacy_by_part))
        conflicts = []
        manufacturer_mismatches = []
        description_differences = []
        for key, rows in legacy_by_part.items():
            if len({row.get("description") for row in rows if row.get("description")}) > 1:
                conflicts.append({"part_number": rows[0].get("part_number"), "legacy_rows": [row["id"] for row in rows]})
            part = normalized_by_part.get(key)
            if not part:
                continue
            normalized_brand = normalize_label((part.raw_values or {}).get("Brand"))
            legacy_brands = {normalize_label(row.get("brand")) for row in rows if row.get("brand")}
            if normalized_brand and legacy_brands and normalized_brand not in legacy_brands:
                manufacturer_mismatches.append({"part_number": part.part_number, "normalized": normalized_brand, "legacy": sorted(legacy_brands)})
            legacy_descriptions = {row.get("description") for row in rows if row.get("description")}
            if part.description and legacy_descriptions and part.description not in legacy_descriptions:
                description_differences.append({"part_number": part.part_number, "normalized": part.description, "legacy": sorted(legacy_descriptions)})
        report = {
            "legacy_searchable_parts": len(legacy_by_part),
            "normalized_searchable_parts": len(normalized_by_part),
            "missing_normalized_records": missing_normalized[:100],
            "missing_normalized_count": len(missing_normalized),
            "normalized_only_records": only_normalized[:100],
            "normalized_only_count": len(only_normalized),
            "conflicting_part_numbers": conflicts,
            "manufacturer_mismatches": manufacturer_mismatches,
            "description_differences": description_differences,
            "records_available_only_through_fallback": missing_normalized[:100],
            "source_rows": db.query(ImportSourceRow).count(),
            "unresolved_ambiguity_count": db.query(DataQualityIssue).filter(DataQualityIssue.status == "open").count(),
            "note": "This report does not modify data. Review differences with source evidence before changing normalized records.",
        }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
