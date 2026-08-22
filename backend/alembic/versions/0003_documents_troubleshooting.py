"""documents and troubleshooting foundation

Revision ID: 0003_documents_troubleshooting
Revises: 0002_identification_workflow
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_documents_troubleshooting"
down_revision = "0002_identification_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in [
        sa.Column("document_number", sa.String(length=255), nullable=True),
        sa.Column("manufacturer_text", sa.String(length=255), nullable=True),
        sa.Column("equipment_family_text", sa.String(length=255), nullable=True),
        sa.Column("equipment_model_text", sa.String(length=255), nullable=True),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("access_classification", sa.String(length=100), nullable=True),
        sa.Column("ingestion_status", sa.String(length=100), nullable=True),
        sa.Column("ingestion_errors", sa.JSON(), nullable=True),
    ]:
        op.add_column("documents", column)
    for name in ["document_number", "manufacturer_text", "equipment_family_text", "equipment_model_text", "ingestion_status"]:
        op.create_index(f"ix_documents_{name}", "documents", [name])
    op.add_column("document_versions", sa.Column("effective_at", sa.Date(), nullable=True))
    op.add_column("document_versions", sa.Column("source_path", sa.String(length=1000), nullable=True))
    op.add_column("document_versions", sa.Column("duplicate_of_version_id", sa.Integer(), nullable=True))
    op.create_index("ix_document_versions_duplicate_of_version_id", "document_versions", ["duplicate_of_version_id"])
    for column in [
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("extraction_method", sa.String(length=100), nullable=True),
        sa.Column("tables", sa.JSON(), nullable=True),
        sa.Column("figure_refs", sa.JSON(), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=True),
    ]:
        op.add_column("document_chunks", column)
    op.create_table(
        "troubleshooting_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("manufacturer", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("serial", sa.String(length=255), nullable=True),
        sa.Column("configuration", sa.String(length=255), nullable=True),
        sa.Column("hardware_version", sa.String(length=255), nullable=True),
        sa.Column("software_version", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("symptom_description", sa.Text(), nullable=True),
        sa.Column("measurements", sa.Text(), nullable=True),
        sa.Column("operating_context", sa.Text(), nullable=True),
        sa.Column("actions_attempted", sa.Text(), nullable=True),
        sa.Column("service_history", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("response_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_troubleshooting_cases_manufacturer", "troubleshooting_cases", ["manufacturer"])
    op.create_index("ix_troubleshooting_cases_model", "troubleshooting_cases", ["model"])
    op.create_index("ix_troubleshooting_cases_error_code", "troubleshooting_cases", ["error_code"])


def downgrade() -> None:
    op.drop_table("troubleshooting_cases")
    for column in ["search_text", "figure_refs", "tables", "extraction_method", "chunk_index"]:
        op.drop_column("document_chunks", column)
    op.drop_index("ix_document_versions_duplicate_of_version_id", table_name="document_versions")
    for column in ["duplicate_of_version_id", "source_path", "effective_at"]:
        op.drop_column("document_versions", column)
    for name in ["ingestion_status", "equipment_model_text", "equipment_family_text", "manufacturer_text", "document_number"]:
        op.drop_index(f"ix_documents_{name}", table_name="documents")
    for column in [
        "ingestion_errors",
        "ingestion_status",
        "access_classification",
        "language",
        "equipment_model_text",
        "equipment_family_text",
        "manufacturer_text",
        "document_number",
    ]:
        op.drop_column("documents", column)
