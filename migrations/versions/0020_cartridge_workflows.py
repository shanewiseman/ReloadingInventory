"""Add cartridge workflow segmentation tables.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
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

    if "cartridge_workflow" not in tables:
        op.create_table(
            "cartridge_workflow",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "name", name="uq_cartridge_workflow_user_name"),
        )
        op.create_index(op.f("ix_cartridge_workflow_user_id"), "cartridge_workflow", ["user_id"])

    user_columns = _columns(inspector, "user")
    if "current_cartridge_workflow_id" not in user_columns:
        op.add_column("user", sa.Column("current_cartridge_workflow_id", sa.Integer(), nullable=True))

    recipe_columns = _columns(inspector, "recipe")
    if "cartridge_workflow_id" not in recipe_columns:
        op.add_column("recipe", sa.Column("cartridge_workflow_id", sa.Integer(), nullable=True))
        op.create_index(op.f("ix_recipe_cartridge_workflow_id"), "recipe", ["cartridge_workflow_id"])

    container_columns = _columns(inspector, "storage_container")
    if "cartridge_workflow_id" not in container_columns:
        op.add_column("storage_container", sa.Column("cartridge_workflow_id", sa.Integer(), nullable=True))
        op.create_index(
            op.f("ix_storage_container_cartridge_workflow_id"),
            "storage_container",
            ["cartridge_workflow_id"],
        )

    tables = set(sa.inspect(connection).get_table_names())
    if "item_cartridge_workflow" not in tables:
        op.create_table(
            "item_cartridge_workflow",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("cartridge_workflow_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["cartridge_workflow_id"], ["cartridge_workflow.id"]),
            sa.ForeignKeyConstraint(["item_id"], ["item.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("item_id", "cartridge_workflow_id", name="uq_item_cartridge_workflow"),
        )
        op.create_index(op.f("ix_item_cartridge_workflow_user_id"), "item_cartridge_workflow", ["user_id"])
        op.create_index(op.f("ix_item_cartridge_workflow_item_id"), "item_cartridge_workflow", ["item_id"])
        op.create_index(
            op.f("ix_item_cartridge_workflow_cartridge_workflow_id"),
            "item_cartridge_workflow",
            ["cartridge_workflow_id"],
        )


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())

    if "item_cartridge_workflow" in tables:
        op.drop_table("item_cartridge_workflow")

    container_columns = _columns(sa.inspect(connection), "storage_container")
    if "cartridge_workflow_id" in container_columns:
        op.drop_index(op.f("ix_storage_container_cartridge_workflow_id"), table_name="storage_container")
        op.drop_column("storage_container", "cartridge_workflow_id")

    recipe_columns = _columns(sa.inspect(connection), "recipe")
    if "cartridge_workflow_id" in recipe_columns:
        op.drop_index(op.f("ix_recipe_cartridge_workflow_id"), table_name="recipe")
        op.drop_column("recipe", "cartridge_workflow_id")

    user_columns = _columns(sa.inspect(connection), "user")
    if "current_cartridge_workflow_id" in user_columns:
        op.drop_column("user", "current_cartridge_workflow_id")

    if "cartridge_workflow" in set(sa.inspect(connection).get_table_names()):
        op.drop_index(op.f("ix_cartridge_workflow_user_id"), table_name="cartridge_workflow")
        op.drop_table("cartridge_workflow")
