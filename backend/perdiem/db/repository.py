"""Data-access helpers (repository layer).

PD-PLAT-001 — thin functions over SQLAlchemy Session used by the worker and
the web API.  All functions accept an explicit Session so callers control
transaction boundaries.

No business logic lives here — the engine is a pure library, the repository
is a pure persistence layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from perdiem.db.models import Audit, Claim, Config, Override, Run, Verdict
from perdiem.engine.models import (
    Claim as EngineClaim,
    DayVerdict,
)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def create_run(
    session: Session,
    cycle_month: str,
    posting_sheet: str | None = None,
    late_sheet: str | None = None,
) -> Run:
    run = Run(
        id=uuid.uuid4(),
        cycle_month=cycle_month,
        status="PENDING",
        progress=0,
        counts={},
        posting_sheet=posting_sheet,
        late_sheet=late_sheet,
    )
    session.add(run)
    session.flush()
    return run


def get_run(session: Session, run_id: uuid.UUID) -> Run | None:
    return session.get(Run, run_id)


def list_runs(
    session: Session,
    limit: int = 100,
    offset: int = 0,
) -> list[Run]:
    stmt = (
        select(Run)
        .order_by(Run.started_at.desc().nulls_last())
        .limit(min(limit, 500))
        .offset(offset)
    )
    return list(session.scalars(stmt))


def update_run_status(
    session: Session,
    run_id: uuid.UUID,
    status: str,
    *,
    stage: str | None = None,
    progress: int | None = None,
    counts: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"Run {run_id} not found")
    run.status = status
    if stage is not None:
        run.stage = stage
    if progress is not None:
        run.progress = progress
    if counts is not None:
        run.counts = counts
    if started_at is not None:
        run.started_at = started_at
    if finished_at is not None:
        run.finished_at = finished_at
    session.flush()


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def create_claim(session: Session, run_id: uuid.UUID, claim: EngineClaim) -> Claim:
    row = Claim(
        id=uuid.uuid4(),
        run_id=run_id,
        source=claim.source,
        source_row_ref=claim.source_row_ref,
        submitted_at=claim.timestamp,
        staff_id=claim.staff_id,
        name=claim.name,
        email=claim.email,
        position=claim.position,
        base=claim.base,
        claim_month=claim.claim_month,
        claimed_days=claim.claimed_days,
        roster_refs=[{"url": u} for u in claim.roster_links],
    )
    session.add(row)
    session.flush()
    return row


def update_claim_roster_refs(
    session: Session,
    claim_id: uuid.UUID,
    refs: list[dict[str, Any]],
) -> None:
    """Persist the resolved roster refs (URL + file_id + content_type + status).

    `create_claim` stores only `{"url": ...}`; once `fetch_rosters` has resolved
    each link this enriches the stored objects so the roster file-type tally is
    re-derivable from the DB and per-claim roster type is inspectable. Replaces
    the list wholesale (idempotent re-run support, N2).
    """
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise ValueError(f"Claim {claim_id} not found")
    claim.roster_refs = refs
    session.flush()


def get_claims_for_run(session: Session, run_id: uuid.UUID) -> list[Claim]:
    stmt = select(Claim).where(Claim.run_id == run_id).order_by(Claim.source_row_ref)
    return list(session.scalars(stmt))


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def write_verdicts(
    session: Session,
    claim_id: uuid.UUID,
    staff_id: str | None,
    verdicts: list[DayVerdict],
    *,
    extracted: dict[str, Any] | None = None,
    confidence: float | None = None,
) -> None:
    """Replace all verdicts for a claim (idempotent re-run support, N2).

    `extracted` (PD-ML-001) is the serialised OCR read for the claim's roster —
    the same snapshot for every day verdict — so the Exceptions panel can show
    what the OCR actually read (e.g. ``roster staff_id=1006428 @0.60``) and a
    false reject is self-evident. `confidence` is a headline OCR confidence for
    quick sorting (e.g. the staff-ID read confidence).
    """
    existing = session.scalars(select(Verdict).where(Verdict.claim_id == claim_id)).all()
    for v in existing:
        session.delete(v)
    session.flush()

    for dv in verdicts:
        session.add(
            Verdict(
                id=uuid.uuid4(),
                claim_id=claim_id,
                staff_id=staff_id,
                claimed_date=dv.claimed_date,
                verdict=dv.verdict,
                rule=dv.rule,
                reason=dv.reason,
                remark=dv.remark,
                confidence=confidence,
                extracted=extracted,
            )
        )
    session.flush()


def get_verdicts_for_claim(session: Session, claim_id: uuid.UUID) -> list[Verdict]:
    stmt = (
        select(Verdict)
        .where(Verdict.claim_id == claim_id)
        .order_by(Verdict.claimed_date)
    )
    return list(session.scalars(stmt))


def get_verdicts_for_run(session: Session, run_id: uuid.UUID) -> list[Verdict]:
    stmt = (
        select(Verdict)
        .join(Claim, Verdict.claim_id == Claim.id)
        .where(Claim.run_id == run_id)
        .order_by(Verdict.staff_id, Verdict.claimed_date)
    )
    return list(session.scalars(stmt))


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def create_override(
    session: Session,
    claim_id: uuid.UUID,
    decision: str,
    decided_by: str,
    note: str | None = None,
) -> Override:
    override = Override(
        id=uuid.uuid4(),
        claim_id=claim_id,
        decision=decision,
        decided_by=decided_by,
        decided_at=datetime.now(tz=timezone.utc),
        note=note,
    )
    session.add(override)
    session.flush()
    return override


def get_overrides_for_claim(session: Session, claim_id: uuid.UUID) -> list[Override]:
    stmt = select(Override).where(Override.claim_id == claim_id).order_by(Override.decided_at)
    return list(session.scalars(stmt))


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def write_audit(
    session: Session,
    action: str,
    run_id: uuid.UUID | None = None,
    claim_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        Audit(
            id=uuid.uuid4(),
            run_id=run_id,
            claim_id=claim_id,
            action=action,
            detail=detail or {},
            at=datetime.now(tz=timezone.utc),
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def get_config(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Config, key)
    return row.value if row is not None else default


def set_config(session: Session, key: str, value: Any) -> None:
    row = session.get(Config, key)
    if row is None:
        session.add(Config(key=key, value=value))
    else:
        row.value = value
    session.flush()


def get_all_config(session: Session) -> dict[str, Any]:
    rows = session.scalars(select(Config)).all()
    return {r.key: r.value for r in rows}


# ---------------------------------------------------------------------------
# Audit queries
# ---------------------------------------------------------------------------


def get_audit_entries(
    session: Session,
    *,
    run_id: uuid.UUID | None = None,
    claim_id: uuid.UUID | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Audit]:
    stmt = select(Audit).order_by(Audit.at.desc())
    if run_id is not None:
        stmt = stmt.where(Audit.run_id == run_id)
    if claim_id is not None:
        stmt = stmt.where(Audit.claim_id == claim_id)
    if action is not None:
        stmt = stmt.where(Audit.action == action)
    stmt = stmt.limit(min(limit, 500)).offset(offset)
    return list(session.scalars(stmt))
