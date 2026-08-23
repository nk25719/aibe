import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class IdentificationStatus(str, enum.Enum):
    candidate = "candidate"
    probable_match = "probable_match"
    verified_match = "verified_match"
    rejected_candidate = "rejected_candidate"
    insufficient_evidence = "insufficient_evidence"


class SourceType(str, enum.Enum):
    spreadsheet = "spreadsheet"
    database = "database"
    document = "document"
    image = "image"
    engineer = "engineer"
    system = "system"
    url = "url"


class ImportRunStatus(str, enum.Enum):
    completed = "completed"
    failed = "failed"


class DataQualityIssueStatus(str, enum.Enum):
    open = "open"
    under_review = "under_review"
    resolved = "resolved"
    accepted_as_distinct = "accepted_as_distinct"
    merged = "merged"
    ignored_with_reason = "ignored_with_reason"


class Manufacturer(TimestampMixin, Base):
    __tablename__ = "manufacturers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    raw_name: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list["ManufacturerAlias"]] = relationship(back_populates="manufacturer", cascade="all, delete-orphan")
    families: Mapped[list["EquipmentFamily"]] = relationship(back_populates="manufacturer")
    models: Mapped[list["EquipmentModel"]] = relationship(back_populates="manufacturer")


class ManufacturerAlias(TimestampMixin, Base):
    __tablename__ = "manufacturer_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manufacturer_id: Mapped[int] = mapped_column(ForeignKey("manufacturers.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(255))
    manufacturer: Mapped[Manufacturer] = relationship(back_populates="aliases")
    __table_args__ = (UniqueConstraint("manufacturer_id", "normalized_alias", name="uq_manufacturer_alias"),)


class EquipmentFamily(TimestampMixin, Base):
    __tablename__ = "equipment_families"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    raw_name: Mapped[str | None] = mapped_column(String(255))
    manufacturer: Mapped[Manufacturer | None] = relationship(back_populates="families")
    models: Mapped[list["EquipmentModel"]] = relationship(back_populates="family")
    __table_args__ = (UniqueConstraint("manufacturer_id", "normalized_name", name="uq_equipment_family"),)


class EquipmentModel(TimestampMixin, Base):
    __tablename__ = "equipment_models"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    family_id: Mapped[int | None] = mapped_column(ForeignKey("equipment_families.id"), index=True)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_model_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    raw_name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(255), index=True)
    manufacturer: Mapped[Manufacturer | None] = relationship(back_populates="models")
    family: Mapped[EquipmentFamily | None] = relationship(back_populates="models")
    aliases: Mapped[list["EquipmentModelAlias"]] = relationship(back_populates="model", cascade="all, delete-orphan")
    configurations: Mapped[list["EquipmentConfiguration"]] = relationship(back_populates="model")
    __table_args__ = (UniqueConstraint("manufacturer_id", "normalized_model_name", name="uq_equipment_model"),)


class EquipmentModelAlias(TimestampMixin, Base):
    __tablename__ = "equipment_model_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("equipment_models.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[EquipmentModel] = relationship(back_populates="aliases")
    __table_args__ = (UniqueConstraint("model_id", "normalized_alias", name="uq_equipment_model_alias"),)


class EquipmentConfiguration(TimestampMixin, Base):
    __tablename__ = "equipment_configurations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("equipment_models.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    serial_range: Mapped[str | None] = mapped_column(String(255))
    hardware_version: Mapped[str | None] = mapped_column(String(255))
    software_version: Mapped[str | None] = mapped_column(String(255))
    region: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[EquipmentModel] = relationship(back_populates="configurations")


class Part(TimestampMixin, Base):
    __tablename__ = "parts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    part_number: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    normalized_part_number: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    natural_description: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(100), default="source_imported_unverified", nullable=False, index=True)
    data_origin: Mapped[str] = mapped_column(String(100), default="normalized_import", nullable=False, index=True)
    raw_values: Mapped[dict | None] = mapped_column(JSON)
    provenance: Mapped[dict | None] = mapped_column(JSON)
    manufacturer: Mapped[Manufacturer | None] = relationship()
    aliases: Mapped[list["PartAlias"]] = relationship(back_populates="part", cascade="all, delete-orphan")
    images: Mapped[list["PartImage"]] = relationship(back_populates="part")


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    source_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    source_sha1: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    importer_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ImportRunStatus] = mapped_column(Enum(ImportRunStatus), default=ImportRunStatus.completed, nullable=False)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ambiguous_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[dict | None] = mapped_column(JSON)


