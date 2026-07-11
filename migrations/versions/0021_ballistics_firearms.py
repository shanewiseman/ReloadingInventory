"""Add ballistics and firearm profiles.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def _columns(inspector, table_name):
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())

    if "firearm_profile" not in tables:
        op.create_table(
            "firearm_profile",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("cartridge_workflow_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("caliber", sa.String(length=80), nullable=True),
            sa.Column("barrel_length", sa.Numeric(10, 3), nullable=True),
            sa.Column("sight_height", sa.Numeric(10, 3), nullable=True),
            sa.Column("default_zero_distance", sa.Numeric(10, 3), nullable=True),
            sa.Column("twist_rate", sa.Numeric(10, 3), nullable=True),
            sa.Column("twist_direction", sa.String(length=10), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["cartridge_workflow_id"], ["cartridge_workflow.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "name", name="uq_firearm_profile_user_name"),
        )
        op.create_index(op.f("ix_firearm_profile_user_id"), "firearm_profile", ["user_id"])
        op.create_index(
            op.f("ix_firearm_profile_cartridge_workflow_id"),
            "firearm_profile",
            ["cartridge_workflow_id"],
        )

    if "bullet_ballistics_profile" not in tables:
        op.create_table(
            "bullet_ballistics_profile",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("drag_model", sa.String(length=8), nullable=False),
            sa.Column("ballistic_coefficient", sa.Numeric(10, 6), nullable=False),
            sa.Column("diameter", sa.Numeric(10, 4), nullable=True),
            sa.Column("bullet_length", sa.Numeric(10, 4), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["item_id"], ["item.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("item_id", name="uq_bullet_ballistics_item"),
        )
        op.create_index(op.f("ix_bullet_ballistics_profile_user_id"), "bullet_ballistics_profile", ["user_id"])
        op.create_index(op.f("ix_bullet_ballistics_profile_item_id"), "bullet_ballistics_profile", ["item_id"])

    performance_columns = _columns(sa.inspect(connection), "performance_record")
    if "firearm_profile_id" not in performance_columns:
        op.add_column("performance_record", sa.Column("firearm_profile_id", sa.Integer(), nullable=True))
        op.create_index(
            op.f("ix_performance_record_firearm_profile_id"),
            "performance_record",
            ["firearm_profile_id"],
        )


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    performance_columns = _columns(inspector, "performance_record")
    if "firearm_profile_id" in performance_columns:
        op.drop_index(op.f("ix_performance_record_firearm_profile_id"), table_name="performance_record")
        op.drop_column("performance_record", "firearm_profile_id")

    tables = set(sa.inspect(connection).get_table_names())
    if "bullet_ballistics_profile" in tables:
        op.drop_index(op.f("ix_bullet_ballistics_profile_item_id"), table_name="bullet_ballistics_profile")
        op.drop_index(op.f("ix_bullet_ballistics_profile_user_id"), table_name="bullet_ballistics_profile")
        op.drop_table("bullet_ballistics_profile")

    tables = set(sa.inspect(connection).get_table_names())
    if "firearm_profile" in tables:
        op.drop_index(op.f("ix_firearm_profile_cartridge_workflow_id"), table_name="firearm_profile")
        op.drop_index(op.f("ix_firearm_profile_user_id"), table_name="firearm_profile")
        op.drop_table("firearm_profile")
