"""Add inventory lot cost.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("inventory_lot")}
    if "cost" not in columns:
        op.add_column("inventory_lot", sa.Column("cost", sa.Numeric(18, 4), nullable=True))


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("inventory_lot")}
    if "cost" in columns:
        op.drop_column("inventory_lot", "cost")
