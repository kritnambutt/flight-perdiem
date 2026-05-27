"""SQLAlchemy ORM models for the six persisted tables.

PD-PLAT-001 — runs, claims, verdicts, overrides, audit, config.
All IDs are UUIDs; times are timestamptz; flexible fields use JSONB.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    DATE,
    DOUBLE_PRECISION,
    TEXT,
    VARCHAR,
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_month: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, default="PENDING")
    stage: Mapped[str | None] = mapped_column(VARCHAR(30), nullable=True)
    # Admin-selected worksheet in each uploaded workbook (overrides auto-detection).
    posting_sheet: Mapped[str | None] = mapped_column(VARCHAR(100), nullable=True)
    late_sheet: Mapped[str | None] = mapped_column(VARCHAR(100), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    claims: Mapped[list["Claim"]] = relationship("Claim", back_populates="run", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    source_row_ref: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    staff_id: Mapped[str | None] = mapped_column(VARCHAR(20), nullable=True)
    name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    email: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    position: Mapped[str | None] = mapped_column(VARCHAR(100), nullable=True)
    base: Mapped[str | None] = mapped_column(VARCHAR(50), nullable=True)
    claim_month: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    claimed_days: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    roster_refs: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)

    run: Mapped["Run"] = relationship("Run", back_populates="claims")
    verdicts: Mapped[list["Verdict"]] = relationship(
        "Verdict", back_populates="claim", cascade="all, delete-orphan"
    )
    overrides: Mapped[list["Override"]] = relationship(
        "Override", back_populates="claim", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_claims_run_id", "run_id"),
        Index("ix_claims_staff_id", "staff_id"),
    )


# ---------------------------------------------------------------------------
# verdicts
# ---------------------------------------------------------------------------


class Verdict(Base):
    __tablename__ = "verdicts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized for the dedup index (staff_id, claimed_date)
    staff_id: Mapped[str | None] = mapped_column(VARCHAR(20), nullable=True)
    claimed_date: Mapped[date] = mapped_column(DATE, nullable=False)
    verdict: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    rule: Mapped[str] = mapped_column(VARCHAR(10), nullable=False)
    reason: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    remark: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    confidence: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    extracted: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    claim: Mapped["Claim"] = relationship("Claim", back_populates="verdicts")

    __table_args__ = (
        Index("ix_verdicts_claim_id", "claim_id"),
        Index("ix_verdicts_staff_id_claimed_date", "staff_id", "claimed_date"),
    )


# ---------------------------------------------------------------------------
# overrides
# ---------------------------------------------------------------------------


class Override(Base):
    __tablename__ = "overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    decided_by: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    claim: Mapped["Claim"] = relationship("Claim", back_populates="overrides")

    __table_args__ = (Index("ix_overrides_claim_id", "claim_id"),)


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


class Audit(Base):
    __tablename__ = "audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_audit_run_id", "run_id"),)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


class Config(Base):
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(VARCHAR(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
