"""Add audited inventory adjustments.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("inventory_lot") as batch_op:
        batch_op.add_column(
            sa.Column(
                "adjustment_quantity",
                sa.Numeric(18, 6),
                nullable=False,
                server_default="0",
            )
        )

    op.create_table(
        "inventory_adjustment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("inventory_lot_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity_change", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("available_before", sa.Numeric(18, 6), nullable=False),
        sa.Column("available_after", sa.Numeric(18, 6), nullable=False),
        sa.Column("reason", sa.String(length=160), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("quantity_change != 0", name="ck_adjustment_nonzero"),
        sa.ForeignKeyConstraint(["inventory_lot_id"], ["inventory_lot.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_inventory_adjustment_inventory_lot_id"),
        "inventory_adjustment",
        ["inventory_lot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_adjustment_user_id"),
        "inventory_adjustment",
        ["user_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_inventory_adjustment_user_id"), table_name="inventory_adjustment")
    op.drop_index(
        op.f("ix_inventory_adjustment_inventory_lot_id"),
        table_name="inventory_adjustment",
    )
    op.drop_table("inventory_adjustment")
    with op.batch_alter_table("inventory_lot") as batch_op:
        batch_op.drop_column("adjustment_quantity")
