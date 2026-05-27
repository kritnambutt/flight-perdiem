"""Eligibility rules engine: R1, R2, R4, R6, R8 + validate_claim orchestrator.

PD-VAL-001 — pure predicates with no I/O. Orchestrates identity (R5/R5a via
identity.py) and pairing (R3 via pairing.py) into one DayVerdict per claimed day.

R4 direction (was REQUIREMENTS §9 Q2, now resolved): roster generated_at must be
>= claimed_date (proof that the roster was printed after the flight). A generated
date that precedes the claimed day is a hard INVALID, not a review — the snapshot
predates the flight and cannot prove flown duty.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime

from perdiem.engine.config import RulesConfig
from perdiem.engine.identity import IdentityResult, check_identity
from perdiem.engine.models import Claim, DayVerdict, ExtractedRoster, Leg, RedAnnotation
from perdiem.engine.pairing import Pair, find_pairs, is_outbound, is_return


# ---------------------------------------------------------------------------
# Pure rule predicates
# ---------------------------------------------------------------------------


def route_ok(leg: Leg, cfg: RulesConfig) -> bool:
    """R1: leg must be on the DMK↔HKT route (either direction)."""
    return (leg.orig, leg.dest) in (
        (cfg.outbound_route[0], cfg.outbound_route[1]),
        (cfg.return_route[0], cfg.return_route[1]),
    )


def flight_ok(leg: Leg, cfg: RulesConfig) -> bool:
    """R2: flight number must be in the configured eligible set."""
    return is_outbound(leg, cfg) or is_return(leg, cfg)


def coverage_ok(claimed_date: date, start: date, end: date) -> bool:
    """R6: claimed day must fall within [start_date, end_date]."""
    return start <= claimed_date <= end


def proof_ok(claimed_date: date, generated_at: datetime) -> bool:
    """R4: roster generated_at must be on or after the claimed date."""
    return generated_at.date() >= claimed_date


def month_route(claimed_date: date, cycle_month: date) -> str:
    """R8: return 'VALID' if flown month == cycle month, else 'VALID_BACKCLAIM'."""
    flown_ym = (claimed_date.year, claimed_date.month)
    cycle_ym = (cycle_month.year, cycle_month.month)
    return "VALID" if flown_ym == cycle_ym else "VALID_BACKCLAIM"


# ---------------------------------------------------------------------------
# Cycle-month parsing
# ---------------------------------------------------------------------------

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_cycle_month(claim_month: str) -> date | None:
    """Parse 'FEBRUARY 2026' → date(2026, 2, 1). Returns None on failure."""
    parts = claim_month.strip().split()
    if len(parts) != 2:
        return None
    month_num = _MONTH_NAMES.get(parts[0].lower())
    if month_num is None:
        return None
    try:
        return date(int(parts[1]), month_num, 1)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# validate_claim — main orchestrator
# ---------------------------------------------------------------------------


def validate_claim(
    claim: Claim,
    roster: ExtractedRoster,
    red: RedAnnotation,
    cfg: RulesConfig,
) -> list[DayVerdict]:
    """
    Return one DayVerdict per claimed day.

    Claimed days are taken from the red annotation when available; the form's
    claimed_days list is the fallback.
    """
    # Determine which days to validate
    raw_days: list[int] = sorted(red.claimed_days) if red.claimed_days else sorted(claim.claimed_days)
    if not raw_days:
        return []

    # Roster start date needed for absolute-date conversion and coverage checks
    roster_start = roster.start_date.value
    roster_end = roster.end_date.value
    cycle_month = _parse_cycle_month(claim.claim_month)

    # Base month for turning day-of-month numbers into absolute dates: prefer the
    # roster's start date (from OCR); fall back to the claimed cycle month so the
    # dates stay real and *distinct* even when no roster could be read. Without
    # this fallback every claimed day collapsed to date.min (0001-01-01), which
    # showed up as a single "1 Jan" entry and made dedup count N days as one.
    date_base = roster_start or cycle_month

    def to_date(day: int) -> date:
        if date_base is None:
            return date.min  # no month context at all; will fail coverage check
        days_in = calendar.monthrange(date_base.year, date_base.month)[1]
        if 1 <= day <= days_in:
            return date(date_base.year, date_base.month, day)
        # Overflow into next month
        nm = date_base.month % 12 + 1
        ny = date_base.year + (1 if date_base.month == 12 else 0)
        return date(ny, nm, day - days_in)

    claimed_dates = [to_date(d) for d in raw_days]

    # -----------------------------------------------------------------------
    # R5 / R5a — identity (one decision covers all claimed days)
    # -----------------------------------------------------------------------
    identity: IdentityResult = check_identity(claim, roster, cfg)
    if identity.decision == "REJECT":
        return [
            DayVerdict(
                claimed_date=cd,
                verdict="INVALID",
                rule="R5",
                reason=identity.reason,
            )
            for cd in claimed_dates
        ]

    # -----------------------------------------------------------------------
    # R3 — pairing (find eligible pairs across the whole roster grid)
    # -----------------------------------------------------------------------
    if roster_start is not None:
        complete_pairs, unmatched_days = find_pairs(roster.grid, roster_start, cfg)
    else:
        complete_pairs, unmatched_days = [], []

    paired_dates: set[date] = set()
    for p in complete_pairs:
        paired_dates.add(p.out_day)
        paired_dates.add(p.back_day)

    # -----------------------------------------------------------------------
    # Per-day verdict
    # -----------------------------------------------------------------------
    verdicts: list[DayVerdict] = []
    for cd in claimed_dates:
        verdict = _check_day(
            claimed_date=cd,
            roster_start=roster_start,
            roster_end=roster_end,
            generated_at=roster.generated_at.value,
            grid=roster.grid,
            paired_dates=paired_dates,
            unmatched_days=unmatched_days,
            identity=identity,
            cycle_month=cycle_month,
            cfg=cfg,
        )
        verdicts.append(verdict)

    return verdicts


def _check_day(
    *,
    claimed_date: date,
    roster_start: date | None,
    roster_end: date | None,
    generated_at: datetime | None,
    grid: dict[int, list[Leg]],
    paired_dates: set[date],
    unmatched_days: list[date],
    identity: IdentityResult,
    cycle_month: date | None,
    cfg: RulesConfig,
) -> DayVerdict:
    # R6: coverage
    if roster_start is None or roster_end is None:
        return DayVerdict(
            claimed_date=claimed_date,
            verdict="NEEDS_REVIEW",
            rule="R6",
            reason="roster date range not readable",
        )
    if not coverage_ok(claimed_date, roster_start, roster_end):
        return DayVerdict(
            claimed_date=claimed_date,
            verdict="INVALID",
            rule="R6",
            reason=f"claimed date {claimed_date} outside roster range"
            f" [{roster_start} – {roster_end}]",
        )

    # R4: proof (open question on direction — see module docstring)
    if generated_at is None:
        return DayVerdict(
            claimed_date=claimed_date,
            verdict="NEEDS_REVIEW",
            rule="R4",
            reason="roster generated date not readable",
        )
    if not proof_ok(claimed_date, generated_at):
        # A roster printed before the claimed day can only reflect *scheduled*
        # (not flown) duty — it cannot prove the flight happened. There is
        # nothing for a reviewer to resolve, so this is a hard rejection.
        return DayVerdict(
            claimed_date=claimed_date,
            verdict="INVALID",
            rule="R4",
            reason=f"generated {generated_at.date()} is before claimed {claimed_date}",
        )

    # R1 / R2: qualifying leg on this day
    day_key = claimed_date.day
    legs = grid.get(day_key, [])
    qualifying = [lg for lg in legs if flight_ok(lg, cfg)]
    if not qualifying:
        # Check if any leg is on the right route but wrong flight number (R2)
        route_match = [lg for lg in legs if route_ok(lg, cfg)]
        if route_match:
            return DayVerdict(
                claimed_date=claimed_date,
                verdict="INVALID",
                rule="R2",
                reason=f"flight {route_match[0].flight_no} not in eligible set",
            )
        if not legs:
            # No legs were extracted for this day at all. On a real roster a
            # claimed day almost always has a flight, so an empty cell is far
            # more likely an OCR/grid read failure than a genuine day off. Say
            # so plainly — otherwise the reviewer may wrongly conclude the
            # flight is missing and reject a valid claim.
            return DayVerdict(
                claimed_date=claimed_date,
                verdict="NEEDS_REVIEW",
                rule="R1",
                reason="no flights could be read from the roster grid for this "
                "day — verify against the roster image",
            )
        # Legs were read, but none of them are on the DMK↔HKT route.
        flown = ", ".join(
            f"{lg.flight_no} {lg.orig or '?'}→{lg.dest or '?'}" for lg in legs
        )
        return DayVerdict(
            claimed_date=claimed_date,
            verdict="NEEDS_REVIEW",
            rule="R1",
            reason=f"no DMK↔HKT leg on this day (roster shows: {flown})",
        )

    # R3: pairing check
    if claimed_date in unmatched_days:
        return DayVerdict(
            claimed_date=claimed_date,
            verdict="NEEDS_REVIEW",
            rule="R3",
            reason="incomplete out-and-back pair",
        )

    # R5a: name review (staff ID matched but name uncertain)
    if identity.decision == "REVIEW":
        return DayVerdict(
            claimed_date=claimed_date,
            verdict="NEEDS_REVIEW",
            rule="R5a",
            reason=identity.reason,
        )

    # R8: month routing
    if cycle_month is None:
        return DayVerdict(
            claimed_date=claimed_date,
            verdict="NEEDS_REVIEW",
            rule="R8",
            reason=f"cannot parse cycle month from {claimed_date!r}",
        )
    verdict_type = month_route(claimed_date, cycle_month)
    remark = None
    if verdict_type == "VALID_BACKCLAIM":
        month_th = {
            1: "มกราคม", 2: "กุมภาพันธ์", 3: "มีนาคม", 4: "เมษายน",
            5: "พฤษภาคม", 6: "มิถุนายน", 7: "กรกฎาคม", 8: "สิงหาคม",
            9: "กันยายน", 10: "ตุลาคม", 11: "พฤศจิกายน", 12: "ธันวาคม",
        }
        remark = f"ตกเบิกเดือน{month_th.get(claimed_date.month, str(claimed_date.month))}"

    return DayVerdict(
        claimed_date=claimed_date,
        verdict=verdict_type,
        rule="R8",
        reason=None,
        remark=remark,
    )
