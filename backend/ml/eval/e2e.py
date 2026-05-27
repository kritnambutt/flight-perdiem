"""End-to-end decision scorer for the eval harness (PD-ML-003).

Scores a *routing backend* — a function `row -> (route, confidence)` — against the
held-out month's admin/master ground truth. The status-quo baseline is
"review everything" (`review_all`): the manual process auto-passes nothing, so a
triage model's value (PD-ML-004) is exactly how much of that review queue it removes
without disagreeing with past admin decisions.

Ground truth: the admin `disposition` (the abundant, complete label). The master's
`approved` flag is a secondary check (partial coverage) reported alongside.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from ml.eval.metrics import E2EMetrics

Route = Literal["AUTO_PASS", "AUTO_REJECT", "SEND_TO_REVIEW"]
RouteFn = Callable[[dict], tuple[Route, float]]


def load_text_rows(dataset_dir: str | Path, split: str | None = None) -> list[dict]:
    """Load `text.jsonl` rows, optionally filtered to one split."""
    path = Path(dataset_dir) / "text.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path} (build it with PD-ML-002)")
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if split is None or row.get("split") == split:
                rows.append(row)
    return rows


def gold_route(disposition: str) -> Route:
    """Map the admin disposition to the route a perfect system would have taken."""
    if disposition == "APPROVED":
        return "AUTO_PASS"
    if disposition == "REJECTED":
        return "AUTO_REJECT"
    return "SEND_TO_REVIEW"  # DEFER_BACKCLAIM / REVIEW


def assert_no_leakage(rows: list[dict], expected_split: str = "test") -> None:
    """Fail loudly if any row is not from the held-out split (AC-5)."""
    leaked = {r.get("split") for r in rows} - {expected_split}
    if leaked:
        raise AssertionError(
            f"split leakage: expected only '{expected_split}', found {sorted(leaked)}"
        )


def review_all(_row: dict) -> tuple[Route, float]:
    """Baseline routing backend: the manual status quo reviews every claim."""
    return "SEND_TO_REVIEW", 1.0


def evaluate_e2e(route_fn: RouteFn, rows: list[dict]) -> E2EMetrics:
    """Score a routing backend over the given rows against the gold disposition."""
    n = len(rows)
    if n == 0:
        return E2EMetrics()

    auto_pass = auto_reject = review = 0
    auto_pass_correct = 0
    non_review = non_review_disagree = 0

    for row in rows:
        gold = gold_route(row["disposition"])
        route, _conf = route_fn(row)
        if route == "SEND_TO_REVIEW":
            review += 1
            continue
        non_review += 1
        if route != gold:
            non_review_disagree += 1
        if route == "AUTO_PASS":
            auto_pass += 1
            if gold == "AUTO_PASS":
                auto_pass_correct += 1
        elif route == "AUTO_REJECT":
            auto_reject += 1

    return E2EMetrics(
        auto_pass_match_master=(auto_pass_correct / auto_pass if auto_pass else 0.0),
        review_queue_frac=review / n,
        disagreement_rate=(non_review_disagree / non_review if non_review else 0.0),
        auto_pass_frac=auto_pass / n,
        auto_reject_frac=auto_reject / n,
        n_rows=n,
    )
