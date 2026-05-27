"""Out-and-back pairing algorithm: R3 / F8.

PD-VAL-003 — matches a DMK→HKT outbound on day N with a HKT→DMK return on
day N+1.  Boundary pairs (e.g. Jan 31 → Feb 1) are handled by calendar-date
arithmetic using the roster's start_date.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from perdiem.engine.config import RulesConfig
from perdiem.engine.models import Leg


@dataclass
class Pair:
    out_day: date
    back_day: date
    complete: bool


# ---------------------------------------------------------------------------
# Leg predicates (thin wrappers used by rules.py too)
# ---------------------------------------------------------------------------


def is_outbound(leg: Leg, cfg: RulesConfig) -> bool:
    return (
        leg.orig == cfg.outbound_route[0]
        and leg.dest == cfg.outbound_route[1]
        and leg.flight_no.upper() in cfg.outbound_flights
    )


def is_return(leg: Leg, cfg: RulesConfig) -> bool:
    return (
        leg.orig == cfg.return_route[0]
        and leg.dest == cfg.return_route[1]
        and leg.flight_no.upper() in cfg.return_flights
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_pairs(
    grid: dict[int, list[Leg]],
    roster_start: date,
    cfg: RulesConfig,
) -> tuple[list[Pair], list[date]]:
    """
    Return (complete_pairs, unmatched_days).

    grid keys are day-of-month integers. roster_start is used to build
    absolute calendar dates, handling month/year boundary rollovers.

    Unmatched days (orphan outbound or orphan return) are returned for
    NEEDS_REVIEW flagging by the rules engine.
    """
    def to_abs(day_of_month: int) -> date:
        """Convert a day-of-month key to an absolute date via roster_start."""
        year, month = roster_start.year, roster_start.month
        days_in_month = calendar.monthrange(year, month)[1]
        if day_of_month <= days_in_month:
            # try current month first
            try:
                return date(year, month, day_of_month)
            except ValueError:
                pass
        # overflow into next month
        next_month = month % 12 + 1
        next_year = year + (1 if month == 12 else 0)
        overflow = day_of_month - days_in_month
        return date(next_year, next_month, overflow)

    # Classify each day in the grid
    days_with_out: set[int] = set()
    days_with_return: set[int] = set()
    for day, legs in grid.items():
        if any(is_outbound(lg, cfg) for lg in legs):
            days_with_out.add(day)
        if any(is_return(lg, cfg) for lg in legs):
            days_with_return.add(day)

    pairs: list[Pair] = []
    consumed_out: set[int] = set()
    consumed_ret: set[int] = set()

    # Greedy forward pass: for each outbound, consume next-day return if present
    for day in sorted(days_with_out):
        if day in consumed_out:
            continue
        next_day = day + 1
        # Handle boundary: if next_day > days_in_month, wrap to 1
        days_in_month = calendar.monthrange(roster_start.year, roster_start.month)[1]
        if day == days_in_month:
            next_day = 1  # day 1 in the grid represents the first day of next month

        if next_day in days_with_return and next_day not in consumed_ret:
            pairs.append(
                Pair(
                    out_day=to_abs(day),
                    back_day=to_abs(next_day) if day < days_in_month else to_abs(day) + timedelta(days=1),
                    complete=True,
                )
            )
            consumed_out.add(day)
            consumed_ret.add(next_day)
        else:
            # Orphan outbound
            pairs.append(Pair(out_day=to_abs(day), back_day=to_abs(day), complete=False))
            consumed_out.add(day)

    # Orphan returns not consumed
    unmatched: list[date] = [
        d for p in pairs if not p.complete for d in [p.out_day]
    ] + [to_abs(day) for day in sorted(days_with_return) if day not in consumed_ret]

    # Keep only complete pairs in the returned pair list; incomplete → unmatched
    complete_pairs = [p for p in pairs if p.complete]

    return complete_pairs, unmatched
