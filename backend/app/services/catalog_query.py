from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    EquipmentModel,
    Manufacturer,
    Part,
    PartAlias,
    PartModelCompatibility,
    PartSupersession,
    SourceEvidence,
)
from app.services import legacy_search
from app.services.normalization import clean_text, normalize_key, normalize_label


@dataclass
class CatalogSearchParams:
    q: str = ""
    manufacturer: str | None = None
    equipment_family: str | None = None
    equipment_model: str | None = None
    include_inactive: bool = False
    include_superseded: bool = True
    limit: int = 20
    offset: int = 0
    enable_legacy_fallback: bool = False


def _text_blob(part: Part, aliases: list[PartAlias]) -> str:
    return " ".join(
        filter(
            None,
            [
                part.part_number,
                part.normalized_part_number,
                part.description,
                part.natural_description,
                " ".join(alias.alias for alias in aliases),
            ],
        )
    ).lower()


def _model_payload(db: Session, part: Part) -> tuple[list[dict[str, Any]], list[PartModelCompatibility]]:
    rows = db.execute(
        select(PartModelCompatibility, EquipmentModel, Manufacturer)
        .join(EquipmentModel, PartModelCompatibility.model_id == EquipmentModel.id)
        .join(Manufacturer, EquipmentModel.manufacturer_id == Manufacturer.id, isouter=True)
        .where(PartModelCompatibility.part_id == part.id)
    ).all()
    models = []
    compat = []
    for link, model, manufacturer in rows:
        compat.append(link)
        models.append(
            {
                "id": model.id,
                "model_name": model.model_name,
                "family_id": model.family_id,
                "manufacturer_id": model.manufacturer_id,
                "manufacturer": manufacturer.name if manufacturer else None,
                "category": model.category,
                "limitations": {
                    "configuration_id": link.configuration_id,
                    "serial_range": link.serial_range,
                    "hardware_version": link.hardware_version,
                    "software_version": link.software_version,
                    "region": link.region,
                },
            }
        )
    return models, compat


def _supersession_payload(db: Session, part: Part) -> dict[str, Any]:
    replacements = db.execute(
        select(PartSupersession, Part)
        .join(Part, PartSupersession.new_part_id == Part.id)
        .where(PartSupersession.old_part_id == part.id)
    ).all()
    supersedes = db.execute(
        select(PartSupersession, Part)
        .join(Part, PartSupersession.old_part_id == Part.id)
        .where(PartSupersession.new_part_id == part.id)
    ).all()
    return {
        "is_superseded": bool(replacements),
        "replacements": [
            {"part_id": new.id, "part_number": new.part_number, "relationship_type": link.relationship_type}
            for link, new in replacements
        ],
        "supersedes": [
            {"part_id": old.id, "part_number": old.part_number, "relationship_type": link.relationship_type}
            for link, old in supersedes
        ],
    }


def _source_evidence(db: Session, part: Part, compat: list[PartModelCompatibility]) -> list[dict[str, Any]]:
    ids = {part.provenance.get("evidence_id") for part in [part] if isinstance(part.provenance, dict)}
    ids |= {link.evidence_id for link in compat if link.evidence_id}
    ids = {item for item in ids if item}
    if not ids:
        return []
    evidence_rows = db.scalars(select(SourceEvidence).where(SourceEvidence.id.in_(ids))).all()
    return [
        {
            "evidence_id": evidence.id,
            "source_type": evidence.source_type.value,
            "internal_reference": evidence.internal_reference,
            "extraction_method": evidence.extraction_method,
            "confidence": evidence.confidence,
            "verified_by": evidence.verified_by,
            "verified_at": evidence.verified_at.isoformat() if evidence.verified_at else None,
        }
        for evidence in evidence_rows
    ]


