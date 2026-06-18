"""Add cartridge limit to storage containers.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("storage_container")}
    if "cartridge_limit" not in columns:
        op.add_column("storage_container", sa.Column("cartridge_limit", sa.Integer(), nullable=True))


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("storage_container")}
    if "cartridge_limit" in columns:
        op.drop_column("storage_container", "cartridge_limit")
