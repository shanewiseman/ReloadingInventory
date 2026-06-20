"""Add generic stored file metadata.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "stored_file" in inspector.get_table_names():
        return
    op.create_table(
        "stored_file",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=320), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=True),
        sa.Column("entity_id", sa.String(length=80), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_stored_file_storage_key"),
    )
    op.create_index(op.f("ix_stored_file_user_id"), "stored_file", ["user_id"], unique=False)
    op.create_index(op.f("ix_stored_file_sha256"), "stored_file", ["sha256"], unique=False)


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "stored_file" not in inspector.get_table_names():
        return
    op.drop_index(op.f("ix_stored_file_sha256"), table_name="stored_file")
    op.drop_index(op.f("ix_stored_file_user_id"), table_name="stored_file")
    op.drop_table("stored_file")
