"""GET /api/audit — filterable audit trail."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from perdiem.db import repository as repo
from perdiem.web.deps import CurrentUser, DBSession
from perdiem.web.schemas import AuditOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    run_id: uuid.UUID | None = Query(default=None),
    claim_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = DBSession,
    _user: str = CurrentUser,
) -> list[AuditOut]:
    entries = repo.get_audit_entries(
        session,
        run_id=run_id,
        claim_id=claim_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return [AuditOut.model_validate(e) for e in entries]
