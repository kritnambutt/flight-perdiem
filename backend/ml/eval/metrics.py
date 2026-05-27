"""Metric dataclasses for the ML eval harness (PD-ML-003).

`FieldMetrics` measures *extraction* quality on the vision split; `E2EMetrics`
measures the *decision* quality (routing vs the admin/master ground truth) on the
held-out month. Both carry coverage counts so accuracy is never silently inflated
when a field has no ground-truth label.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class FieldMetrics:
    """Per-field extraction accuracy on the vision split."""

    staff_id_acc: float = 0.0
    name_match_rate: float = 0.0
    date_range_acc: float = 0.0
    generated_date_acc: float = 0.0
    grid_leg_precision: float = 0.0
    grid_leg_recall: float = 0.0
    # Denominators (rows that actually had a ground-truth label for the field).
    coverage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class E2EMetrics:
    """End-to-end decision quality of a routing backend on the held-out month."""

    auto_pass_match_master: float = 0.0   # headline KPI: of AUTO_PASS rows, frac truly APPROVED
    review_queue_frac: float = 0.0        # frac routed to SEND_TO_REVIEW
    disagreement_rate: float = 0.0        # of non-review routes, frac that disagree with gold
    auto_pass_frac: float = 0.0           # frac auto-passed (coverage of the headline KPI)
    auto_reject_frac: float = 0.0
    n_rows: int = 0

    def to_dict(self) -> dict:
        return asdict(self)