def _score_part(
    part: Part,
    aliases: list[PartAlias],
    models: list[dict[str, Any]],
    params: CatalogSearchParams,
) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
    query = clean_text(params.q) or ""
    normalized_query = normalize_key(query)
    query_lower = query.lower()
    normalized_tokens = {normalize_key(token) for token in query.replace("/", " ").split()}
    normalized_tokens = {token for token in normalized_tokens if token}
    score = 0.0
    factors: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    alias_norms = {alias.normalized_alias for alias in aliases}
    if query and part.part_number.lower() == query_lower:
        score += 100
        factors.append({"type": "exact_official_part_number", "detail": "Exact official part number match."})
    if normalized_query and normalized_query in alias_norms:
        score += 92
        factors.append({"type": "exact_alias", "detail": "Exact alias or alternate part number match."})
    if normalized_query and part.normalized_part_number == normalized_query:
        score += 88
        factors.append({"type": "normalized_exact_part_number", "detail": "Normalized official part number match."})
    if part.normalized_part_number in normalized_tokens:
        score += 86
        factors.append({"type": "part_number_token", "detail": "A token in the query exactly matches the normalized part number."})
    if alias_norms & normalized_tokens:
        score += 84
        factors.append({"type": "alias_token", "detail": "A token in the query exactly matches an alias or alternate part number."})
    if normalized_query and part.normalized_part_number.startswith(normalized_query):
        score += 70
        factors.append({"type": "prefix_part_number", "detail": "Part number starts with the query."})
    elif normalized_query and normalized_query in part.normalized_part_number:
        score += 55
        factors.append({"type": "partial_part_number", "detail": "Part number contains the query."})

    blob = _text_blob(part, aliases)
    if query_lower and query_lower in blob:
        score += 30
        factors.append({"type": "description_text", "detail": "Query appears in catalog text."})
    else:
        tokens = [token for token in query_lower.split() if len(token) >= 3]
        matched = [token for token in tokens if token in blob]
        if matched:
            score += min(25, 8 * len(matched))
            factors.append({"type": "description_tokens", "detail": f"Matched tokens: {', '.join(matched)}."})

    manufacturer = part.manufacturer.name if part.manufacturer else clean_text((part.raw_values or {}).get("Brand"))
    if params.manufacturer:
        if normalize_label(manufacturer) == normalize_label(params.manufacturer):
            score += 20
            factors.append({"type": "manufacturer", "detail": f"Manufacturer matches {manufacturer}."})
        else:
            score -= 40
            conflicts.append({"type": "manufacturer", "detail": f"Catalog manufacturer is {manufacturer or 'unknown'}."})

    if params.equipment_model:
        requested_model_id = int(params.equipment_model) if str(params.equipment_model).isdigit() else None
        wanted = normalize_label(params.equipment_model)
        compatible = [model for model in models if model.get("id") == requested_model_id or normalize_label(model["model_name"]) == wanted]
        if compatible:
            score += 30
            factors.append({"type": "equipment_model", "detail": f"Compatible with {params.equipment_model}."})
        elif models:
            score -= 35
            conflicts.append({"type": "equipment_model", "detail": "Part has compatibility records, but not for the requested model."})

    if params.equipment_family:
        requested_family_id = int(params.equipment_family) if str(params.equipment_family).isdigit() else None
        wanted_family = normalize_label(params.equipment_family)
        family_match = any(model.get("family_id") == requested_family_id or normalize_label(model.get("category")) == wanted_family for model in models)
        if family_match:
            score += 12
            factors.append({"type": "equipment_family", "detail": f"Equipment family/category matches {params.equipment_family}."})

    return max(score, 0.0), factors, conflicts


def _result(db: Session, part: Part, score: float, factors, conflicts, legacy_fallback_used: bool = False) -> dict[str, Any]:
    aliases = db.scalars(select(PartAlias).where(PartAlias.part_id == part.id, PartAlias.is_active.is_(True))).all()
    models, compat = _model_payload(db, part)
    supersession = _supersession_payload(db, part)
    manufacturer = part.manufacturer.name if part.manufacturer else clean_text((part.raw_values or {}).get("Brand"))
    evidence = _source_evidence(db, part, compat)
    return {
        "id": part.id,
        "normalized_part_id": part.id,
        "part_number": part.part_number,
        "alternate_pn": aliases[0].alias if aliases else None,
        "aliases": [{"id": alias.id, "alias": alias.alias, "alias_type": alias.alias_type} for alias in aliases],
        "description": part.description,
        "official_description": part.description,
        "natural_description": part.natural_description,
        "brand": manufacturer,
        "manufacturer": manufacturer,
        "manufacturer_id": part.manufacturer_id,
        "equipment1": ", ".join(model["model_name"] for model in models) or None,
        "eq_category": ", ".join(sorted({model["category"] for model in models if model["category"]})) or None,
        "compatible_models": models,
        "compatibility_limitations": [model["limitations"] for model in models if any(model["limitations"].values())],
        "supersession": supersession,
        "verification_status": part.verification_status,
        "source_evidence": evidence,
        "data_origin": part.data_origin,
        "legacy_fallback_used": legacy_fallback_used,
        "rank_score": round(score, 3),
        "match_factors": factors,
        "contradicting_evidence": conflicts,
    }


