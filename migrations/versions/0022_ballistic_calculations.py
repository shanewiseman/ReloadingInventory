"""Add saved ballistic calculations.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())

    if "ballistic_calculation" not in tables:
        op.create_table(
            "ballistic_calculation",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("recipe_id", sa.Integer(), nullable=True),
            sa.Column("batch_id", sa.Integer(), nullable=True),
            sa.Column("bullet_item_id", sa.Integer(), nullable=True),
            sa.Column("firearm_profile_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("load_source", sa.String(length=40), nullable=True),
            sa.Column("load_label", sa.String(length=255), nullable=True),
            sa.Column("bullet_label", sa.String(length=255), nullable=True),
            sa.Column("firearm_label", sa.String(length=255), nullable=True),
            sa.Column("source_snapshot", sa.JSON(), nullable=False),
            sa.Column("inputs", sa.JSON(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["batch_id"], ["batch.id"]),
            sa.ForeignKeyConstraint(["bullet_item_id"], ["item.id"]),
            sa.ForeignKeyConstraint(["firearm_profile_id"], ["firearm_profile.id"]),
            sa.ForeignKeyConstraint(["recipe_id"], ["recipe.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_ballistic_calculation_user_id"), "ballistic_calculation", ["user_id"])
        op.create_index(op.f("ix_ballistic_calculation_recipe_id"), "ballistic_calculation", ["recipe_id"])
        op.create_index(op.f("ix_ballistic_calculation_batch_id"), "ballistic_calculation", ["batch_id"])
        op.create_index(op.f("ix_ballistic_calculation_bullet_item_id"), "ballistic_calculation", ["bullet_item_id"])
        op.create_index(
            op.f("ix_ballistic_calculation_firearm_profile_id"),
            "ballistic_calculation",
            ["firearm_profile_id"],
        )


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "ballistic_calculation" in set(inspector.get_table_names()):
        op.drop_index(op.f("ix_ballistic_calculation_firearm_profile_id"), table_name="ballistic_calculation")
        op.drop_index(op.f("ix_ballistic_calculation_bullet_item_id"), table_name="ballistic_calculation")
        op.drop_index(op.f("ix_ballistic_calculation_batch_id"), table_name="ballistic_calculation")
        op.drop_index(op.f("ix_ballistic_calculation_recipe_id"), table_name="ballistic_calculation")
        op.drop_index(op.f("ix_ballistic_calculation_user_id"), table_name="ballistic_calculation")
        op.drop_table("ballistic_calculation")
