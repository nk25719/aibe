from sqlalchemy.orm import Session

from app.db.models import AuditEvent, TroubleshootingCase
from app.services.documents import retrieve_chunks
from app.services.normalization import clean_text


def create_troubleshooting_case(db: Session, payload) -> dict:
    case = TroubleshootingCase(**payload.model_dump(exclude={"reviewed_by"}), status="draft")
    db.add(case)
    db.flush()
    missing = []
    for label in ["model", "serial", "configuration", "hardware_version", "software_version"]:
        if not clean_text(getattr(payload, label)):
            missing.append(label)
    query = " ".join(filter(None, [payload.error_code, payload.symptom_description, payload.actions_attempted]))
    hits = retrieve_chunks(db, query or "troubleshooting", payload.manufacturer, payload.model, limit=5)
    docs = [
        {"document_title": doc.title, "revision": version.revision, "page": chunk.page_number, "section": chunk.section}
        for _score, chunk, version, doc in hits
    ]
    causes = []
    for score, chunk, version, doc in hits[:3]:
        causes.append(
            {
                "cause": chunk.section or "Documented troubleshooting item",
                "rank_score": score,
                "evidence": [{"document_title": doc.title, "revision": version.revision, "page": chunk.page_number, "section": chunk.section}],
                "confidence": "source-supported-candidate",
            }
        )
    if not causes:
        causes.append({"cause": "Insufficient source evidence", "rank_score": 0, "evidence": [], "confidence": "unsupported"})
    response = {
        "ok": True,
        "case_id": case.id,
        "problem_restatement": f"{payload.manufacturer} {payload.model or 'unknown model'}: {payload.error_code or 'no error code'} - {payload.symptom_description or 'no symptom provided'}",
        "missing_information": missing,
        "possible_causes": causes,
        "safe_next_checks": [
            "Review manufacturer safety prerequisites before opening equipment.",
            "Verify the exact model, serial/configuration, and software/hardware version.",
            "Collect the measurements named in the cited troubleshooting material.",
        ],
        "required_measurements_tools": ["Manufacturer-specified service tools and calibrated measurement equipment from cited documents."],
        "relevant_documents": docs,
        "possible_parts": [],
        "stop_escalation_conditions": [
            "Stop if patient-connected operation, high voltage, gas delivery, radiation, or life-support safety is involved.",
            "Escalate when manufacturer documentation is missing, conflicting, or not applicable to the configuration.",
            "Do not infer patient-safe operation merely because an error disappeared.",
        ],
        "service_report_draft": "Engineer review required before final report. Include complaint, verified model/serial, cited documents, measurements, actions, and outcome.",
        "safety_notice": "AIBE is decision support, not an autonomous repair authority. Qualified review is required before diagnostics or repair.",
    }
    case.response_snapshot = response
    db.add(AuditEvent(actor=payload.reviewed_by, action="troubleshooting_response_created", entity_type="troubleshooting_case", entity_id=str(case.id), details={"query": query, "evidence_count": len(docs)}))
    db.commit()
    return response
