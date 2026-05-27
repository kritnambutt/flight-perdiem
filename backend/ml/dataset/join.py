"""Form ⨝ master join and the blank-Remark labelling rule (PD-ML-002).

The master (CCD payroll) is the record of what was actually paid. We index every
master row by ``(staff_id, claimed-month, claimed-year)`` — derived from its
``Period`` dates, since a master row's *report* sheet is the pay month, not the
claimed month — then attach the approved outcome to each form submission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ml.dataset.models import Disposition
from ml.dataset.normalise import days_in_periods, parse_period
from ml.dataset.readers import MasterRow

# Join key: (staff_id, MONTH, YEAR) — MONTH uppercase canonical.
MasterKey = tuple[str, str, int]


@dataclass
class MasterMatch:
    """The reconciled outcome attached to a form row from the master."""

    periods: list[tuple[date, date]] = field(default_factory=list)
    days: int = 0
    total_thb: int = 0
    provenance: str | None = None


_EN_MONTH_NAME = {
    1: "JANUARY", 2: "FEBRUARY", 3: "MARCH", 4: "APRIL", 5: "MAY", 6: "JUNE",
    7: "JULY", 8: "AUGUST", 9: "SEPTEMBER", 10: "OCTOBER", 11: "NOVEMBER", 12: "DECEMBER",
}


def build_master_index(master_rows: list[MasterRow]) -> dict[MasterKey, MasterMatch]:
    """Index master rows by ``(staff_id, claimed-month, year)``.

    A row whose ``Period`` spans several months registers under each month's key (its
    days/THB split by the ranges falling in that month), so a claim is matched to the
    month it was actually flown — independent of which report sheet paid it.
    """
    index: dict[MasterKey, MasterMatch] = {}
    for mrow in master_rows:
        if not mrow.staff_id:
            continue
        periods = parse_period(mrow.period_raw)
        if not periods:
            continue
        # Group ranges by their start month/year.
        by_month: dict[tuple[str, int], list[tuple[date, date]]] = {}
        for start, end in periods:
            mk = (_EN_MONTH_NAME[start.month], start.year)
            by_month.setdefault(mk, []).append((start, end))
        for (month, year), ranges in by_month.items():
            key: MasterKey = (mrow.staff_id, month, year)
            days = days_in_periods(ranges)
            match = index.get(key)
            if match is None:
                match = MasterMatch(provenance=mrow.provenance)
                index[key] = match
            match.periods.extend(ranges)
            match.days += days
            # Total THB is recomputed from the canonical rate in build.py; the master's
            # own THB is kept only when this row maps to a single month.
            match.total_thb += _coerce_int(mrow.total_thb_raw) if len(by_month) == 1 else 0
    return index


def _coerce_int(raw: object) -> int:
    if raw is None:
        return 0
    try:
        return int(float(str(raw).strip()))
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# The blank-Remark labelling rule — the project's single decision gate.
# ---------------------------------------------------------------------------

def apply_blank_remark_rule(
    classified: tuple[Disposition, str] | None,
    matched_in_master: bool,
) -> tuple[Disposition, str, str]:
    """Resolve the final ``(disposition, rule_hint, label_source)`` for one row.

    THE BLANK-REMARK RULE (decision gate, confirm with admins — overview.md):
        A form row with a **blank admin Remark but present in the master** is treated
        as **APPROVED** (``label_source = master_reconciled``). It was paid, so the
        admin simply didn't annotate it.

    Otherwise:
      * an annotated remark wins (``label_source = admin_remark``);
      * a blank remark with **no** master match ⇒ ``REVIEW`` (unknown; never guessed).

    This is the one place the rule lives, so changing it touches a single function.
    """
    if classified is not None:
        disposition, rule_hint = classified
        return disposition, rule_hint, "admin_remark"
    # Blank remark.
    if matched_in_master:
        return "APPROVED", "NONE", "master_reconciled"
    return "REVIEW", "NONE", "admin_remark"
