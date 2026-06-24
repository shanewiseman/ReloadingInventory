"""Add inventory lot component weights.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("inventory_lot")}
    if "weight_grains" not in columns:
        op.add_column("inventory_lot", sa.Column("weight_grains", sa.Numeric(10, 3), nullable=True))


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("inventory_lot")}
    if "weight_grains" in columns:
        op.drop_column("inventory_lot", "weight_grains")
