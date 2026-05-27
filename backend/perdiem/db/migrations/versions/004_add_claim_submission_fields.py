"""Add submitted_at / position / base columns to claims table.

Persists the crew-submitted form metadata (Google Form timestamp, crew
position, operating base) so the run detail page can surface it. These were
parsed at ingestion but previously dropped before persistence.

Revision ID: 004
Revises: 003
Create Date: 2026-05-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("claims", sa.Column("position", sa.VARCHAR(100), nullable=True))
    op.add_column("claims", sa.Column("base", sa.VARCHAR(50), nullable=True))


def downgrade() -> None:
    op.drop_column("claims", "base")
    op.drop_column("claims", "position")
    op.drop_column("claims", "submitted_at")
