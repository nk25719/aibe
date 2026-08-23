"""normalized catalog authority fields

Revision ID: 0005_normalized_catalog_authority
Revises: 0004_data_quality_review
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_normalized_catalog_authority"
down_revision = "0004_data_quality_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("parts")}
    indexes = {item["name"] for item in inspector.get_indexes("parts")}
    if "manufacturer_id" not in columns:
        op.add_column("parts", sa.Column("manufacturer_id", sa.Integer(), nullable=True))
    if "verification_status" not in columns:
        op.add_column("parts", sa.Column("verification_status", sa.String(length=100), nullable=False, server_default="source_imported_unverified"))
    if "data_origin" not in columns:
        op.add_column("parts", sa.Column("data_origin", sa.String(length=100), nullable=False, server_default="normalized_import"))
    for name, column in [
        ("ix_parts_manufacturer_id", "manufacturer_id"),
        ("ix_parts_verification_status", "verification_status"),
        ("ix_parts_data_origin", "data_origin"),
    ]:
        if name not in indexes:
            op.create_index(name, "parts", [column])


def downgrade() -> None:
    for name in ["ix_parts_data_origin", "ix_parts_verification_status", "ix_parts_manufacturer_id"]:
        op.drop_index(name, table_name="parts")
    for column in ["data_origin", "verification_status", "manufacturer_id"]:
        op.drop_column("parts", column)
