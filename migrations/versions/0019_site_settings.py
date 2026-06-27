"""Add site settings table.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "site_setting" in inspector.get_table_names():
        return
    op.create_table(
        "site_setting",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "site_setting" in inspector.get_table_names():
        op.drop_table("site_setting")
