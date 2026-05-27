"""Dataset row models for the ML dataset builder (PD-ML-002).

These live **outside** ``perdiem/engine`` — this is pure data prep, not part of the
validation engine. They may import the engine (a pure library), but the engine must
never import this package.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

Disposition = Literal["APPROVED", "REJECTED", "DEFER_BACKCLAIM", "REVIEW"]
LabelSource = Literal["admin_remark", "master_reconciled", "regex_bootstrap"]
Split = Literal["train", "val", "test"]
Source = Literal["POSTING_BASE", "LATE"]

# rule_hint vocabulary tagged onto a disposition (see normalise.REMARK_RULE_MAP).
RULE_HINTS = {"R4", "R6", "R7", "R8", "DOC_INCOMPLETE", "OUT_OF_SCOPE", "NONE"}


@dataclass
class TextRow:
    """One admin-decided form submission (all history, no image needed).

    This is the abundant label tier feeding triage / reason classifiers
    (PD-ML-003/004). ``disposition`` is the gold WS-3 label.
    """

    provenance: str                          # "<workbook>!<sheet>!<row>"
    source: Source
    staff_id: str | None
    name: str
    cycle_month: tuple[str, int]             # ("AUGUST", 2025)
    claimed_days: list[int]
    claim_type: str | None
    crew_remark: str | None
    disposition: Disposition
    reason_text: str | None
    rule_hint: str                           # one of RULE_HINTS
    approved: bool
    approved_periods: list[tuple[date, date]]
    approved_days: int
    total_thb: int
    split: Split
    label_source: LabelSource
    # Provenance / audit flags surfaced in the quality report.
    unmatched_master: bool = False
    roster_links: list[str] = field(default_factory=list)

    def to_jsonable(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict (dates → ISO strings, tuples → lists)."""
        d = asdict(self)
        d["cycle_month"] = list(self.cycle_month)
        d["approved_periods"] = [
            [start.isoformat(), end.isoformat()] for start, end in self.approved_periods
        ]
        return d


@dataclass
class VisionRow:
    """One submission whose roster Drive link resolves to a cached image.

    The scarce label tier feeding the Donut roster reader (PD-ML-006). Field labels
    are **weak/derived** — ``label_source`` records how, so the reader can weight them.
    """

    provenance: str
    image_path: str                          # cached roster file (<file_id>.<ext>)
    fields: dict[str, Any]                   # staff_id/name/date_range/generated_at/grid (weak)
    label_source: str
    split: Split

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)
