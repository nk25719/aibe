"""identification workflow fields

Revision ID: 0002_identification_workflow
Revises: 0001_foundation_schema
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_identification_workflow"
down_revision = "0001_foundation_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def add_column_if_missing(table, column):
        columns = {item["name"] for item in inspector.get_columns(table)}
        if column.name not in columns:
            op.add_column(table, column)

    def create_index_if_missing(name, table, columns):
        indexes = {item["name"] for item in inspector.get_indexes(table)}
        if name not in indexes:
            op.create_index(name, table, columns)

    add_column_if_missing("identification_cases", sa.Column("manufacturer_id", sa.Integer(), nullable=True))
    add_column_if_missing("identification_cases", sa.Column("manufacturer_text", sa.String(length=255), nullable=True))
    add_column_if_missing("identification_cases", sa.Column("equipment_family_text", sa.String(length=255), nullable=True))
    add_column_if_missing("identification_cases", sa.Column("equipment_model_text", sa.String(length=255), nullable=True))
    add_column_if_missing("identification_cases", sa.Column("description", sa.Text(), nullable=True))
    add_column_if_missing("identification_cases", sa.Column("visible_markings", sa.Text(), nullable=True))
    add_column_if_missing("identification_cases", sa.Column("component_location", sa.Text(), nullable=True))
    create_index_if_missing("ix_identification_cases_manufacturer_id", "identification_cases", ["manufacturer_id"])
    add_column_if_missing("identification_candidates", sa.Column("confidence_level", sa.String(length=50), nullable=True))
    add_column_if_missing("identification_candidates", sa.Column("match_factors", sa.JSON(), nullable=True))
    add_column_if_missing("identification_candidates", sa.Column("contradicting_evidence", sa.JSON(), nullable=True))
    add_column_if_missing("identification_candidates", sa.Column("candidate_snapshot", sa.JSON(), nullable=True))
    add_column_if_missing("identification_confirmations", sa.Column("evidence_id", sa.Integer(), nullable=True))
    create_index_if_missing("ix_identification_confirmations_evidence_id", "identification_confirmations", ["evidence_id"])


def downgrade() -> None:
    op.drop_index("ix_identification_confirmations_evidence_id", table_name="identification_confirmations")
    op.drop_column("identification_confirmations", "evidence_id")
    op.drop_column("identification_candidates", "candidate_snapshot")
    op.drop_column("identification_candidates", "contradicting_evidence")
    op.drop_column("identification_candidates", "match_factors")
    op.drop_column("identification_candidates", "confidence_level")
    op.drop_index("ix_identification_cases_manufacturer_id", table_name="identification_cases")
    op.drop_column("identification_cases", "component_location")
    op.drop_column("identification_cases", "visible_markings")
    op.drop_column("identification_cases", "description")
    op.drop_column("identification_cases", "equipment_model_text")
    op.drop_column("identification_cases", "equipment_family_text")
    op.drop_column("identification_cases", "manufacturer_text")
    op.drop_column("identification_cases", "manufacturer_id")
