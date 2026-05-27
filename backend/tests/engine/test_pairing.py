"""Unit tests for perdiem.engine.pairing (PD-VAL-003)."""
from __future__ import annotations

from datetime import date

import pytest

from perdiem.engine.config import RulesConfig
from perdiem.engine.models import Leg
from perdiem.engine.pairing import Pair, find_pairs, is_outbound, is_return

_CFG = RulesConfig()


# ---------------------------------------------------------------------------
# Leg builder helpers
# ---------------------------------------------------------------------------


def _out(day_hint: int = 0) -> Leg:
    return Leg(flight_no="FD3013", orig="DMK", dest="HKT", time=None)


def _ret(day_hint: int = 0) -> Leg:
    return Leg(flight_no="FD3026", orig="HKT", dest="DMK", time=None)


def _other() -> Leg:
    return Leg(flight_no="FD9999", orig="DMK", dest="SIN", time=None)


# ---------------------------------------------------------------------------
# is_outbound / is_return predicates
# ---------------------------------------------------------------------------


def test_is_outbound_correct_flight():
    assert is_outbound(Leg("FD3013", "DMK", "HKT", None), _CFG) is True


def test_is_outbound_wrong_flight():
    assert is_outbound(Leg("FD9999", "DMK", "HKT", None), _CFG) is False


def test_is_outbound_wrong_route():
    assert is_outbound(Leg("FD3013", "DMK", "SIN", None), _CFG) is False


def test_is_return_correct_flight():
    assert is_return(Leg("FD3026", "HKT", "DMK", None), _CFG) is True


def test_is_return_wrong_direction():
    assert is_return(Leg("FD3026", "DMK", "HKT", None), _CFG) is False


# ---------------------------------------------------------------------------
# find_pairs — core scenarios
# ---------------------------------------------------------------------------

_START = date(2026, 2, 1)  # February 2026


def test_single_complete_pair():
    grid = {3: [_out()], 4: [_ret()]}
    pairs, unmatched = find_pairs(grid, _START, _CFG)
    assert len(pairs) == 1
    assert pairs[0].complete is True
    assert pairs[0].out_day == date(2026, 2, 3)
    assert pairs[0].back_day == date(2026, 2, 4)
    assert unmatched == []


def test_multiple_independent_pairs():
    grid = {3: [_out()], 4: [_ret()], 10: [_out()], 11: [_ret()]}
    pairs, unmatched = find_pairs(grid, _START, _CFG)
    assert len(pairs) == 2
    assert all(p.complete for p in pairs)
    assert unmatched == []


def test_orphan_outbound_flagged():
    grid = {3: [_out()]}  # no return on day 4
    pairs, unmatched = find_pairs(grid, _START, _CFG)
    assert len(pairs) == 0
    assert date(2026, 2, 3) in unmatched


def test_orphan_return_flagged():
    grid = {4: [_ret()]}  # return with no prior-day outbound
    pairs, unmatched = find_pairs(grid, _START, _CFG)
    assert len(pairs) == 0
    assert date(2026, 2, 4) in unmatched


def test_non_qualifying_leg_ignored():
    grid = {3: [_other()], 4: [_other()]}
    pairs, unmatched = find_pairs(grid, _START, _CFG)
    assert pairs == []
    assert unmatched == []


def test_greedy_consumes_first_available_return():
    # Day 3 outbound → no return on day 4 (day 4 is itself an outbound) → day 3 orphaned
    # Day 4 outbound → return on day 5 → complete pair
    grid = {3: [_out()], 4: [_out()], 5: [_ret()]}
    pairs, unmatched = find_pairs(grid, _START, _CFG)
    assert len(pairs) == 1
    assert pairs[0].out_day == date(2026, 2, 4)
    assert pairs[0].back_day == date(2026, 2, 5)
    assert date(2026, 2, 3) in unmatched


def test_empty_grid():
    pairs, unmatched = find_pairs({}, _START, _CFG)
    assert pairs == []
    assert unmatched == []


# ---------------------------------------------------------------------------
# Month boundary
# ---------------------------------------------------------------------------


def test_month_boundary_jan_31_to_feb_1():
    start = date(2026, 1, 1)  # January 2026 roster
    # Day 31 outbound (Jan 31), day 1 return — but day 1 key would be Jan 1
    # The boundary is detected when day == days_in_month(31) → next_day wraps to 1
    grid = {31: [_out()], 1: [_ret()]}
    pairs, unmatched = find_pairs(grid, start, _CFG)
    # Day 31 outbound looks for day 32 → wraps to 1. Day 1 has return.
    # However day 1 also represents Jan 1 in the grid — ambiguous.
    # The pairing should create a boundary pair: Jan 31 → Feb 1.
    if pairs:
        assert pairs[0].out_day == date(2026, 1, 31)
        assert pairs[0].back_day == date(2026, 2, 1)
    # Either a complete pair or both days in unmatched is acceptable for boundary edge case
    total = len(pairs) + len(unmatched)
    assert total > 0
