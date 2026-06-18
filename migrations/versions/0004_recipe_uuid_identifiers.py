"""Replace recipe slugs with UUID identifiers.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-18
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    recipe = sa.table(
        "recipe",
        sa.column("id", sa.Integer),
        sa.column("slug", sa.String),
    )
    recipe_ids = connection.execute(sa.select(recipe.c.id)).scalars().all()
    for recipe_id in recipe_ids:
        connection.execute(
            recipe.update()
            .where(recipe.c.id == recipe_id)
            .values(slug=str(uuid.uuid4()))
        )


def downgrade():
    # Previous human-readable identifiers cannot be reconstructed reliably.
    pass
