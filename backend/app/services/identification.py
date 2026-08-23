import hashlib
import io
import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    IdentificationCandidate,
    IdentificationCase,
    IdentificationConfirmation,
    IdentificationInput,
    IdentificationStatus,
    SourceEvidence,
    SourceType,
)
from app.services.catalog_query import CatalogSearchParams, search_catalog
from app.services.image_index import embed_pil, image_index, read_validated_image_upload
from app.services.normalization import clean_text, normalize_key


PART_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9-]{2,}")


@dataclass
class CaseInput:
    manufacturer: str
    equipment_family: str | None = None
    equipment_model: str | None = None
    description: str | None = None
    visible_markings: str | None = None
    component_location: str | None = None
    opened_by: str | None = None
    top_k: int = 5


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {token.lower() for token in PART_TOKEN.findall(text.upper())}


def _safe_contains(haystack: str | None, needle: str | None) -> bool:
    h = (haystack or "").lower()
    n = (needle or "").lower().strip()
    return bool(n and n in h)


def _ocr_image(_raw: bytes) -> dict[str, Any]:
    try:
        import pytesseract
    except Exception:
        return {"available": False, "text": "", "method": None, "message": "OCR engine not installed."}
    try:
        text = pytesseract.image_to_string(Image.open(io.BytesIO(_raw))).strip()
        return {"available": True, "text": text, "method": "pytesseract", "message": ""}
    except Exception as exc:
        return {"available": False, "text": "", "method": "pytesseract", "message": str(exc)}


def _score_catalog_result(row: dict[str, Any], case_input: CaseInput, query_tokens: set[str], image_scores: dict[str, float]) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
    score = 0.0
    factors: list[dict[str, Any]] = list(row.get("match_factors") or [])
    contradictions: list[dict[str, Any]] = list(row.get("contradicting_evidence") or [])

    brand = clean_text(row.get("manufacturer") or row.get("brand"))
    family = clean_text(row.get("eq_category"))
    part_number = clean_text(row.get("part_number"))
    alternate = clean_text(row.get("alternate_pn"))
    aliases = [clean_text(alias.get("alias")) for alias in row.get("aliases", [])]
    description = clean_text(row.get("official_description") or row.get("description"))
    natural = clean_text(row.get("natural_description"))
    compatible_models = [model.get("model_name") for model in row.get("compatible_models", [])]

    if _safe_contains(brand, case_input.manufacturer) or _safe_contains(case_input.manufacturer, brand):
        score += 0.25
        factors.append({"type": "manufacturer", "detail": f"Manufacturer matches {brand}."})
    else:
        contradictions.append({"type": "manufacturer", "detail": f"Candidate manufacturer is {brand or 'unknown'}."})
        score -= 0.12

    if case_input.equipment_model:
        if any(_safe_contains(model, case_input.equipment_model) or _safe_contains(case_input.equipment_model, model) for model in compatible_models):
            score += 0.18
            factors.append({"type": "equipment_model", "detail": f"Equipment model matches {case_input.equipment_model}."})
        elif compatible_models:
            contradictions.append({"type": "equipment_model", "detail": f"Compatible models are {', '.join(filter(None, compatible_models))}."})
            score -= 0.08

    if case_input.equipment_family:
        if _safe_contains(family, case_input.equipment_family) or _safe_contains(case_input.equipment_family, family):
            score += 0.08
            factors.append({"type": "equipment_family", "detail": f"Equipment family matches {family}."})

    row_text = " ".join([part_number or "", alternate or "", " ".join(filter(None, aliases)), description or "", natural or ""]).lower()
    matched_tokens = [token for token in query_tokens if token and token in row_text]
    if matched_tokens:
        token_score = min(0.35, 0.08 * len(matched_tokens))
        score += token_score
        factors.append({"type": "text_or_ocr", "detail": f"Matched tokens: {', '.join(sorted(matched_tokens))}."})
    normalized_part = normalize_key(part_number)
    normalized_aliases = {normalize_key(alias) for alias in aliases + [alternate]}
    exact_marking_hits = [
        token for token in query_tokens if token and token in ({normalized_part} | {alias for alias in normalized_aliases if alias})
    ]
    if exact_marking_hits:
        score += 0.45
        factors.append({"type": "part_number_marking", "detail": "Visible marking matches a known part or alternate number."})

    if normalized_part and normalized_part in image_scores:
        image_score = image_scores[normalized_part]
        score += min(0.18, max(0.0, image_score) * 0.18)
        factors.append({"type": "image_similarity", "detail": f"Visual similarity score {image_score:.3f}; candidate only."})

    return max(0.0, min(score, 1.0)), factors, contradictions


