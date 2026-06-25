"""Add expected velocity to recipes.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    recipe_columns = {column["name"] for column in inspector.get_columns("recipe")}
    if "expected_velocity" not in recipe_columns:
        op.add_column("recipe", sa.Column("expected_velocity", sa.Numeric(10, 3), nullable=True))


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    recipe_columns = {column["name"] for column in inspector.get_columns("recipe")}
    if "expected_velocity" in recipe_columns:
        op.drop_column("recipe", "expected_velocity")
