"""POST /api/claims/{id}/decision — approve, reject, or correct a claim."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session

from perdiem.db import repository as repo
from perdiem.web.deps import CurrentUser, DBSession
from perdiem.web.schemas import DecisionIn, DecisionOut

router = APIRouter(prefix="/api/claims", tags=["claims"])


@router.post("/{claim_id}/decision", response_model=DecisionOut)
def record_decision(
    claim_id: uuid.UUID,
    body: DecisionIn,
    session: Session = DBSession,
    user: str = CurrentUser,
) -> DecisionOut:
    from perdiem.db.models import Claim
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")

    if body.corrected_days is not None:
        claim.claimed_days = body.corrected_days
        session.flush()

    override = repo.create_override(
        session,
        claim_id=claim_id,
        decision=body.decision,
        decided_by=user,
        note=body.note,
    )
    repo.write_audit(
        session,
        action="override_applied",
        run_id=claim.run_id,
        claim_id=claim_id,
        detail={"decision": body.decision, "decided_by": user, "note": body.note},
    )
    session.commit()

    return DecisionOut(
        claim_id=claim_id,
        decision=override.decision,
        decided_by=override.decided_by,
        note=override.note,
    )
