"""Add batch characteristics.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("batch")}
    if "characteristics" not in columns:
        op.add_column("batch", sa.Column("characteristics", sa.Text(), nullable=True))


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("batch")}
    if "characteristics" in columns:
        op.drop_column("batch", "characteristics")
