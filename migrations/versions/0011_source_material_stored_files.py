"""Link source material to stored files.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("source_material")}
    if "stored_file_id" not in columns:
        op.add_column("source_material", sa.Column("stored_file_id", sa.Integer(), nullable=True))


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("source_material")}
    if "stored_file_id" in columns:
        op.drop_column("source_material", "stored_file_id")
