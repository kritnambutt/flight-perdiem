"""De-duplication and per-crew aggregation: R7 / F9 / F10.

PD-REP-001 — merges per-day verdicts from all submissions in a cycle,
de-duplicates by unique (staff_id, calendar_date), groups consecutive
payable days into ranges, and computes the per diem amount.
"""
from __future__ import annotations

from datetime import date, timedelta

from perdiem.engine.config import RulesConfig
from perdiem.engine.models import Claim, CrewResult, DayVerdict


# ---------------------------------------------------------------------------
# Range helpers
# ---------------------------------------------------------------------------


def _merge_consecutive(sorted_dates: list[date]) -> list[tuple[date, date]]:
    """Collapse a sorted list of dates into consecutive (start, end) ranges."""
    if not sorted_dates:
        return []
    ranges: list[tuple[date, date]] = []
    start = end = sorted_dates[0]
    for d in sorted_dates[1:]:
        if d - end == timedelta(days=1):
            end = d
        else:
            ranges.append((start, end))
            start = end = d
    ranges.append((start, end))
    return ranges


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def aggregate(
    claim_verdicts: list[tuple[Claim, list[DayVerdict]]],
    cfg: RulesConfig,
) -> list[CrewResult]:
    """
    Merge and de-duplicate verdicts across all submissions for a cycle.

    Returns one CrewResult per staff member, sorted by staff_id for
    deterministic output (N2 idempotency requirement).

    claim_verdicts: each element is (claim, its per-day verdicts as returned
    by validate_claim).  All submissions for the cycle — Posting Base, Late
    Submission, and any re-submissions — must be included.
    """
    # Payable unique days: (staff_id, date) → first contributing verdict
    payable_days: dict[str, dict[date, DayVerdict]] = {}
    # All claimed dates per staff (for reconciliation note)
    all_claimed: dict[str, set[date]] = {}
    # Back-claim remarks per staff
    back_remarks: dict[str, list[str]] = {}
    # Crew metadata: prefer the most recent non-empty name/email
    crew_meta: dict[str, tuple[str, str]] = {}  # staff_id → (name, email)

    for claim, verdicts in claim_verdicts:
        sid = (claim.staff_id or "").strip()
        if not sid:
            continue

        # Update crew metadata (last non-empty wins across re-submissions)
        if claim.name.strip():
            crew_meta[sid] = (claim.name.strip(), claim.email.strip())

        for v in verdicts:
            all_claimed.setdefault(sid, set()).add(v.claimed_date)

            if v.verdict in ("VALID", "VALID_BACKCLAIM"):
                # Dedup: first writer wins; we keep the audit link but don't double count
                payable_days.setdefault(sid, {})[v.claimed_date] = v
                if v.remark:
                    back_remarks.setdefault(sid, [])
                    if v.remark not in back_remarks[sid]:
                        back_remarks[sid].append(v.remark)

    results: list[CrewResult] = []
    for sid in sorted(payable_days.keys()):
        name, email = crew_meta.get(sid, ("", ""))
        dates = sorted(payable_days[sid].keys())
        periods = _merge_consecutive(dates)
        days = len(dates)
        total_thb = days * cfg.rate_thb_per_day

        # Build remark: back-claim notes + reconciliation flag
        remark_parts: list[str] = list(back_remarks.get(sid, []))
        claimed_count = len(all_claimed.get(sid, set()))
        if claimed_count > days:
            diff = claimed_count - days
            remark_parts.append(
                f"{diff} claimed day(s) not roster-proven — flagged for review"
            )

        results.append(
            CrewResult(
                staff_id=sid,
                name=name,
                email=email,
                periods=periods,
                days=days,
                total_thb=total_thb,
                remark="; ".join(remark_parts) if remark_parts else None,
            )
        )

    return results
