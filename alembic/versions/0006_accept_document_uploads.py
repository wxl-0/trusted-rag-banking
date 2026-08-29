"""Add object metadata and upload audit events.

Revision ID: 0006_accept_document_uploads
Revises: 0005_create_knowledge_documents
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_accept_document_uploads"
down_revision = "0005_create_knowledge_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("object_bucket", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("object_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("content_type", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_document_versions_object",
        "document_versions",
        ["object_bucket", "object_key"],
    )
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_target_activity",
        "audit_events",
        ["target_type", "target_id", "created_at"],
    )
    op.create_index(
        "ix_audit_events_actor_activity",
        "audit_events",
        ["actor_subject", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor_activity", table_name="audit_events")
    op.drop_index("ix_audit_events_target_activity", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_constraint(
        "uq_document_versions_object",
        "document_versions",
        type_="unique",
    )
    op.drop_column("document_versions", "content_type")
    op.drop_column("document_versions", "checksum_sha256")
    op.drop_column("document_versions", "object_key")
    op.drop_column("document_versions", "object_bucket")
