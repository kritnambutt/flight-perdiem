"""Add stage column to runs table.

Revision ID: 002
Revises: 001
Create Date: 2026-05-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("stage", sa.VARCHAR(30), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "stage")