def _confidence_level(score: float, contradictions: list[dict[str, Any]]) -> str:
    if contradictions and score < 0.55:
        return "uncertain"
    if score >= 0.72:
        return "probable"
    if score >= 0.4:
        return "possible"
    return "low"


def _candidate_snapshot(row: dict[str, Any], score: float, level: str, factors, contradictions, evidence_id: int | None) -> dict[str, Any]:
    evidence = list(row.get("source_evidence") or [])
    if evidence_id:
        evidence.append({"source_type": "system", "source": "normalized catalog retrieval", "evidence_id": evidence_id})
    return {
        "normalized_part_id": row.get("normalized_part_id"),
        "part_name": row.get("natural_description") or row.get("description"),
        "official_part_number": row.get("part_number"),
        "official_description": row.get("official_description") or row.get("description"),
        "manufacturer": row.get("manufacturer") or row.get("brand"),
        "manufacturer_id": row.get("manufacturer_id"),
        "aliases": row.get("aliases") or [],
        "compatible_equipment_models": [model.get("model_name") for model in row.get("compatible_models", []) if clean_text(model.get("model_name"))],
        "compatibility_limitations": row.get("compatibility_limitations") or [],
        "replacement_or_superseding_part": row.get("supersession"),
        "supporting_images": [],
        "source_evidence": evidence,
        "match_factors": factors,
        "contradicting_evidence": contradictions,
        "confidence_score": round(score, 3),
        "confidence_level": level,
        "verification_status": "verified_catalog_record" if row.get("verification_status") in {"administrator_resolved", "engineer_verified"} else "candidate",
        "catalog_verification_status": row.get("verification_status"),
        "data_origin": row.get("data_origin"),
        "legacy_fallback_used": row.get("legacy_fallback_used", False),
        "commercial_lookup_status": "not_configured",
    }


