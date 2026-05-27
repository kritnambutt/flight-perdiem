"""Tests for the eval harness (PD-ML-003) — pure scorers + E2E + leakage guard."""
from __future__ import annotations

from datetime import date

import pytest

from ml.eval.e2e import assert_no_leakage, evaluate_e2e, gold_route, review_all
from ml.eval.scorers import (
    aggregate_field_metrics,
    score_dates,
    score_grid,
    score_name,
    score_staff_id,
)

# ---------------------------------------------------------------------------
# Per-field scorers
# ---------------------------------------------------------------------------

def test_staff_id_excludes_missing_gold() -> None:
    # Two gold labels (one missing) → denominator is 2, one hit.
    acc, n = score_staff_id(["1", "2", "3"], ["1", "x", None])
    assert n == 2
    assert acc == pytest.approx(0.5)


def test_name_match_uses_engine_normalize_threshold() -> None:
    # Diacritics/case/spacing differences still match at the engine threshold.
    rate, n = score_name(["Sawaros  Phanichvibul"], ["sawaros phanichvibul"], threshold=0.8)
    assert n == 1
    assert rate == 1.0


def test_dates_exact_match() -> None:
    acc, n = score_dates([date(2025, 8, 2), date(2025, 8, 3)], [date(2025, 8, 2), None])
    assert n == 1 and acc == 1.0


def test_grid_leg_precision_recall() -> None:
    pred = [(2, "FD3013", "DMK", "HKT"), (2, "FD3026", "HKT", "DMK")]
    gold = [(2, "FD3013", "DMK", "HKT"), (3, "FD3013", "DMK", "HKT")]
    tp, fp, fn = score_grid(pred, gold)
    assert (tp, fp, fn) == (1, 1, 1)
    fm = aggregate_field_metrics(
        staff_id=(1.0, 1), name=(1.0, 1), date_range=(1.0, 1),
        generated_date=(0.0, 0), grid_counts=(tp, fp, fn),
    )
    assert fm.grid_leg_precision == pytest.approx(0.5)
    assert fm.grid_leg_recall == pytest.approx(0.5)
    assert fm.coverage["generated_date"] == 0   # no gold → excluded


# ---------------------------------------------------------------------------
# End-to-end decision scoring
# ---------------------------------------------------------------------------

def test_gold_route_mapping() -> None:
    assert gold_route("APPROVED") == "AUTO_PASS"
    assert gold_route("REJECTED") == "AUTO_REJECT"
    assert gold_route("DEFER_BACKCLAIM") == "SEND_TO_REVIEW"
    assert gold_route("REVIEW") == "SEND_TO_REVIEW"


def test_review_all_baseline_reviews_everything() -> None:
    rows = [{"disposition": d, "split": "test"} for d in ("APPROVED", "REJECTED", "REVIEW")]
    m = evaluate_e2e(review_all, rows)
    assert m.review_queue_frac == 1.0
    assert m.auto_pass_frac == 0.0
    assert m.disagreement_rate == 0.0


def test_perfect_router_scores_clean() -> None:
    rows = [{"disposition": d, "split": "test"} for d in ("APPROVED", "APPROVED", "REJECTED")]
    perfect = lambda row: (gold_route(row["disposition"]), 1.0)  # noqa: E731
    m = evaluate_e2e(perfect, rows)
    assert m.auto_pass_match_master == 1.0
    assert m.disagreement_rate == 0.0
    assert m.auto_pass_frac == pytest.approx(2 / 3)


def test_auto_pass_match_penalises_wrong_autopass() -> None:
    rows = [{"disposition": "REJECTED", "split": "test"}]
    always_pass = lambda _row: ("AUTO_PASS", 1.0)  # noqa: E731
    m = evaluate_e2e(always_pass, rows)
    assert m.auto_pass_match_master == 0.0       # auto-passed a reject → wrong
    assert m.disagreement_rate == 1.0


def test_leakage_guard_raises_on_non_test_split() -> None:
    with pytest.raises(AssertionError):
        assert_no_leakage([{"split": "test"}, {"split": "train"}], expected_split="test")
    # All-test passes silently.
    assert_no_leakage([{"split": "test"}], expected_split="test")
