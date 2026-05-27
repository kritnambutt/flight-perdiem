"""Unit tests for perdiem.engine.dedup (PD-REP-001)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from perdiem.engine.config import RulesConfig
from perdiem.engine.dedup import _merge_consecutive, aggregate
from perdiem.engine.models import Claim, DayVerdict, CrewResult

_CFG = RulesConfig()  # 400 THB/day


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _claim(
    staff_id: str = "1234567",
    name: str = "John Doe",
    email: str = "john@test.com",
    claimed_days: list[int] | None = None,
    source: str = "POSTING_BASE",
) -> Claim:
    return Claim(
        source=source,
        source_row_ref="test!A1",
        timestamp=None,
        email=email,
        staff_id=staff_id,
        name=name,
        position=None,
        base="DMK",
        claim_type="Posting",
        claim_month="FEBRUARY 2026",
        claimed_days=claimed_days or [],
    )


def _verdict(
    d: date,
    verdict: str = "VALID",
    rule: str = "R8",
    reason: str | None = None,
    remark: str | None = None,
) -> DayVerdict:
    return DayVerdict(
        claimed_date=d,
        verdict=verdict,
        rule=rule,
        reason=reason,
        remark=remark,
    )


# ---------------------------------------------------------------------------
# _merge_consecutive
# ---------------------------------------------------------------------------


def test_merge_single_date():
    assert _merge_consecutive([date(2026, 2, 3)]) == [(date(2026, 2, 3), date(2026, 2, 3))]


def test_merge_two_consecutive():
    result = _merge_consecutive([date(2026, 2, 3), date(2026, 2, 4)])
    assert result == [(date(2026, 2, 3), date(2026, 2, 4))]


def test_merge_gap_creates_two_ranges():
    result = _merge_consecutive([date(2026, 2, 3), date(2026, 2, 5)])
    assert result == [(date(2026, 2, 3), date(2026, 2, 3)), (date(2026, 2, 5), date(2026, 2, 5))]


def test_merge_three_consecutive():
    dates = [date(2026, 2, 3), date(2026, 2, 4), date(2026, 2, 5)]
    assert _merge_consecutive(dates) == [(date(2026, 2, 3), date(2026, 2, 5))]


def test_merge_two_separate_ranges():
    dates = [
        date(2026, 1, 26), date(2026, 1, 27),
        date(2026, 2, 10), date(2026, 2, 11),
    ]
    assert _merge_consecutive(dates) == [
        (date(2026, 1, 26), date(2026, 1, 27)),
        (date(2026, 2, 10), date(2026, 2, 11)),
    ]


def test_merge_empty_returns_empty():
    assert _merge_consecutive([]) == []


# ---------------------------------------------------------------------------
# aggregate — basic cases
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty():
    assert aggregate([], _CFG) == []


def test_single_valid_day():
    d = date(2026, 2, 3)
    cv = [(_claim(), [_verdict(d)])]
    results = aggregate(cv, _CFG)
    assert len(results) == 1
    r = results[0]
    assert r.staff_id == "1234567"
    assert r.days == 1
    assert r.total_thb == 400
    assert r.periods == [(d, d)]


def test_amount_is_days_times_rate():
    d3, d4 = date(2026, 2, 3), date(2026, 2, 4)
    cv = [(_claim(), [_verdict(d3), _verdict(d4)])]
    results = aggregate(cv, _CFG)
    assert results[0].days == 2
    assert results[0].total_thb == 800


def test_invalid_verdicts_excluded():
    d = date(2026, 2, 3)
    cv = [(_claim(), [_verdict(d, verdict="INVALID", rule="R5")])]
    assert aggregate(cv, _CFG) == []


def test_needs_review_verdicts_excluded():
    d = date(2026, 2, 3)
    cv = [(_claim(), [_verdict(d, verdict="NEEDS_REVIEW", rule="R3")])]
    assert aggregate(cv, _CFG) == []


def test_valid_backclaim_included():
    d = date(2026, 1, 31)
    cv = [(_claim(), [_verdict(d, verdict="VALID_BACKCLAIM", remark="ตกเบิกเดือนมกราคม")])]
    results = aggregate(cv, _CFG)
    assert len(results) == 1
    assert results[0].days == 1


# ---------------------------------------------------------------------------
# aggregate — deduplication (R7)
# ---------------------------------------------------------------------------


def test_same_day_two_submissions_counted_once():
    d = date(2026, 2, 3)
    cv = [
        (_claim(source="POSTING_BASE"), [_verdict(d)]),
        (_claim(source="LATE"), [_verdict(d)]),
    ]
    results = aggregate(cv, _CFG)
    assert results[0].days == 1


def test_overlapping_ranges_deduped():
    d3, d4 = date(2026, 2, 3), date(2026, 2, 4)
    cv = [
        (_claim(), [_verdict(d3), _verdict(d4)]),
        (_claim(), [_verdict(d3)]),  # re-submission overlapping day 3
    ]
    results = aggregate(cv, _CFG)
    assert results[0].days == 2


# ---------------------------------------------------------------------------
# aggregate — range grouping
# ---------------------------------------------------------------------------


def test_consecutive_days_one_range():
    dates = [date(2026, 2, 3), date(2026, 2, 4), date(2026, 2, 5)]
    cv = [(_claim(), [_verdict(d) for d in dates])]
    r = aggregate(cv, _CFG)[0]
    assert r.periods == [(date(2026, 2, 3), date(2026, 2, 5))]


def test_non_consecutive_days_two_ranges():
    dates = [date(2026, 1, 26), date(2026, 1, 27), date(2026, 2, 10), date(2026, 2, 11)]
    cv = [(_claim(), [_verdict(d) for d in dates])]
    r = aggregate(cv, _CFG)[0]
    assert r.periods == [
        (date(2026, 1, 26), date(2026, 1, 27)),
        (date(2026, 2, 10), date(2026, 2, 11)),
    ]


# ---------------------------------------------------------------------------
# aggregate — remarks
# ---------------------------------------------------------------------------


def test_backclaim_remark_propagated():
    d = date(2026, 1, 31)
    remark = "ตกเบิกเดือนมกราคม"
    cv = [(_claim(), [_verdict(d, verdict="VALID_BACKCLAIM", remark=remark)])]
    r = aggregate(cv, _CFG)[0]
    assert remark in (r.remark or "")


def test_duplicate_backclaim_remark_deduplicated():
    d3, d4 = date(2026, 1, 30), date(2026, 1, 31)
    remark = "ตกเบิกเดือนมกราคม"
    cv = [(_claim(), [
        _verdict(d3, verdict="VALID_BACKCLAIM", remark=remark),
        _verdict(d4, verdict="VALID_BACKCLAIM", remark=remark),
    ])]
    r = aggregate(cv, _CFG)[0]
    assert (r.remark or "").count(remark) == 1


def test_reconciliation_note_when_claim_exceeds_proven():
    # Claim says 3 days, but only 2 are valid (one is NEEDS_REVIEW)
    d3, d4, d5 = date(2026, 2, 3), date(2026, 2, 4), date(2026, 2, 5)
    cv = [(_claim(), [
        _verdict(d3),
        _verdict(d4),
        _verdict(d5, verdict="NEEDS_REVIEW", rule="R3"),
    ])]
    r = aggregate(cv, _CFG)[0]
    assert r.days == 2
    assert "1 claimed day(s) not roster-proven" in (r.remark or "")


def test_no_reconciliation_note_when_all_proven():
    d3, d4 = date(2026, 2, 3), date(2026, 2, 4)
    cv = [(_claim(), [_verdict(d3), _verdict(d4)])]
    r = aggregate(cv, _CFG)[0]
    assert r.remark is None


# ---------------------------------------------------------------------------
# aggregate — multiple crew, stable ordering
# ---------------------------------------------------------------------------


def test_multiple_crew_sorted_by_staff_id():
    d = date(2026, 2, 3)
    cv = [
        (_claim(staff_id="9999999", name="Zara Z"), [_verdict(d)]),
        (_claim(staff_id="1111111", name="Alice A"), [_verdict(d)]),
    ]
    results = aggregate(cv, _CFG)
    assert results[0].staff_id == "1111111"
    assert results[1].staff_id == "9999999"


def test_missing_staff_id_skipped():
    d = date(2026, 2, 3)
    cv = [(_claim(staff_id=""), [_verdict(d)])]
    assert aggregate(cv, _CFG) == []


def test_crew_metadata_preserved():
    d = date(2026, 2, 3)
    cv = [(_claim(name="Sawaros P", email="sw@test.com"), [_verdict(d)])]
    r = aggregate(cv, _CFG)[0]
    assert r.name == "Sawaros P"
    assert r.email == "sw@test.com"
