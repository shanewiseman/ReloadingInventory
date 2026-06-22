"""Add batch production loss accounting.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "batch_production_loss" not in inspector.get_table_names():
        op.create_table(
            "batch_production_loss",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("batch_id", sa.Integer(), nullable=False),
            sa.Column("recipe_component_id", sa.Integer(), nullable=False),
            sa.Column("source_reservation_id", sa.Integer(), nullable=False),
            sa.Column("replacement_reservation_id", sa.Integer(), nullable=False),
            sa.Column("source_lot_id", sa.Integer(), nullable=False),
            sa.Column("replacement_lot_id", sa.Integer(), nullable=False),
            sa.Column("quantity_lost", sa.Numeric(18, 6), nullable=False),
            sa.Column("unit", sa.String(length=20), nullable=False),
            sa.Column("reason", sa.String(length=160), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("quantity_lost > 0", name="ck_production_loss_positive"),
            sa.ForeignKeyConstraint(["batch_id"], ["batch.id"]),
            sa.ForeignKeyConstraint(["recipe_component_id"], ["recipe_component.id"]),
            sa.ForeignKeyConstraint(["replacement_lot_id"], ["inventory_lot.id"]),
            sa.ForeignKeyConstraint(["replacement_reservation_id"], ["batch_inventory_reservation.id"]),
            sa.ForeignKeyConstraint(["source_lot_id"], ["inventory_lot.id"]),
            sa.ForeignKeyConstraint(["source_reservation_id"], ["batch_inventory_reservation.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in ("batch_id", "source_lot_id", "replacement_lot_id", "user_id"):
            op.create_index(
                op.f(f"ix_batch_production_loss_{column}"),
                "batch_production_loss",
                [column],
                unique=False,
            )


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "batch_production_loss" in inspector.get_table_names():
        for column in ("user_id", "replacement_lot_id", "source_lot_id", "batch_id"):
            op.drop_index(op.f(f"ix_batch_production_loss_{column}"), table_name="batch_production_loss")
        op.drop_table("batch_production_loss")
