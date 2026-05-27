"""GET /PUT /api/config — view and update rules configuration."""
from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy.orm import Session

from perdiem.db import repository as repo
from perdiem.web.deps import CurrentUser, DBSession
from perdiem.web.schemas import ConfigIn, ConfigOut

router = APIRouter(prefix="/api/config", tags=["config"])

_DEFAULTS: dict = {
    "outbound_flights": ["FD3013", "FD3015"],
    "return_flights": ["FD3026", "FD3006", "FD3038", "FD3084"],
    "rate_thb_per_day": 400,
    "name_match_threshold": 0.8,
    "ocr_confidence_threshold": 0.6,
}


def _read_config(session: Session) -> ConfigOut:
    stored = repo.get_all_config(session)
    merged = {**_DEFAULTS, **stored}
    return ConfigOut(
        outbound_flights=list(merged["outbound_flights"]),
        return_flights=list(merged["return_flights"]),
        rate_thb_per_day=int(merged["rate_thb_per_day"]),
        name_match_threshold=float(merged["name_match_threshold"]),
        ocr_confidence_threshold=float(merged["ocr_confidence_threshold"]),
    )


@router.get("", response_model=ConfigOut)
def get_config(session: Session = DBSession, _user: str = CurrentUser) -> ConfigOut:
    return _read_config(session)


@router.put("", response_model=ConfigOut)
def update_config(
    body: ConfigIn,
    session: Session = DBSession,
    user: str = CurrentUser,
) -> ConfigOut:
    updates = body.model_dump()
    for key, value in updates.items():
        repo.set_config(session, key, value)
    repo.write_audit(
        session,
        action="config_updated",
        detail={"updated_by": user, "new_values": updates},
    )
    session.commit()
    return _read_config(session)
