"""Persist immutable ingestion artifacts and BM25 generations.

Revision ID: 0007_process_document_versions
Revises: 0006_accept_document_uploads
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_process_document_versions"
down_revision = "0006_accept_document_uploads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_version_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("collection_name", sa.String(length=64), nullable=False),
        sa.Column("object_bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "collection_name IN ('regulations', 'tables')",
            name="ck_document_version_artifacts_collection",
        ),
        sa.CheckConstraint(
            "chunk_count > 0",
            name="ck_document_version_artifacts_chunk_count",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            name="uq_document_version_artifacts_version",
        ),
        sa.UniqueConstraint(
            "object_bucket",
            "object_key",
            name="uq_document_version_artifacts_object",
        ),
    )
    op.create_table(
        "bm25_generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "chunk_count > 0",
            name="ck_bm25_generations_chunk_count",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            name="uq_bm25_generations_version",
        ),
        sa.UniqueConstraint("artifact_path", name="uq_bm25_generations_path"),
    )
    op.create_table(
        "knowledge_index_state",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "active_bm25_generation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_knowledge_index_state_singleton"),
        sa.ForeignKeyConstraint(
            ["active_bm25_generation_id"],
            ["bm25_generations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO knowledge_index_state (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("knowledge_index_state")
    op.drop_table("bm25_generations")
    op.drop_table("document_version_artifacts")
