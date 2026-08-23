"""technical document library metadata

Revision ID: 0006_technical_document_library
Revises: 0005_normalized_catalog_authority
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_technical_document_library"
down_revision = "0005_normalized_catalog_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def add_column_if_missing(table: str, column: sa.Column) -> None:
        columns = {item["name"] for item in inspector.get_columns(table)}
        if column.name not in columns:
            op.add_column(table, column)

    def create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
        indexes = {item["name"] for item in inspector.get_indexes(table)}
        if name not in indexes:
            op.create_index(name, table, columns)

    add_column_if_missing("documents", sa.Column("equipment_family_id", sa.Integer(), nullable=True))
    add_column_if_missing("documents", sa.Column("equipment_model_id", sa.Integer(), nullable=True))
    add_column_if_missing("documents", sa.Column("verification_status", sa.String(length=100), nullable=False, server_default="unverified"))
    add_column_if_missing("documents", sa.Column("notes", sa.Text(), nullable=True))
    create_index_if_missing("ix_documents_equipment_family_id", "documents", ["equipment_family_id"])
    create_index_if_missing("ix_documents_equipment_model_id", "documents", ["equipment_model_id"])
    create_index_if_missing("ix_documents_verification_status", "documents", ["verification_status"])

    add_column_if_missing("document_versions", sa.Column("expires_at", sa.Date(), nullable=True))
    add_column_if_missing("document_versions", sa.Column("lifecycle_status", sa.String(length=100), nullable=False, server_default="draft"))
    add_column_if_missing("document_versions", sa.Column("superseded_by_version_id", sa.Integer(), nullable=True))
    add_column_if_missing("document_versions", sa.Column("original_filename", sa.String(length=500), nullable=True))
    add_column_if_missing("document_versions", sa.Column("mime_type", sa.String(length=255), nullable=True))
    add_column_if_missing("document_versions", sa.Column("file_size", sa.Integer(), nullable=True))
    add_column_if_missing("document_versions", sa.Column("uploaded_at", sa.DateTime(), nullable=True))
    add_column_if_missing("document_versions", sa.Column("uploaded_by", sa.String(length=255), nullable=True))
    add_column_if_missing("document_versions", sa.Column("file_sha256", sa.String(length=64), nullable=True))
    op.execute("UPDATE document_versions SET file_sha256 = file_sha1 WHERE file_sha256 IS NULL AND file_sha1 IS NOT NULL")
    create_index_if_missing("ix_document_versions_lifecycle_status", "document_versions", ["lifecycle_status"])
    create_index_if_missing("ix_document_versions_superseded_by_version_id", "document_versions", ["superseded_by_version_id"])
    create_index_if_missing("ix_document_versions_file_sha256", "document_versions", ["file_sha256"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    def drop_index_if_exists(name: str, table: str) -> None:
        indexes = {item["name"] for item in inspector.get_indexes(table)}
        if name in indexes:
            op.drop_index(name, table_name=table)

    def drop_column_if_exists(table: str, column: str) -> None:
        columns = {item["name"] for item in inspector.get_columns(table)}
        if column in columns:
            op.drop_column(table, column)

    for name in [
        "ix_document_versions_file_sha256",
        "ix_document_versions_superseded_by_version_id",
        "ix_document_versions_lifecycle_status",
    ]:
        drop_index_if_exists(name, "document_versions")
    for column in [
        "uploaded_by",
        "uploaded_at",
        "file_sha256",
        "file_size",
        "mime_type",
        "original_filename",
        "superseded_by_version_id",
        "lifecycle_status",
        "expires_at",
    ]:
        drop_column_if_exists("document_versions", column)
    for name in [
        "ix_documents_verification_status",
        "ix_documents_equipment_model_id",
        "ix_documents_equipment_family_id",
    ]:
        drop_index_if_exists(name, "documents")
    for column in ["notes", "verification_status", "equipment_model_id", "equipment_family_id"]:
        drop_column_if_exists("documents", column)