class ImportSourceRow(Base):
    __tablename__ = "import_source_rows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_run_id: Mapped[int] = mapped_column(ForeignKey("import_runs.id"), nullable=False, index=True)
    source_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    source_sha1: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    row_key: Mapped[str] = mapped_column(String(700), nullable=False, index=True)
    row_sha1: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_row_sha1: Mapped[str | None] = mapped_column(String(64))
    row_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255))
    raw_values: Mapped[dict] = mapped_column(JSON, nullable=False)
    normalized_values: Mapped[dict | None] = mapped_column(JSON)
    part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"), index=True)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("source_evidence.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("import_run_id", "source_row", name="uq_import_source_row_run_row"),)


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    issue_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source_import_id: Mapped[int | None] = mapped_column(ForeignKey("import_runs.id"), index=True)
    source_row_id: Mapped[int | None] = mapped_column(ForeignKey("import_source_rows.id"), index=True)
    source_row: Mapped[int | None] = mapped_column(Integer, index=True)
    original_values: Mapped[dict | None] = mapped_column(JSON)
    conflicting_values: Mapped[dict | None] = mapped_column(JSON)
    severity: Mapped[str] = mapped_column(String(50), default="medium", nullable=False, index=True)
    status: Mapped[DataQualityIssueStatus] = mapped_column(
        Enum(DataQualityIssueStatus), default=DataQualityIssueStatus.open, nullable=False, index=True
    )
    suggested_resolution: Mapped[str | None] = mapped_column(Text)
    resolution_selected: Mapped[str | None] = mapped_column(String(100))
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    evidence: Mapped[dict | None] = mapped_column(JSON)
    audit_history: Mapped[list | None] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)


class PartAlias(TimestampMixin, Base):
    __tablename__ = "part_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alias_type: Mapped[str] = mapped_column(String(50), default="alternate", nullable=False)
    part: Mapped[Part] = relationship(back_populates="aliases")
    __table_args__ = (UniqueConstraint("part_id", "normalized_alias", "alias_type", name="uq_part_alias"),)


class PartImage(TimestampMixin, Base):
    __tablename__ = "part_images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"), index=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    sha1: Mapped[str | None] = mapped_column(String(64), index=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    embedding_generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    part: Mapped[Part | None] = relationship(back_populates="images")


class PartModelCompatibility(TimestampMixin, Base):
    __tablename__ = "part_model_compatibility"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("equipment_models.id"), nullable=False, index=True)
    configuration_id: Mapped[int | None] = mapped_column(ForeignKey("equipment_configurations.id"), index=True)
    serial_range: Mapped[str | None] = mapped_column(String(255))
    hardware_version: Mapped[str | None] = mapped_column(String(255))
    software_version: Mapped[str | None] = mapped_column(String(255))
    region: Mapped[str | None] = mapped_column(String(255))
    effective_from: Mapped[Date | None] = mapped_column(Date)
    effective_to: Mapped[Date | None] = mapped_column(Date)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("source_evidence.id"), index=True)
    __table_args__ = (UniqueConstraint("part_id", "model_id", "configuration_id", name="uq_part_model_compatibility"),)


class PartSupersession(TimestampMixin, Base):
    __tablename__ = "part_supersessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    old_part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    new_part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    effective_date: Mapped[Date | None] = mapped_column(Date)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("source_evidence.id"), index=True)
    __table_args__ = (CheckConstraint("old_part_id != new_part_id", name="ck_supersession_distinct_parts"),)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    document_type: Mapped[str | None] = mapped_column(String(100))
    document_number: Mapped[str | None] = mapped_column(String(255), index=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    manufacturer_text: Mapped[str | None] = mapped_column(String(255), index=True)
    equipment_family_text: Mapped[str | None] = mapped_column(String(255), index=True)
    equipment_model_text: Mapped[str | None] = mapped_column(String(255), index=True)
    language: Mapped[str | None] = mapped_column(String(50))
    access_classification: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    internal_reference: Mapped[str | None] = mapped_column(String(500))
    ingestion_status: Mapped[str | None] = mapped_column(String(100), index=True)
    ingestion_errors: Mapped[dict | None] = mapped_column(JSON)


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "document_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    revision: Mapped[str] = mapped_column(String(100), nullable=False)
    published_at: Mapped[Date | None] = mapped_column(Date)
    effective_at: Mapped[Date | None] = mapped_column(Date)
    file_sha1: Mapped[str | None] = mapped_column(String(64))
    source_path: Mapped[str | None] = mapped_column(String(1000))
    duplicate_of_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), index=True)
    __table_args__ = (UniqueConstraint("document_id", "revision", name="uq_document_revision"),)


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), nullable=False, index=True)
    page_number: Mapped[int | None] = mapped_column(Integer)
    figure: Mapped[str | None] = mapped_column(String(100))
    section: Mapped[str | None] = mapped_column(String(255))
    text: Mapped[str | None] = mapped_column(Text)
    chunk_index: Mapped[int | None] = mapped_column(Integer)
    extraction_method: Mapped[str | None] = mapped_column(String(100))
    tables: Mapped[dict | None] = mapped_column(JSON)
    figure_refs: Mapped[dict | None] = mapped_column(JSON)
    search_text: Mapped[str | None] = mapped_column(Text)


