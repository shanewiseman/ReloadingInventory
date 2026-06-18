"""Track batch quantity cleared from emptied containers.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("batch")}
    if "container_depleted_quantity" not in columns:
        op.add_column(
            "batch",
            sa.Column(
                "container_depleted_quantity",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("batch")}
    if "container_depleted_quantity" in columns:
        op.drop_column("batch", "container_depleted_quantity")
