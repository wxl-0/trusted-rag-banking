"""Create knowledge document read model.

Revision ID: 0005_create_knowledge_documents
Revises: 0004_control_model_context
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_create_knowledge_documents"
down_revision = "0004_control_model_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by_subject", sa.String(length=255), nullable=False),
        sa.Column("uploaded_by_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("version_number > 0", name="ck_document_versions_number"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_document_versions_size"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_number",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "current_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_knowledge_documents_current_version",
        "knowledge_documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "ingestion_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("result_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued', 'parsing', 'indexing', 'succeeded', 'failed')",
            name="ck_ingestion_tasks_state",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_documents_activity",
        "knowledge_documents",
        ["updated_at", "id"],
    )
    op.create_index(
        "ix_document_versions_document_number",
        "document_versions",
        ["document_id", "version_number"],
    )
    op.create_index(
        "ix_ingestion_tasks_version_activity",
        "ingestion_tasks",
        ["document_version_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_tasks_version_activity", table_name="ingestion_tasks")
    op.drop_index("ix_document_versions_document_number", table_name="document_versions")
    op.drop_index("ix_knowledge_documents_activity", table_name="knowledge_documents")
    op.drop_table("ingestion_tasks")
    op.drop_constraint(
        "fk_knowledge_documents_current_version",
        "knowledge_documents",
        type_="foreignkey",
    )
    op.drop_column("knowledge_documents", "current_version_id")
    op.drop_table("document_versions")
    op.drop_table("knowledge_documents")
