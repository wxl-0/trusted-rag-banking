"""Establish the PostgreSQL migration baseline.

Revision ID: 0001_postgresql_baseline
Revises:
Create Date: 2026-08-28
"""


revision = "0001_postgresql_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Domain tables are introduced by the tickets that own those behaviours.
    pass


def downgrade() -> None:
    pass
