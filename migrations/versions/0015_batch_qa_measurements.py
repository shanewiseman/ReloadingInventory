"""Add batch QA measurements.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "batch_qa_measurement" not in inspector.get_table_names():
        op.create_table(
            "batch_qa_measurement",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("batch_id", sa.Integer(), nullable=False),
            sa.Column("sample_number", sa.Integer(), nullable=False),
            sa.Column("completed_weight", sa.Numeric(10, 3), nullable=False),
            sa.Column("overall_length", sa.Numeric(10, 4), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("sample_number > 0", name="ck_batch_qa_sample_positive"),
            sa.CheckConstraint("completed_weight > 0", name="ck_batch_qa_weight_positive"),
            sa.CheckConstraint("overall_length > 0", name="ck_batch_qa_length_positive"),
            sa.ForeignKeyConstraint(["batch_id"], ["batch.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("batch_id", "sample_number", name="uq_batch_qa_sample"),
        )
        op.create_index(op.f("ix_batch_qa_measurement_batch_id"), "batch_qa_measurement", ["batch_id"], unique=False)
        op.create_index(op.f("ix_batch_qa_measurement_user_id"), "batch_qa_measurement", ["user_id"], unique=False)


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "batch_qa_measurement" in inspector.get_table_names():
        op.drop_index(op.f("ix_batch_qa_measurement_user_id"), table_name="batch_qa_measurement")
        op.drop_index(op.f("ix_batch_qa_measurement_batch_id"), table_name="batch_qa_measurement")
        op.drop_table("batch_qa_measurement")
