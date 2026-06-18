"""Add UUID identifiers for batches.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-18
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns("batch")}
    if "identifier" not in columns:
        op.add_column("batch", sa.Column("identifier", sa.String(length=36), nullable=True))

    batch = sa.table(
        "batch",
        sa.column("id", sa.Integer),
        sa.column("identifier", sa.String),
    )
    batch_ids = connection.execute(
        sa.select(batch.c.id).where(batch.c.identifier.is_(None))
    ).scalars().all()
    for batch_id in batch_ids:
        connection.execute(
            batch.update()
            .where(batch.c.id == batch_id)
            .values(identifier=str(uuid.uuid4()))
        )

    inspector = sa.inspect(connection)
    identifier_column = next(
        column for column in inspector.get_columns("batch")
        if column["name"] == "identifier"
    )
    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("batch")
    }
    if identifier_column["nullable"] or "uq_batch_identifier" not in unique_constraints:
        with op.batch_alter_table("batch") as batch_op:
            if identifier_column["nullable"]:
                batch_op.alter_column(
                    "identifier",
                    existing_type=sa.String(length=36),
                    nullable=False,
                )
            if "uq_batch_identifier" not in unique_constraints:
                batch_op.create_unique_constraint("uq_batch_identifier", ["identifier"])


def downgrade():
    with op.batch_alter_table("batch") as batch_op:
        batch_op.drop_constraint("uq_batch_identifier", type_="unique")
        batch_op.drop_column("identifier")
