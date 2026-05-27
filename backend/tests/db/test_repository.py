"""Integration tests for perdiem.db.repository (PD-PLAT-001).

Requires Docker (testcontainers).  Skipped automatically if Docker is
unavailable — engine unit tests always run without a DB.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from perdiem.db.repository import (
    create_claim,
    create_override,
    create_run,
    get_all_config,
    get_config,
    get_claims_for_run,
    get_overrides_for_claim,
    get_run,
    get_verdicts_for_run,
    set_config,
    update_claim_roster_refs,
    update_run_status,
    write_audit,
    write_verdicts,
)
from perdiem.engine.models import Claim as EngineClaim, DayVerdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_claim(staff_id: str = "1234567", name: str = "Test Crew") -> EngineClaim:
    return EngineClaim(
        source="POSTING_BASE",
        source_row_ref="Sheet1!A2",
        timestamp=None,
        email="crew@test.com",
        staff_id=staff_id,
        name=name,
        position=None,
        base="DMK",
        claim_type="Posting",
        claim_month="FEBRUARY 2026",
        claimed_days=[3, 4],
        roster_links=["https://drive.google.com/file/d/abc123"],
    )


def _day_verdict(d: date = date(2026, 2, 3), verdict: str = "VALID") -> DayVerdict:
    return DayVerdict(claimed_date=d, verdict=verdict, rule="R8", reason=None)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_create_and_get_run(session):
    run = create_run(session, "FEBRUARY 2026")
    session.commit()
    fetched = get_run(session, run.id)
    assert fetched is not None
    assert fetched.cycle_month == "FEBRUARY 2026"
    assert fetched.status == "PENDING"
    assert fetched.progress == 0


def test_update_run_status(session):
    run = create_run(session, "FEBRUARY 2026")
    session.commit()
    started = datetime.now(tz=timezone.utc)
    update_run_status(
        session, run.id, status="RUNNING", progress=10, started_at=started
    )
    session.commit()
    fetched = get_run(session, run.id)
    assert fetched.status == "RUNNING"
    assert fetched.progress == 10
    assert fetched.started_at is not None


def test_update_run_counts(session):
    run = create_run(session, "FEBRUARY 2026")
    session.commit()
    update_run_status(
        session, run.id, status="DONE", progress=100,
        counts={"total": 5, "valid": 4, "invalid": 1},
        finished_at=datetime.now(tz=timezone.utc),
    )
    session.commit()
    fetched = get_run(session, run.id)
    assert fetched.counts == {"total": 5, "valid": 4, "invalid": 1}
    assert fetched.finished_at is not None


def test_update_run_not_found_raises(session):
    with pytest.raises(ValueError, match="not found"):
        update_run_status(session, uuid.uuid4(), status="DONE")


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def test_create_claim(session):
    run = create_run(session, "FEBRUARY 2026")
    claim = create_claim(session, run.id, _engine_claim())
    session.commit()
    assert claim.id is not None
    assert claim.staff_id == "1234567"
    assert claim.claimed_days == [3, 4]
    assert len(claim.roster_refs) == 1


def test_update_claim_roster_refs_enriches_stored_refs(session):
    run = create_run(session, "FEBRUARY 2026")
    claim = create_claim(session, run.id, _engine_claim())
    session.commit()
    # create_claim stores only the bare URL
    assert claim.roster_refs == [{"url": "https://drive.google.com/file/d/abc123"}]

    update_claim_roster_refs(
        session,
        claim.id,
        [{"url": "https://drive.google.com/file/d/abc123", "file_id": "abc123",
          "content_type": "application/pdf", "status": "OK"}],
    )
    session.commit()

    refreshed = get_claims_for_run(session, run.id)[0]
    assert refreshed.roster_refs[0]["content_type"] == "application/pdf"
    assert refreshed.roster_refs[0]["status"] == "OK"
    assert refreshed.roster_refs[0]["file_id"] == "abc123"


def test_update_claim_roster_refs_not_found_raises(session):
    with pytest.raises(ValueError, match="not found"):
        update_claim_roster_refs(session, uuid.uuid4(), [])


def test_get_claims_for_run(session):
    run = create_run(session, "FEBRUARY 2026")
    create_claim(session, run.id, _engine_claim("1111111", "Alice"))
    create_claim(session, run.id, _engine_claim("2222222", "Bob"))
    session.commit()
    claims = get_claims_for_run(session, run.id)
    assert len(claims) == 2


def test_claims_cascade_delete_with_run(session):
    run = create_run(session, "FEBRUARY 2026")
    create_claim(session, run.id, _engine_claim())
    session.commit()
    session.delete(run)
    session.commit()
    claims = get_claims_for_run(session, run.id)
    assert claims == []


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def test_write_and_read_verdicts(session):
    run = create_run(session, "FEBRUARY 2026")
    claim = create_claim(session, run.id, _engine_claim())
    session.commit()

    verdicts = [
        _day_verdict(date(2026, 2, 3), "VALID"),
        _day_verdict(date(2026, 2, 4), "VALID"),
    ]
    write_verdicts(session, claim.id, claim.staff_id, verdicts)
    session.commit()

    rows = get_verdicts_for_run(session, run.id)
    assert len(rows) == 2
    assert all(r.verdict == "VALID" for r in rows)
    assert all(r.staff_id == "1234567" for r in rows)


def test_write_verdicts_is_idempotent(session):
    run = create_run(session, "FEBRUARY 2026")
    claim = create_claim(session, run.id, _engine_claim())
    session.commit()

    v1 = [_day_verdict(date(2026, 2, 3), "NEEDS_REVIEW")]
    write_verdicts(session, claim.id, claim.staff_id, v1)
    session.commit()

    # Re-run replaces verdicts
    v2 = [_day_verdict(date(2026, 2, 3), "VALID")]
    write_verdicts(session, claim.id, claim.staff_id, v2)
    session.commit()

    rows = get_verdicts_for_run(session, run.id)
    assert len(rows) == 1
    assert rows[0].verdict == "VALID"


def test_verdict_staff_id_stored_for_dedup_index(session):
    run = create_run(session, "FEBRUARY 2026")
    claim = create_claim(session, run.id, _engine_claim(staff_id="9876543"))
    session.commit()
    write_verdicts(session, claim.id, "9876543", [_day_verdict()])
    session.commit()
    rows = get_verdicts_for_run(session, run.id)
    assert rows[0].staff_id == "9876543"


def test_verdict_backclaim_remark_stored(session):
    run = create_run(session, "FEBRUARY 2026")
    claim = create_claim(session, run.id, _engine_claim())
    session.commit()
    dv = DayVerdict(
        claimed_date=date(2026, 1, 31),
        verdict="VALID_BACKCLAIM",
        rule="R8",
        reason=None,
        remark="ตกเบิกเดือนมกราคม",
    )
    write_verdicts(session, claim.id, claim.staff_id, [dv])
    session.commit()
    rows = get_verdicts_for_run(session, run.id)
    assert rows[0].remark == "ตกเบิกเดือนมกราคม"


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_create_override(session):
    run = create_run(session, "FEBRUARY 2026")
    claim = create_claim(session, run.id, _engine_claim())
    session.commit()

    override = create_override(
        session, claim.id, decision="APPROVE", decided_by="admin@test.com", note="Verified OK"
    )
    session.commit()

    overrides = get_overrides_for_claim(session, claim.id)
    assert len(overrides) == 1
    assert overrides[0].decision == "APPROVE"
    assert overrides[0].decided_by == "admin@test.com"
    assert overrides[0].note == "Verified OK"


def test_override_without_note(session):
    run = create_run(session, "FEBRUARY 2026")
    claim = create_claim(session, run.id, _engine_claim())
    session.commit()
    create_override(session, claim.id, decision="REJECT", decided_by="admin@test.com")
    session.commit()
    overrides = get_overrides_for_claim(session, claim.id)
    assert overrides[0].note is None


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_write_audit_with_run_and_claim(session):
    run = create_run(session, "FEBRUARY 2026")
    claim = create_claim(session, run.id, _engine_claim())
    session.commit()

    write_audit(
        session,
        action="verdict_written",
        run_id=run.id,
        claim_id=claim.id,
        detail={"count": 2},
    )
    session.commit()

    from sqlalchemy import select
    from perdiem.db.models import Audit
    rows = session.scalars(select(Audit)).all()
    assert len(rows) == 1
    assert rows[0].action == "verdict_written"
    assert rows[0].detail == {"count": 2}


def test_write_audit_run_only(session):
    run = create_run(session, "FEBRUARY 2026")
    session.commit()
    write_audit(session, action="run_started", run_id=run.id)
    session.commit()

    from sqlalchemy import select
    from perdiem.db.models import Audit
    rows = session.scalars(select(Audit)).all()
    assert rows[0].claim_id is None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_set_and_get_config(session):
    set_config(session, "rate_thb_per_day", 400)
    session.commit()
    assert get_config(session, "rate_thb_per_day") == 400


def test_get_config_default(session):
    assert get_config(session, "nonexistent_key", default=42) == 42


def test_set_config_upsert(session):
    set_config(session, "outbound_flights", ["FD3013", "FD3015"])
    session.commit()
    set_config(session, "outbound_flights", ["FD3013"])
    session.commit()
    assert get_config(session, "outbound_flights") == ["FD3013"]


def test_set_config_jsonb_dict(session):
    value = {"routes": {"outbound": "DMK-HKT"}, "rate": 400}
    set_config(session, "rules_config", value)
    session.commit()
    assert get_config(session, "rules_config") == value


def test_get_all_config(session):
    set_config(session, "key_a", 1)
    set_config(session, "key_b", "hello")
    session.commit()
    all_cfg = get_all_config(session)
    assert all_cfg["key_a"] == 1
    assert all_cfg["key_b"] == "hello"
