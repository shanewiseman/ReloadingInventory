"""Disable recipe component alternatives.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-18
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    # Preserve every component while making each one an ordinary mandatory component.
    op.execute("UPDATE recipe_component SET alternative_group = NULL")


def downgrade():
    # Alternative grouping cannot be reconstructed after removal.
    pass