def search_catalog(db: Session, params: CatalogSearchParams) -> dict[str, Any]:
    query = clean_text(params.q) or ""
    normalized_query = normalize_key(query)
    stmt = select(Part)
    if not params.include_inactive:
        stmt = stmt.where(Part.is_active.is_(True))
    if params.manufacturer:
        manufacturer_id = int(params.manufacturer) if str(params.manufacturer).isdigit() else None
        filters = [Manufacturer.normalized_name == normalize_label(params.manufacturer), Part.raw_values["Brand"].as_string() == params.manufacturer]
        if manufacturer_id is not None:
            filters.append(Part.manufacturer_id == manufacturer_id)
        stmt = stmt.join(Manufacturer, Part.manufacturer_id == Manufacturer.id, isouter=True).where(or_(*filters))
    parts = db.scalars(stmt).all()
    scored = []
    for part in parts:
        aliases = db.scalars(select(PartAlias).where(PartAlias.part_id == part.id, PartAlias.is_active.is_(True))).all()
        models, _compat = _model_payload(db, part)
        if normalized_query:
            blob = _text_blob(part, aliases)
            tokens = [token for token in query.lower().split() if len(token) >= 3]
            token_match = any(token in blob for token in tokens)
            if normalized_query not in part.normalized_part_number and query.lower() not in blob and normalized_query not in {a.normalized_alias for a in aliases} and not token_match:
                continue
        score, factors, conflicts = _score_part(part, aliases, models, params)
        if score > 0 or not query:
            scored.append((score, part, factors, conflicts))
    scored.sort(key=lambda item: (-item[0], item[1].part_number.lower(), item[1].id))
    page = scored[params.offset : params.offset + params.limit]
    results = [_result(db, part, score, factors, conflicts) for score, part, factors, conflicts in page]
    legacy_fallback_used = False
    if not results and params.enable_legacy_fallback and query:
        legacy_fallback_used = True
        db.add(AuditEvent(action="legacy_search_fallback_used", entity_type="legacy_parts", details={"query": query, "limit": params.limit, "offset": params.offset}))
        db.commit()
        results = [_legacy_result(row) for row in legacy_search.search_parts(query, params.limit, params.offset)]
    return {
        "ok": True,
        "count": len(results),
        "total": len(scored),
        "limit": params.limit,
        "offset": params.offset,
        "source": "legacy_fallback" if legacy_fallback_used else "normalized_catalog",
        "legacy_fallback_used": legacy_fallback_used,
        "results": results,
    }


def _legacy_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "normalized_part_id": None,
        "aliases": [{"id": None, "alias": row.get("alternate_pn"), "alias_type": "legacy_alternate"}] if row.get("alternate_pn") else [],
        "official_description": row.get("description"),
        "manufacturer": row.get("brand"),
        "manufacturer_id": None,
        "compatible_models": [{"id": None, "model_name": row.get("equipment1"), "category": row.get("eq_category")}],
        "compatibility_limitations": [],
        "supersession": {"is_superseded": False, "replacements": [], "supersedes": []},
        "verification_status": "legacy_unverified_fallback",
        "source_evidence": [{"source_type": "legacy_database", "internal_reference": f"parts.db row {row.get('id')}"}],
        "data_origin": "legacy_parts_db_fallback",
        "legacy_fallback_used": True,
        "rank_score": 0,
        "match_factors": [{"type": "legacy_fallback", "detail": "Returned only because explicit legacy fallback is enabled."}],
        "contradicting_evidence": [],
    }
