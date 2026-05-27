"""Pydantic request/response schemas for the FastAPI web layer."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginIn(BaseModel):
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    user: str


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class RunOut(BaseModel):
    id: uuid.UUID
    cycle_month: str
    status: str
    stage: str | None
    progress: int
    counts: dict[str, Any]
    posting_sheet: str | None = None
    late_sheet: str | None = None
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class WorkbookSheetsOut(BaseModel):
    """Worksheet names of an uploaded workbook, plus the auto-detected default."""

    sheets: list[str]
    suggested: str | None = None


# ---------------------------------------------------------------------------
# Results (aggregated per-crew payable summary)
# ---------------------------------------------------------------------------


class PeriodOut(BaseModel):
    start: date
    end: date


class CrewResultOut(BaseModel):
    staff_id: str
    name: str
    email: str
    periods: list[PeriodOut]
    days: int
    total_thb: int
    remark: str | None


# ---------------------------------------------------------------------------
# Exceptions (flagged verdicts)
# ---------------------------------------------------------------------------


class ExceptionOut(BaseModel):
    claim_id: uuid.UUID
    verdict_id: uuid.UUID
    staff_id: str | None
    name: str
    email: str
    source_row_ref: str
    claimed_date: date
    verdict: str
    rule: str
    reason: str | None
    confidence: float | None
    roster_file_id: str | None
    extracted: dict[str, Any] | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Run rows (every per-day verdict + the crew's submitted form fields)
# ---------------------------------------------------------------------------


class RunRowOut(BaseModel):
    claim_id: uuid.UUID
    verdict_id: uuid.UUID
    # Verdict (per claimed day)
    claimed_date: date
    verdict: str                 # original engine verdict for this day
    decision: str | None         # latest admin override on the claim: APPROVE | REJECT | None
    rule: str
    reason: str | None
    confidence: float | None
    # Form fields the crew submitted
    source: str                  # "Posting Base" | "Late Submission"
    source_row_ref: str
    submitted_at: datetime | None  # Google Form submission timestamp
    staff_id: str | None
    name: str
    email: str
    position: str | None         # e.g. "Cabin Crew" | "Senior Cabin Crew"
    base: str | None             # operating base, e.g. "DMK"
    claim_month: str
    claimed_days: list[int]      # all days the crew claimed on this submission
    roster_file_id: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Decision (approve / reject / correct)
# ---------------------------------------------------------------------------


class DecisionIn(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    note: str | None = None
    corrected_days: list[int] | None = None


class DecisionOut(BaseModel):
    claim_id: uuid.UUID
    decision: str
    decided_by: str
    note: str | None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class ConfigOut(BaseModel):
    outbound_flights: list[str]
    return_flights: list[str]
    rate_thb_per_day: int
    name_match_threshold: float
    ocr_confidence_threshold: float


class ConfigIn(BaseModel):
    outbound_flights: list[str] = Field(min_length=1)
    return_flights: list[str] = Field(min_length=1)
    rate_thb_per_day: int = Field(gt=0)
    name_match_threshold: float = Field(gt=0.0, le=1.0)
    ocr_confidence_threshold: float = Field(gt=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID | None
    claim_id: uuid.UUID | None
    action: str
    detail: dict[str, Any]
    at: datetime

    model_config = {"from_attributes": True}
