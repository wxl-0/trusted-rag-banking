"""Persist rolling conversation context summaries.

Revision ID: 0004_control_model_context
Revises: 0003_manage_conversation_history
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_control_model_context"
down_revision = "0003_manage_conversation_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("context_summary", sa.Text(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column(
            "summarized_message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "summarized_message_count")
    op.drop_column("conversations", "context_summary")
