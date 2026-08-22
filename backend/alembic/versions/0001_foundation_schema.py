"""foundation schema

Revision ID: 0001_foundation_schema
Revises:
Create Date: 2026-08-23
"""

from alembic import op

from app.db.models import Base

revision = "0001_foundation_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
