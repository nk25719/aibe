"""data quality review workflow

Revision ID: 0004_data_quality_review
Revises: 0003_documents_troubleshooting
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_data_quality_review"
down_revision = "0003_documents_troubleshooting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "import_runs" in inspector.get_table_names():
        return
    op.create_table(
        "import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("source_path", sa.String(length=1000), nullable=False),
        sa.Column("source_name", sa.String(length=500), nullable=False),
        sa.Column("source_sha1", sa.String(length=64), nullable=False),
        sa.Column("importer_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.Enum("completed", "failed", name="importrunstatus"), nullable=False),
        sa.Column("inserted_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("ambiguous_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
    )
    op.create_index("ix_import_runs_source_name", "import_runs", ["source_name"])
    op.create_index("ix_import_runs_source_sha1", "import_runs", ["source_sha1"])

    op.create_table(
        "import_source_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_run_id", sa.Integer(), sa.ForeignKey("import_runs.id"), nullable=False),
        sa.Column("source_path", sa.String(length=1000), nullable=False),
        sa.Column("source_name", sa.String(length=500), nullable=False),
        sa.Column("source_sha1", sa.String(length=64), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("row_key", sa.String(length=700), nullable=False),
        sa.Column("row_sha1", sa.String(length=64), nullable=False),
        sa.Column("previous_row_sha1", sa.String(length=64), nullable=True),
        sa.Column("row_status", sa.String(length=50), nullable=False),
        sa.Column("rejection_reason", sa.String(length=255), nullable=True),
        sa.Column("raw_values", sa.JSON(), nullable=False),
        sa.Column("normalized_values", sa.JSON(), nullable=True),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=True),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("source_evidence.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("import_run_id", "source_row", name="uq_import_source_row_run_row"),
    )
    for name in ["import_run_id", "source_name", "source_sha1", "source_row", "row_key", "row_sha1", "row_status", "part_id", "evidence_id"]:
        op.create_index(f"ix_import_source_rows_{name}", "import_source_rows", [name])

    op.create_table(
        "data_quality_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("issue_type", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=True),
        sa.Column("source_import_id", sa.Integer(), sa.ForeignKey("import_runs.id"), nullable=True),
        sa.Column("source_row_id", sa.Integer(), sa.ForeignKey("import_source_rows.id"), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("original_values", sa.JSON(), nullable=True),
        sa.Column("conflicting_values", sa.JSON(), nullable=True),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("status", sa.Enum("open", "under_review", "resolved", "accepted_as_distinct", "merged", "ignored_with_reason", name="dataqualityissuestatus"), nullable=False),
        sa.Column("suggested_resolution", sa.Text(), nullable=True),
        sa.Column("resolution_selected", sa.String(length=100), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("audit_history", sa.JSON(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
    )
    for name in ["issue_type", "entity_type", "entity_id", "source_import_id", "source_row_id", "source_row", "severity", "status", "fingerprint"]:
        op.create_index(f"ix_data_quality_issues_{name}", "data_quality_issues", [name], unique=(name == "fingerprint"))


def downgrade() -> None:
    op.drop_table("data_quality_issues")
    op.drop_table("import_source_rows")
    op.drop_table("import_runs")
