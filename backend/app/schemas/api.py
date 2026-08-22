from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    ok: Literal[False] = False
    error: str
    detail: Any | None = None


class HealthResponse(BaseModel):
    ok: Literal[True] = True
    service: str
    database_url: str
    legacy_parts_db: str
    image_index: dict[str, Any]


class SearchResult(BaseModel):
    id: int
    part_number: str | None = None
    alternate_pn: str | None = None
    description: str | None = None
    equipment1: str | None = None
    brand: str | None = None
    eq_category: str | None = None
    natural_description: str | None = None


class SearchResponse(BaseModel):
    ok: Literal[True] = True
    count: int
    limit: int
    offset: int
    results: list[SearchResult]


class ImageMatch(BaseModel):
    id: str
    score: float
    status: Literal["candidate"] = "candidate"
    confidence_semantics: str = "visual_similarity_only_not_verified"
    meta: dict[str, Any] | None = None


class ImageMatchResponse(BaseModel):
    ok: Literal[True] = True
    matches: list[ImageMatch]
    status: Literal["candidate"] = "candidate"
    warning: str = Field(
        default="Generic MobileNet similarity is not a verified biomedical part identification."
    )


class ImportReportResponse(BaseModel):
    ok: Literal[True] = True
    report: dict[str, Any]


class CatalogOption(BaseModel):
    value: str
    label: str


class CatalogResponse(BaseModel):
    ok: Literal[True] = True
    manufacturers: list[CatalogOption]
    equipment_models: list[CatalogOption]
    equipment_families: list[CatalogOption]


class IdentificationCandidateResponse(BaseModel):
    candidate_id: int
    part_name: str | None = None
    official_part_number: str | None = None
    official_description: str | None = None
    manufacturer: str | None = None
    compatible_equipment_models: list[str] = []
    replacement_or_superseding_part: str | None = None
    supporting_images: list[str] = []
    source_evidence: list[dict[str, Any]] = []
    match_factors: list[dict[str, Any]] = []
    contradicting_evidence: list[dict[str, Any]] = []
    confidence_score: float
    confidence_level: str
    verification_status: str
    commercial_lookup_status: str = "not_configured"


class IdentificationCaseResponse(BaseModel):
    ok: Literal[True] = True
    case_id: int
    status: str
    ocr: dict[str, Any]
    candidates: list[IdentificationCandidateResponse]
    follow_up_questions: list[str]
    message: str


class CandidateActionRequest(BaseModel):
    action: Literal["confirm", "reject", "uncertain"]
    user: str = Field(min_length=1, max_length=255)
    notes: str | None = None


class CandidateActionResponse(BaseModel):
    ok: Literal[True] = True
    case_id: int
    candidate_id: int
    status: str


class DocumentIngestRequest(BaseModel):
    path: str
    manufacturer: str = Field(min_length=1, max_length=255)
    equipment_model: str | None = None
    equipment_family: str | None = None
    document_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    document_number: str | None = None
    revision: str = Field(default="unknown", max_length=100)
    published_at: str | None = None
    effective_at: str | None = None
    language: str = "en"
    source: str | None = None
    access_classification: str = "internal"


class DocumentIngestResponse(BaseModel):
    ok: Literal[True] = True
    document_id: int
    document_version_id: int
    status: str
    checksum: str
    pages: int
    duplicate_of_version_id: int | None = None
    errors: list[str] = []


class TechnicalQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    manufacturer: str | None = None
    model: str | None = None
    include_historical: bool = False


class TechnicalQuestionResponse(BaseModel):
    ok: Literal[True] = True
    answer: str
    missing_information: list[str]
    evidence: list[dict[str, Any]]
    inferences: list[str]
    warnings: list[str]
    conflicts: list[dict[str, Any]]


class TroubleshootingRequest(BaseModel):
    manufacturer: str = Field(min_length=1, max_length=255)
    model: str | None = None
    serial: str | None = None
    configuration: str | None = None
    hardware_version: str | None = None
    software_version: str | None = None
    error_code: str | None = None
    symptom_description: str | None = None
    measurements: str | None = None
    operating_context: str | None = None
    actions_attempted: str | None = None
    service_history: str | None = None
    reviewed_by: str | None = None


class TroubleshootingResponse(BaseModel):
    ok: Literal[True] = True
    case_id: int
    problem_restatement: str
    missing_information: list[str]
    possible_causes: list[dict[str, Any]]
    safe_next_checks: list[str]
    required_measurements_tools: list[str]
    relevant_documents: list[dict[str, Any]]
    possible_parts: list[dict[str, Any]]
    stop_escalation_conditions: list[str]
    service_report_draft: str
    safety_notice: str
