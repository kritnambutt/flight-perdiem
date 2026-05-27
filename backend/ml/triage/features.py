"""Feature assembly for triage training (PD-ML-004).

The *pure feature spec* lives in `perdiem.engine.triage` so training and inference can
never drift (and the engine never imports `ml`). This module re-exports it and adds
the train-time matrix/standardisation helpers (numpy).
"""
from __future__ import annotations

# Single source of truth for the feature spec + labels (engine-owned).
from perdiem.engine.triage import (  # noqa: F401
    MONTHS,
    NUMERIC_FEATURES,
    build_features,
    reason_target,
    triage_target,
)


def feature_names(rows: list[dict]) -> list[str]:
    """Stable, ordered feature-name list (build_features always emits the same keys)."""
    if not rows:
        return []
    return list(build_features(rows[0]).keys())


def standardization(rows: list[dict], names: list[str]) -> dict[str, list[float]]:
    """Per-numeric-feature (mean, std) over the training rows."""
    import numpy as np

    stats: dict[str, list[float]] = {}
    for name in names:
        if name not in NUMERIC_FEATURES:
            continue
        vals = np.array([build_features(r).get(name, 0.0) for r in rows], dtype=float)
        std = float(vals.std())
        stats[name] = [float(vals.mean()), std if std else 1.0]
    return stats


def build_matrix(rows: list[dict], names: list[str], standardize: dict[str, list[float]]):
    """Build the standardised feature matrix X (N×F) for the given rows."""
    import numpy as np

    X = np.zeros((len(rows), len(names)), dtype=float)
    for i, row in enumerate(rows):
        feats = build_features(row)
        for j, name in enumerate(names):
            v = float(feats.get(name, 0.0))
            if name in standardize:
                mean, std = standardize[name]
                v = (v - mean) / std if std else 0.0
            X[i, j] = v
    return X
