"""GET /api/runs/{id}/results — per-crew aggregated payable summary."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.orm import Session

from perdiem.db import repository as repo
from perdiem.db.models import Claim as DbClaim, Verdict as DbVerdict
from perdiem.engine import dedup as dedup_engine
from perdiem.engine.config import RulesConfig
from perdiem.engine.models import Claim as EngineClaim, CrewResult, DayVerdict
from perdiem.web.deps import CurrentUser, DBSession
from perdiem.web.schemas import CrewResultOut, PeriodOut

router = APIRouter(tags=["results"])

_DEFAULT_CFG = RulesConfig()


def _load_cfg(session: Session) -> RulesConfig:
    cfg_map = repo.get_all_config(session)
    cfg = RulesConfig()
    if "outbound_flights" in cfg_map:
        cfg.outbound_flights = set(cfg_map["outbound_flights"])
    if "return_flights" in cfg_map:
        cfg.return_flights = set(cfg_map["return_flights"])
    if "rate_thb_per_day" in cfg_map:
        cfg.rate_thb_per_day = int(cfg_map["rate_thb_per_day"])
    if "name_match_threshold" in cfg_map:
        cfg.name_match_threshold = float(cfg_map["name_match_threshold"])
    return cfg


def _apply_override(verdicts: list[DbVerdict], decision: str | None) -> list[DayVerdict]:
    """Convert DB verdicts to engine DayVerdict, honouring latest override."""
    result = []
    for v in verdicts:
        effective = v.verdict
        if decision == "APPROVE" and v.verdict in ("NEEDS_REVIEW", "INVALID"):
            effective = "VALID"
        elif decision == "REJECT" and v.verdict in ("VALID", "VALID_BACKCLAIM", "NEEDS_REVIEW"):
            effective = "INVALID"
        result.append(
            DayVerdict(
                claimed_date=v.claimed_date,
                verdict=effective,  # type: ignore[arg-type]
                rule=v.rule,
                reason=v.reason,
                remark=v.remark,
            )
        )
    return result


def _db_claim_to_engine(c: DbClaim) -> EngineClaim:
    return EngineClaim(
        source=c.source,  # type: ignore[arg-type]
        source_row_ref=c.source_row_ref,
        timestamp=c.submitted_at,
        email=c.email,
        staff_id=c.staff_id,
        name=c.name,
        position=c.position,
        base=c.base,
        claim_type=None,
        claim_month=c.claim_month,
        claimed_days=list(c.claimed_days or []),
        roster_links=[ref.get("url", "") for ref in (c.roster_refs or [])],
    )


def compute_results(session: Session, run_id: uuid.UUID) -> list[CrewResult]:
    claims = repo.get_claims_for_run(session, run_id)
    cfg = _load_cfg(session)
    pairs: list[tuple[EngineClaim, list[DayVerdict]]] = []
    for claim in claims:
        verdicts = repo.get_verdicts_for_claim(session, claim.id)
        overrides = repo.get_overrides_for_claim(session, claim.id)
        latest_decision = overrides[-1].decision if overrides else None
        engine_verdicts = _apply_override(verdicts, latest_decision)
        pairs.append((_db_claim_to_engine(claim), engine_verdicts))
    return dedup_engine.aggregate(pairs, cfg)


@router.get("/api/runs/{run_id}/results", response_model=list[CrewResultOut])
def get_results(
    run_id: uuid.UUID,
    session: Session = DBSession,
    _user: str = CurrentUser,
) -> list[CrewResultOut]:
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    results = compute_results(session, run_id)
    return [
        CrewResultOut(
            staff_id=r.staff_id,
            name=r.name,
            email=r.email,
            periods=[PeriodOut(start=s, end=e) for s, e in r.periods],
            days=r.days,
            total_thb=r.total_thb,
            remark=r.remark,
        )
        for r in results
    ]
