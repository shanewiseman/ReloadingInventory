"""Revise batch lifecycle state names.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    batch = sa.table("batch", sa.column("state", sa.String))
    connection = op.get_bind()
    connection.execute(
        batch.update()
        .where(batch.c.state == "PARTIALLY USED")
        .values(state="PARTIALLY DEPLETED")
    )
    connection.execute(
        batch.update()
        .where(batch.c.state == "USED")
        .values(state="DEPLETED")
    )


def downgrade():
    batch = sa.table("batch", sa.column("state", sa.String))
    connection = op.get_bind()
    connection.execute(
        batch.update()
        .where(batch.c.state == "PARTIALLY DEPLETED")
        .values(state="PARTIALLY USED")
    )
    connection.execute(
        batch.update()
        .where(batch.c.state == "DEPLETED")
        .values(state="USED")
    )
