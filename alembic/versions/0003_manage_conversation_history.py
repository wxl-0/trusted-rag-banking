"""Add conversation history metadata.

Revision ID: 0003_manage_conversation_history
Revises: 0002_create_conversations
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_manage_conversation_history"
down_revision = "0002_create_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("title", sa.Text(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_conversations_owner_activity",
        "conversations",
        ["owner_subject", "updated_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_owner_activity", table_name="conversations")
    op.drop_column("conversations", "deleted_at")
    op.drop_column("conversations", "title")
