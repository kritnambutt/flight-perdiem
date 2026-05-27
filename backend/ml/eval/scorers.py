"""Pure per-field scorers for the eval harness (PD-ML-003).

Each scorer takes parallel ``(pred, gold)`` sequences and returns a rate plus the
denominator (rows that had a ground-truth label). A field with no gold label is
**excluded** from its denominator and counted in coverage — never silently scored as
a hit or a miss (AC error-scenario).

Name matching reuses the engine's `normalize` + the same fuzzy score and threshold
the rules use, so the harness can't drift from production behaviour.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from ml.eval.metrics import FieldMetrics
from perdiem.engine.identity import _fuzzy_score, normalize

GridLeg = tuple[int, str, str | None, str | None]  # (day, flight_no, orig, dest)


def _exact_rate(preds: Sequence[Any], golds: Sequence[Any]) -> tuple[float, int]:
    """Exact-match rate over rows that have a non-empty gold value."""
    hits = total = 0
    for pred, gold in zip(preds, golds):
        if gold in (None, ""):
            continue
        total += 1
        if pred == gold:
            hits += 1
    return (hits / total if total else 0.0), total


def score_staff_id(preds: Sequence[str | None], golds: Sequence[str | None]) -> tuple[float, int]:
    return _exact_rate(
        [str(p).strip() if p else p for p in preds],
        [str(g).strip() if g else g for g in golds],
    )


def score_name(
    preds: Sequence[str | None],
    golds: Sequence[str | None],
    threshold: float,
) -> tuple[float, int]:
    """Normalised fuzzy name-match rate at the engine's threshold."""
    hits = total = 0
    for pred, gold in zip(preds, golds):
        if not gold:
            continue
        total += 1
        if pred and _fuzzy_score(normalize(pred), normalize(gold)) >= threshold:
            hits += 1
    return (hits / total if total else 0.0), total


def score_dates(
    preds: Sequence[date | datetime | None],
    golds: Sequence[date | datetime | None],
) -> tuple[float, int]:
    return _exact_rate(list(preds), list(golds))


def score_grid(
    pred_legs: Sequence[GridLeg],
    gold_legs: Sequence[GridLeg],
) -> tuple[int, int, int]:
    """Return (tp, fp, fn) over leg tuples keyed on (day, flight_no, orig, dest).

    Time is ignored on purpose — it's outside the rule scope (R1/R2 use route +
    flight number). Multiplicity is collapsed to a set per the rules' day-leg model.
    """
    pred_set, gold_set = set(pred_legs), set(gold_legs)
    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    return tp, fp, fn


def aggregate_field_metrics(
    *,
    staff_id: tuple[float, int],
    name: tuple[float, int],
    date_range: tuple[float, int],
    generated_date: tuple[float, int],
    grid_counts: tuple[int, int, int],
) -> FieldMetrics:
    tp, fp, fn = grid_counts
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return FieldMetrics(
        staff_id_acc=staff_id[0],
        name_match_rate=name[0],
        date_range_acc=date_range[0],
        generated_date_acc=generated_date[0],
        grid_leg_precision=precision,
        grid_leg_recall=recall,
        coverage={
            "staff_id": staff_id[1],
            "name": name[1],
            "date_range": date_range[1],
            "generated_date": generated_date[1],
            "grid_legs_gold": tp + fn,
        },
    )
