"""Abstention-threshold selection for triage (PD-ML-004).

Picks the auto-pass confidence cut on the **validation** split so auto-passed claims
meet a target precision against the gold disposition. Keeping this separate makes the
abstention policy auditable and tunable without retraining.
"""
from __future__ import annotations


def select_autopass_threshold(
    autopass_confidences: list[float],
    autopass_correct: list[bool],
    *,
    target_precision: float = 0.97,
    default: float = 0.85,
) -> float:
    """Smallest confidence cut whose auto-passed subset hits `target_precision`.

    `autopass_confidences[i]` is the model's confidence for a row it would auto-pass;
    `autopass_correct[i]` whether that auto-pass agrees with the gold disposition.
    Falls back to `default` when no cut reaches the target (or there are no auto-passes).
    """
    if not autopass_confidences:
        return default

    pairs = sorted(zip(autopass_confidences, autopass_correct), key=lambda p: p[0])
    n = len(pairs)
    # Try each confidence as the cut: keep rows at or above it, measure precision.
    best: float | None = None
    for i in range(n):
        cut = pairs[i][0]
        kept = [c for conf, c in pairs if conf >= cut]
        if not kept:
            continue
        precision = sum(kept) / len(kept)
        if precision >= target_precision:
            best = cut
            break
    return float(best) if best is not None else default
