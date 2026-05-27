"""Add posting_sheet / late_sheet columns to runs table.

Stores the admin's explicit worksheet choice per uploaded workbook so the
worker reads the right tab instead of guessing from the cycle month.

Revision ID: 003
Revises: 002
Create Date: 2026-05-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("posting_sheet", sa.VARCHAR(100), nullable=True))
    op.add_column("runs", sa.Column("late_sheet", sa.VARCHAR(100), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "late_sheet")
    op.drop_column("runs", "posting_sheet")