class DocumentLink(TimestampMixin, Base):
    __tablename__ = "document_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), nullable=False, index=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("equipment_models.id"), index=True)
    part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"), index=True)
    technical_bulletin_id: Mapped[int | None] = mapped_column(ForeignKey("technical_bulletins.id"), index=True)
    lifecycle_notice_id: Mapped[int | None] = mapped_column(ForeignKey("lifecycle_notices.id"), index=True)
    link_type: Mapped[str] = mapped_column(String(100), nullable=False)


class TechnicalBulletin(TimestampMixin, Base):
    __tablename__ = "technical_bulletins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bulletin_number: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    effective_date: Mapped[Date | None] = mapped_column(Date)


class LifecycleNotice(TimestampMixin, Base):
    __tablename__ = "lifecycle_notices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("equipment_models.id"), index=True)
    part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"), index=True)
    effective_date: Mapped[Date | None] = mapped_column(Date)


class IdentificationCase(TimestampMixin, Base):
    __tablename__ = "identification_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[IdentificationStatus] = mapped_column(Enum(IdentificationStatus), default=IdentificationStatus.insufficient_evidence)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    equipment_model_id: Mapped[int | None] = mapped_column(ForeignKey("equipment_models.id"), index=True)
    manufacturer_text: Mapped[str | None] = mapped_column(String(255))
    equipment_family_text: Mapped[str | None] = mapped_column(String(255))
    equipment_model_text: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    visible_markings: Mapped[str | None] = mapped_column(Text)
    component_location: Mapped[str | None] = mapped_column(Text)
    opened_by: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)


class IdentificationInput(TimestampMixin, Base):
    __tablename__ = "identification_inputs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("identification_cases.id"), nullable=False, index=True)
    input_type: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String(500))
    sha1: Mapped[str | None] = mapped_column(String(64))


class IdentificationCandidate(TimestampMixin, Base):
    __tablename__ = "identification_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("identification_cases.id"), nullable=False, index=True)
    part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"), index=True)
    status: Mapped[IdentificationStatus] = mapped_column(Enum(IdentificationStatus), default=IdentificationStatus.candidate)
    score: Mapped[float | None] = mapped_column(Float)
    confidence_level: Mapped[str | None] = mapped_column(String(50))
    method: Mapped[str | None] = mapped_column(String(255))
    match_factors: Mapped[dict | None] = mapped_column(JSON)
    contradicting_evidence: Mapped[dict | None] = mapped_column(JSON)
    candidate_snapshot: Mapped[dict | None] = mapped_column(JSON)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("source_evidence.id"), index=True)


class IdentificationConfirmation(TimestampMixin, Base):
    __tablename__ = "identification_confirmations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("identification_candidates.id"), nullable=False, index=True)
    status: Mapped[IdentificationStatus] = mapped_column(Enum(IdentificationStatus), nullable=False)
    confirmed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("source_evidence.id"), index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class SourceEvidence(TimestampMixin, Base):
    __tablename__ = "source_evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), index=True)
    document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), index=True)
    page: Mapped[str | None] = mapped_column(String(100))
    figure: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    internal_reference: Mapped[str | None] = mapped_column(String(500))
    extraction_method: Mapped[str | None] = mapped_column(String(255))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_by: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    actor: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(255), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(255), index=True)
    details: Mapped[dict | None] = mapped_column(JSON)


class TroubleshootingCase(TimestampMixin, Base):
    __tablename__ = "troubleshooting_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manufacturer: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(255), index=True)
    serial: Mapped[str | None] = mapped_column(String(255))
    configuration: Mapped[str | None] = mapped_column(String(255))
    hardware_version: Mapped[str | None] = mapped_column(String(255))
    software_version: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(255), index=True)
    symptom_description: Mapped[str | None] = mapped_column(Text)
    measurements: Mapped[str | None] = mapped_column(Text)
    operating_context: Mapped[str | None] = mapped_column(Text)
    actions_attempted: Mapped[str | None] = mapped_column(Text)
    service_history: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(100), default="draft", nullable=False)
    response_snapshot: Mapped[dict | None] = mapped_column(JSON)
