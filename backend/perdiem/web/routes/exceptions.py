"""Exception queue and exception report export."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from perdiem.db import repository as repo
from perdiem.db.models import Claim, Override, Verdict
from perdiem.engine import report as report_engine
from perdiem.engine.models import Claim as EngineClaim, DayVerdict
from perdiem.web.deps import CurrentUser, DBSession
from perdiem.web.schemas import ExceptionOut, RunRowOut

router = APIRouter(tags=["exceptions"])

_FLAGGED = ("NEEDS_REVIEW", "INVALID")


def _first_file_id(roster_refs: list) -> str | None:
    if not roster_refs:
        return None
    url: str = roster_refs[0].get("url", "")
    for part in url.split("/"):
        if len(part) > 20 and "=" not in part:
            return part
    import re
    m = re.search(r"[?&]id=([^&]+)", url)
    return m.group(1) if m else None


@router.get("/api/runs/{run_id}/exceptions", response_model=list[ExceptionOut])
def list_exceptions(
    run_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = DBSession,
    _user: str = CurrentUser,
) -> list[ExceptionOut]:
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    stmt = (
        select(Verdict, Claim)
        .join(Claim, Verdict.claim_id == Claim.id)
        .where(Claim.run_id == run_id)
        .where(Verdict.verdict.in_(_FLAGGED))
        .order_by(Claim.staff_id, Verdict.claimed_date)
        .limit(min(limit, 500))
        .offset(offset)
    )
    rows = session.execute(stmt).all()

    return [
        ExceptionOut(
            claim_id=claim.id,
            verdict_id=verdict.id,
            staff_id=claim.staff_id,
            name=claim.name,
            email=claim.email,
            source_row_ref=claim.source_row_ref,
            claimed_date=verdict.claimed_date,
            verdict=verdict.verdict,
            rule=verdict.rule,
            reason=verdict.reason,
            confidence=verdict.confidence,
            roster_file_id=_first_file_id(list(claim.roster_refs or [])),
            extracted=dict(verdict.extracted) if verdict.extracted else None,
        )
        for verdict, claim in rows
    ]


@router.get("/api/runs/{run_id}/rows", response_model=list[RunRowOut])
def list_rows(
    run_id: uuid.UUID,
    limit: int = Query(default=2000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    session: Session = DBSession,
    _user: str = CurrentUser,
) -> list[RunRowOut]:
    """Every per-day verdict for a run (all statuses) with the crew's form fields."""
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    # Latest override decision per claim (last wins, ordered by decided_at asc).
    latest_decision: dict = {}
    for cid, decision in session.execute(
        select(Override.claim_id, Override.decision)
        .join(Claim, Override.claim_id == Claim.id)
        .where(Claim.run_id == run_id)
        .order_by(Override.decided_at.asc())
    ).all():
        latest_decision[cid] = decision

    stmt = (
        select(Verdict, Claim)
        .join(Claim, Verdict.claim_id == Claim.id)
        .where(Claim.run_id == run_id)
        .order_by(Claim.staff_id, Verdict.claimed_date)
        .limit(min(limit, 10000))
        .offset(offset)
    )
    rows = session.execute(stmt).all()

    return [
        RunRowOut(
            claim_id=claim.id,
            verdict_id=verdict.id,
            claimed_date=verdict.claimed_date,
            verdict=verdict.verdict,
            decision=latest_decision.get(claim.id),
            rule=verdict.rule,
            reason=verdict.reason,
            confidence=verdict.confidence,
            source=claim.source,
            source_row_ref=claim.source_row_ref,
            submitted_at=claim.submitted_at,
            staff_id=claim.staff_id,
            name=claim.name,
            email=claim.email,
            position=claim.position,
            base=claim.base,
            claim_month=claim.claim_month,
            claimed_days=list(claim.claimed_days or []),
            roster_file_id=_first_file_id(list(claim.roster_refs or [])),
        )
        for verdict, claim in rows
    ]


@router.get("/api/runs/{run_id}/exceptions/export")
def export_exceptions(
    run_id: uuid.UUID,
    session: Session = DBSession,
    _user: str = CurrentUser,
) -> Response:
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status not in ("DONE", "FAILED"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run not finished yet")

    claims = repo.get_claims_for_run(session, run_id)
    pairs: list[tuple[EngineClaim, list[DayVerdict]]] = []
    for claim in claims:
        vds = repo.get_verdicts_for_claim(session, claim.id)
        overrides = repo.get_overrides_for_claim(session, claim.id)
        decision = overrides[-1].decision if overrides else None
        from perdiem.web.routes.results import _apply_override, _db_claim_to_engine
        pairs.append((_db_claim_to_engine(claim), _apply_override(vds, decision)))

    xlsx_bytes = report_engine.write_exceptions(pairs, run.cycle_month)
    filename = f"exceptions_{run.cycle_month.replace(' ', '_')}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
