"""Make ingestion task delivery idempotent.

Revision ID: 0008_recover_ingestion
Revises: 0007_process_document_versions
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_recover_ingestion"
down_revision = "0007_process_document_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_tasks",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.execute("UPDATE ingestion_tasks SET idempotency_key = id::text")
    op.alter_column("ingestion_tasks", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_ingestion_tasks_idempotency_key",
        "ingestion_tasks",
        ["idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_ingestion_tasks_document_version",
        "ingestion_tasks",
        ["document_version_id"],
    )
    op.add_column(
        "ingestion_tasks",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "ingestion_tasks",
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "ingestion_tasks",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ingestion_tasks",
        sa.Column("result_code", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_ingestion_tasks_attempt_count",
        "ingestion_tasks",
        "attempt_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ingestion_tasks_attempt_count",
        "ingestion_tasks",
        type_="check",
    )
    op.drop_column("ingestion_tasks", "result_code")
    op.drop_column("ingestion_tasks", "lease_expires_at")
    op.drop_column("ingestion_tasks", "lease_token")
    op.drop_column("ingestion_tasks", "attempt_count")
    op.drop_constraint(
        "uq_ingestion_tasks_document_version",
        "ingestion_tasks",
        type_="unique",
    )
    op.drop_constraint(
        "uq_ingestion_tasks_idempotency_key",
        "ingestion_tasks",
        type_="unique",
    )
    op.drop_column("ingestion_tasks", "idempotency_key")