async def create_identification_case(db: Session, case_input: CaseInput, files: list[UploadFile]) -> dict[str, Any]:
    if not clean_text(case_input.manufacturer):
        raise HTTPException(422, "Manufacturer is required.")
    if not files:
        raise HTTPException(422, "At least one image is required.")

    case = IdentificationCase(
        status=IdentificationStatus.insufficient_evidence,
        manufacturer_text=case_input.manufacturer,
        equipment_family_text=case_input.equipment_family,
        equipment_model_text=case_input.equipment_model,
        description=case_input.description,
        visible_markings=case_input.visible_markings,
        component_location=case_input.component_location,
        opened_by=case_input.opened_by,
    )
    db.add(case)
    db.flush()

    extracted_texts = []
    image_scores: dict[str, float] = {}
    for file in files:
        raw = await read_validated_image_upload(file)
        sha1 = hashlib.sha1(raw).hexdigest()
        ocr = _ocr_image(raw)
        if ocr.get("text"):
            extracted_texts.append(ocr["text"])
        db.add(IdentificationInput(case_id=case.id, input_type="image", file_path=file.filename, sha1=sha1))
        if image_index.M is not None and image_index.M.shape[0] > 0:
            q = embed_pil(Image.open(io.BytesIO(raw)))
            for match in image_index.topk(q, case_input.top_k):
                key = normalize_key(str(match["id"]))
                if key:
                    image_scores[key] = max(image_scores.get(key, 0.0), float(match["score"]))

    text_inputs = {
        "manufacturer": case_input.manufacturer,
        "equipment_family": case_input.equipment_family,
        "equipment_model": case_input.equipment_model,
        "description": case_input.description,
        "visible_markings": case_input.visible_markings,
        "component_location": case_input.component_location,
        "ocr_text": "\n".join(extracted_texts),
    }
    for key, value in text_inputs.items():
        if clean_text(value):
            db.add(IdentificationInput(case_id=case.id, input_type=key, value=clean_text(value)))

    query_tokens = set()
    for value in text_inputs.values():
        query_tokens |= _tokens(value)

    catalog_query = " ".join(filter(None, [case_input.visible_markings, case_input.description, " ".join(extracted_texts)]))
    catalog_response = search_catalog(
        db,
        CatalogSearchParams(
            q=catalog_query,
            manufacturer=case_input.manufacturer,
            equipment_family=case_input.equipment_family,
            equipment_model=case_input.equipment_model,
            limit=max(case_input.top_k * 3, case_input.top_k),
            enable_legacy_fallback=False,
        ),
    )
    rows = catalog_response["results"]
    scored = []
    for row in rows:
        score, factors, contradictions = _score_catalog_result(row, case_input, query_tokens, image_scores)
        if score > 0:
            scored.append((score, row, factors, contradictions))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[: case_input.top_k]

    responses = []
    for score, row, factors, contradictions in selected:
        evidence = SourceEvidence(
            source_type=SourceType.spreadsheet,
            internal_reference=f"normalized part {row.get('normalized_part_id')}",
            extraction_method="normalized_catalog_structured_text_ocr_image_candidate_retrieval",
            confidence=round(score, 3),
            notes="Normalized catalog candidate evidence only; engineer confirmation required.",
        )
        db.add(evidence)
        db.flush()
        level = _confidence_level(score, contradictions)
        snapshot = _candidate_snapshot(row, score, level, factors, contradictions, evidence.id)
        candidate = IdentificationCandidate(
            case_id=case.id,
            status=IdentificationStatus.candidate if level != "probable" else IdentificationStatus.probable_match,
            score=round(score, 3),
            confidence_level=level,
            method="normalized_catalog_structured_text_ocr_image_similarity",
            match_factors={"items": factors},
            contradicting_evidence={"items": contradictions},
            candidate_snapshot=snapshot,
            evidence_id=evidence.id,
            part_id=row.get("normalized_part_id"),
        )
        db.add(candidate)
        db.flush()
        snapshot["candidate_id"] = candidate.id
        snapshot["verification_status"] = candidate.status.value
        responses.append(snapshot)

    if not responses:
        message = "No supported candidate match was found from the current evidence."
        questions = ["Can you add a clearer label photo or visible part number?", "Can you provide the equipment model?"]
    else:
        message = "Candidates are ranked by supported evidence. None are engineer-confirmed yet."
        questions = _follow_up_questions(case_input, responses)

    db.add(
        AuditEvent(
            actor=case_input.opened_by,
            action="identification_case_created",
            entity_type="identification_case",
            entity_id=str(case.id),
            details={"candidate_count": len(responses), "ocr_text_found": bool(extracted_texts)},
        )
    )
    db.commit()
    return {
        "ok": True,
        "case_id": case.id,
        "status": case.status.value,
        "ocr": {
            "available": bool(extracted_texts),
            "text": "\n".join(extracted_texts),
            "message": "OCR text extracted." if extracted_texts else "No OCR text extracted or OCR engine unavailable.",
        },
        "candidates": responses,
        "follow_up_questions": questions,
        "message": message,
    }


def _follow_up_questions(case_input: CaseInput, candidates: list[dict[str, Any]]) -> list[str]:
    questions = []
    if not clean_text(case_input.equipment_model):
        questions.append("Which equipment model or module was the part removed from?")
    if not clean_text(case_input.visible_markings):
        questions.append("Are there visible label markings, barcodes, or partial numbers on the part?")
    if candidates and candidates[0]["confidence_level"] in {"low", "uncertain"}:
        questions.append("Can you upload a sharper close-up of the label or connector side?")
    return questions[:3]


def record_candidate_action(db: Session, case_id: int, candidate_id: int, action: str, user: str, notes: str | None) -> dict[str, Any]:
    candidate = db.get(IdentificationCandidate, candidate_id)
    if not candidate or candidate.case_id != case_id:
        raise HTTPException(404, "Candidate not found for this case.")
    status_map = {
        "confirm": IdentificationStatus.verified_match,
        "reject": IdentificationStatus.rejected_candidate,
        "uncertain": IdentificationStatus.insufficient_evidence,
    }
    new_status = status_map[action]
    evidence = SourceEvidence(
        source_type=SourceType.engineer,
        extraction_method="engineer_feedback",
        verified_by=user,
        confidence=1.0 if action == "confirm" else None,
        notes=notes,
    )
    db.add(evidence)
    db.flush()
    candidate.status = new_status
    db.add(
        IdentificationConfirmation(
            candidate_id=candidate.id,
            status=new_status,
            confirmed_by=user,
            evidence_id=evidence.id,
            notes=notes,
        )
    )
    db.add(
        AuditEvent(
            actor=user,
            action=f"candidate_{action}",
            entity_type="identification_candidate",
            entity_id=str(candidate.id),
            details={"case_id": case_id, "status": new_status.value, "notes": notes},
        )
    )
    db.commit()
    return {"ok": True, "case_id": case_id, "candidate_id": candidate_id, "status": new_status.value}
