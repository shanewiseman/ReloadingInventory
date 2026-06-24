"""Reconcile component weight storage location.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    inventory_columns = {column["name"] for column in inspector.get_columns("inventory_lot")}
    if "weight_grains" not in inventory_columns:
        op.add_column("inventory_lot", sa.Column("weight_grains", sa.Numeric(10, 3), nullable=True))

    component_columns = {column["name"] for column in inspector.get_columns("recipe_component")}
    if "weight_grains" in component_columns:
        op.drop_column("recipe_component", "weight_grains")


def downgrade():
    pass
