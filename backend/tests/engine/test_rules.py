"""Unit tests for perdiem.engine.rules (PD-VAL-001)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from perdiem.engine.config import RulesConfig
from perdiem.engine.models import Claim, DayVerdict, ExtractedRoster, Field, Leg, RedAnnotation
from perdiem.engine.rules import (
    coverage_ok,
    flight_ok,
    month_route,
    proof_ok,
    route_ok,
    validate_claim,
)

_CFG = RulesConfig()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _claim(
    claimed_days: list[int],
    staff_id: str = "1234567",
    name: str = "John Doe",
    claim_month: str = "FEBRUARY 2026",
) -> Claim:
    return Claim(
        source="POSTING_BASE",
        source_row_ref="test!A1",
        timestamp=None,
        email="test@test.com",
        staff_id=staff_id,
        name=name,
        position=None,
        base="DMK",
        claim_type="Posting",
        claim_month=claim_month,
        claimed_days=claimed_days,
    )


def _roster(
    days: dict[int, list[Leg]],
    start: date = date(2026, 2, 1),
    end: date = date(2026, 2, 28),
    generated: datetime = datetime(2026, 2, 5, 10, 0),
    staff_id: str = "1234567",
    name: str = "John Doe",
) -> ExtractedRoster:
    return ExtractedRoster(
        staff_id=Field(staff_id, 1.0),
        name=Field(name, 0.9),
        start_date=Field(start, 1.0),
        end_date=Field(end, 1.0),
        generated_at=Field(generated, 1.0),
        grid=days,
        needs_review=[],
    )


def _no_red() -> RedAnnotation:
    return RedAnnotation(claimed_days=set(), confidence=0.0, bbox=None)


def _out() -> Leg:
    return Leg(flight_no="FD3013", orig="DMK", dest="HKT", time=None)


def _ret() -> Leg:
    return Leg(flight_no="FD3026", orig="HKT", dest="DMK", time=None)


# ---------------------------------------------------------------------------
# Pure predicate unit tests
# ---------------------------------------------------------------------------


def test_route_ok_outbound():
    assert route_ok(Leg("FD3013", "DMK", "HKT", None), _CFG) is True


def test_route_ok_return():
    assert route_ok(Leg("FD3026", "HKT", "DMK", None), _CFG) is True


def test_route_ok_wrong_route():
    assert route_ok(Leg("FD9999", "DMK", "SIN", None), _CFG) is False


def test_flight_ok_valid():
    assert flight_ok(Leg("FD3013", "DMK", "HKT", None), _CFG) is True


def test_flight_ok_wrong_number():
    assert flight_ok(Leg("FD9999", "DMK", "HKT", None), _CFG) is False


def test_coverage_ok_within():
    assert coverage_ok(date(2026, 2, 5), date(2026, 2, 1), date(2026, 2, 28)) is True


def test_coverage_ok_before_start():
    assert coverage_ok(date(2026, 1, 31), date(2026, 2, 1), date(2026, 2, 28)) is False


def test_coverage_ok_after_end():
    assert coverage_ok(date(2026, 3, 1), date(2026, 2, 1), date(2026, 2, 28)) is False


def test_proof_ok_generated_after():
    assert proof_ok(date(2026, 2, 3), datetime(2026, 2, 4, 0, 0)) is True


def test_proof_ok_same_day():
    assert proof_ok(date(2026, 2, 3), datetime(2026, 2, 3, 23, 59)) is True


def test_proof_ok_generated_before():
    assert proof_ok(date(2026, 2, 3), datetime(2026, 2, 2, 0, 0)) is False


def test_month_route_same_month():
    assert month_route(date(2026, 2, 3), date(2026, 2, 1)) == "VALID"


def test_month_route_different_month():
    assert month_route(date(2026, 1, 31), date(2026, 2, 1)) == "VALID_BACKCLAIM"


# ---------------------------------------------------------------------------
# validate_claim integration tests
# ---------------------------------------------------------------------------


def test_valid_complete_claim():
    # Day 3 outbound, day 4 return; claim covers days 3 and 4
    grid = {3: [_out()], 4: [_ret()]}
    claim = _claim([3, 4])
    roster = _roster(grid, generated=datetime(2026, 2, 5, 10, 0))
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    assert len(verdicts) == 2
    for v in verdicts:
        assert v.verdict in ("VALID", "VALID_BACKCLAIM"), v


def test_r5_id_mismatch_all_invalid():
    grid = {3: [_out()], 4: [_ret()]}
    claim = _claim([3, 4], staff_id="0000000")
    roster = _roster(grid)
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    assert all(v.verdict == "INVALID" for v in verdicts)
    assert all(v.rule == "R5" for v in verdicts)


def test_r6_day_outside_roster_range():
    grid = {3: [_out()]}
    claim = _claim([3])
    # Roster only covers Feb 5–28; day 3 is outside
    roster = _roster(grid, start=date(2026, 2, 5), end=date(2026, 2, 28))
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    assert verdicts[0].verdict == "INVALID"
    assert verdicts[0].rule == "R6"


def test_r4_generated_before_claimed_date():
    grid = {3: [_out()], 4: [_ret()]}
    claim = _claim([3, 4])
    # Generated before both claimed days
    roster = _roster(grid, generated=datetime(2026, 2, 1, 0, 0))
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    # Day 3: generated Feb 1 < claimed Feb 3 → INVALID R4
    # (roster predates the flight, so it cannot prove flown duty)
    assert verdicts[0].verdict == "INVALID"
    assert verdicts[0].rule == "R4"


def test_r1_off_route_leg_lists_flown_legs():
    # Day 3 has a leg, but it is not on the DMK↔HKT route.
    grid = {3: [Leg("FD9999", "DMK", "SIN", None)]}
    claim = _claim([3])
    roster = _roster(grid)
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    assert verdicts[0].verdict == "NEEDS_REVIEW"
    assert verdicts[0].rule == "R1"
    # Reason should report what *was* flown, not claim nothing was found.
    assert "FD9999" in verdicts[0].reason
    assert "DMK→SIN" in verdicts[0].reason


def test_r1_no_legs_extracted_reads_as_unread_grid():
    # Claimed day 3 has no legs in the grid at all (grid OCR gap, not a day off).
    # Day 4 is populated so the claim itself is otherwise plausible.
    grid = {4: [_ret()]}
    claim = _claim([3])
    roster = _roster(grid)
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    assert verdicts[0].verdict == "NEEDS_REVIEW"
    assert verdicts[0].rule == "R1"
    # The reason must point the reviewer at the image, not imply the flight
    # is genuinely absent.
    assert "could be read" in verdicts[0].reason
    assert "roster image" in verdicts[0].reason


def test_r2_right_route_wrong_flight():
    # DMK→HKT but wrong flight number → R2 INVALID
    grid = {3: [Leg("FD9999", "DMK", "HKT", None)]}
    claim = _claim([3])
    roster = _roster(grid)
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    assert verdicts[0].verdict == "INVALID"
    assert verdicts[0].rule == "R2"


def test_r3_orphan_outbound_needs_review():
    # Day 3 has outbound but day 4 has no return
    grid = {3: [_out()]}
    claim = _claim([3])
    roster = _roster(grid)
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    assert verdicts[0].verdict == "NEEDS_REVIEW"
    assert verdicts[0].rule == "R3"


def test_r8_backclaim_sets_remark():
    # Claim month is February, but day is in January → back-claim
    grid = {31: [_out()], 1: [_ret()]}
    # Roster covers Jan 31 – Feb 1
    roster = _roster(
        grid,
        start=date(2026, 1, 31),
        end=date(2026, 2, 1),
        generated=datetime(2026, 2, 2, 0, 0),
    )
    claim = _claim([31], claim_month="FEBRUARY 2026")
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    # Day 31 is January; cycle month is February → back-claim
    backclaim = [v for v in verdicts if v.verdict == "VALID_BACKCLAIM"]
    assert backclaim, verdicts
    assert backclaim[0].remark is not None
    assert "ตกเบิก" in backclaim[0].remark


def test_red_annotation_overrides_form_days():
    # Form claims days [3], but red box marks [4]
    grid = {3: [_out()], 4: [_ret()]}
    claim = _claim([3])
    red = RedAnnotation(claimed_days={4}, confidence=0.8, bbox=None)
    roster = _roster(grid, generated=datetime(2026, 2, 5, 0, 0))
    verdicts = validate_claim(claim, roster, red, _CFG)
    assert len(verdicts) == 1
    assert verdicts[0].claimed_date == date(2026, 2, 4)


def test_r5a_name_review_propagates():
    grid = {3: [_out()], 4: [_ret()]}
    claim = _claim([3, 4], name="Alice Wong")
    # Roster has completely different name but same staff ID
    roster = _roster(grid, name="Bob Zhang")
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    assert all(v.verdict == "NEEDS_REVIEW" for v in verdicts)
    assert all(v.rule == "R5a" for v in verdicts)


def test_empty_claimed_days_returns_empty():
    roster = _roster({})
    claim = _claim([])
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)
    assert verdicts == []


def test_unreadable_roster_dates_fall_back_to_cycle_month():
    # Regression: when OCR can't read the roster's date range, every claimed day
    # used to collapse to date.min (0001-01-01), so days [25,26,29,30] showed as a
    # single "1 Jan" entry and deduped to one. They must instead resolve to real,
    # distinct dates from the claimed cycle month.
    roster = ExtractedRoster(
        staff_id=Field("1234567", 1.0),
        name=Field("John Doe", 0.9),
        start_date=Field(None, 0.0),
        end_date=Field(None, 0.0),
        generated_at=Field(None, 0.0),
        grid={},
        needs_review=["start_date", "end_date"],
    )
    claim = _claim([25, 26, 29, 30], claim_month="JULY 2025")
    verdicts = validate_claim(claim, roster, _no_red(), _CFG)

    dates = [v.claimed_date for v in verdicts]
    assert dates == [
        date(2025, 7, 25),
        date(2025, 7, 26),
        date(2025, 7, 29),
        date(2025, 7, 30),
    ]
    # No roster range to verify against → each day is surfaced for review (R6).
    assert all(v.verdict == "NEEDS_REVIEW" and v.rule == "R6" for v in verdicts)
    # Four distinct dates so dedup keeps them as four claimed days, not one.
    assert len({v.claimed_date for v in verdicts}) == 4


# ---------------------------------------------------------------------------
# RulesConfig validation
# ---------------------------------------------------------------------------


def test_rules_config_validate_ok():
    _CFG.validate()  # should not raise


def test_rules_config_empty_outbound_flights():
    with pytest.raises(ValueError, match="outbound_flights"):
        RulesConfig(outbound_flights=set()).validate()


def test_rules_config_empty_return_flights():
    with pytest.raises(ValueError, match="return_flights"):
        RulesConfig(return_flights=set()).validate()
