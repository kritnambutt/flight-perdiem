"""Initial schema: runs, claims, verdicts, overrides, audit, config.

Revision ID: 001
Revises: None
Create Date: 2026-05-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # runs
    # ------------------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cycle_month", sa.VARCHAR(20), nullable=False),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="PENDING"),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("counts", JSONB, nullable=False, server_default="{}"),
        sa.Column("started_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", TIMESTAMP(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # claims
    # ------------------------------------------------------------------
    op.create_table(
        "claims",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.VARCHAR(20), nullable=False),
        sa.Column("source_row_ref", sa.VARCHAR(200), nullable=False),
        sa.Column("staff_id", sa.VARCHAR(20), nullable=True),
        sa.Column("name", sa.VARCHAR(200), nullable=False),
        sa.Column("email", sa.VARCHAR(200), nullable=False),
        sa.Column("claim_month", sa.VARCHAR(20), nullable=False),
        sa.Column("claimed_days", JSONB, nullable=False, server_default="[]"),
        sa.Column("roster_refs", JSONB, nullable=False, server_default="[]"),
    )
    op.create_index("ix_claims_run_id", "claims", ["run_id"])
    op.create_index("ix_claims_staff_id", "claims", ["staff_id"])

    # ------------------------------------------------------------------
    # verdicts
    # ------------------------------------------------------------------
    op.create_table(
        "verdicts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "claim_id",
            UUID(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("staff_id", sa.VARCHAR(20), nullable=True),  # denormalized for dedup index
        sa.Column("claimed_date", sa.DATE, nullable=False),
        sa.Column("verdict", sa.VARCHAR(20), nullable=False),
        sa.Column("rule", sa.VARCHAR(10), nullable=False),
        sa.Column("reason", sa.TEXT, nullable=True),
        sa.Column("remark", sa.TEXT, nullable=True),
        sa.Column("confidence", sa.DOUBLE_PRECISION, nullable=True),
        sa.Column("extracted", JSONB, nullable=True),
    )
    op.create_index("ix_verdicts_claim_id", "verdicts", ["claim_id"])
    op.create_index(
        "ix_verdicts_staff_id_claimed_date", "verdicts", ["staff_id", "claimed_date"]
    )

    # ------------------------------------------------------------------
    # overrides
    # ------------------------------------------------------------------
    op.create_table(
        "overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "claim_id",
            UUID(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.VARCHAR(20), nullable=False),
        sa.Column("decided_by", sa.VARCHAR(200), nullable=False),
        sa.Column(
            "decided_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("note", sa.TEXT, nullable=True),
    )
    op.create_index("ix_overrides_claim_id", "overrides", ["claim_id"])

    # ------------------------------------------------------------------
    # audit
    # ------------------------------------------------------------------
    op.create_table(
        "audit",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "claim_id",
            UUID(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.VARCHAR(50), nullable=False),
        sa.Column("detail", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_run_id", "audit", ["run_id"])

    # ------------------------------------------------------------------
    # config
    # ------------------------------------------------------------------
    op.create_table(
        "config",
        sa.Column("key", sa.VARCHAR(100), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("config")
    op.drop_index("ix_audit_run_id", table_name="audit")
    op.drop_table("audit")
    op.drop_index("ix_overrides_claim_id", table_name="overrides")
    op.drop_table("overrides")
    op.drop_index("ix_verdicts_staff_id_claimed_date", table_name="verdicts")
    op.drop_index("ix_verdicts_claim_id", table_name="verdicts")
    op.drop_table("verdicts")
    op.drop_index("ix_claims_staff_id", table_name="claims")
    op.drop_index("ix_claims_run_id", table_name="claims")
    op.drop_table("claims")
    op.drop_table("runs")
