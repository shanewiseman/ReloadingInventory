"""Initial traceability schema.

Revision ID: 0001
Revises:
Create Date: 2026-06-17
"""
from alembic import op

from storage_service.models import db

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    db.metadata.create_all(bind=op.get_bind())


def downgrade():
    db.metadata.drop_all(bind=op.get_bind())

