"""Adapt the triage scorer into an eval-harness routing backend (PD-ML-003/004).

Bridges a dataset row → features → `triage()` → `(route, confidence)`, the shape the
PD-ML-003 E2E harness scores. Kept in `ml/` (not the engine) since it's only used by
offline evaluation.
"""
from __future__ import annotations

from perdiem.engine.triage import TriageConfig, build_features, triage


def make_route_fn(model_path: str, cfg: TriageConfig):
    """Return a `row -> (route, confidence)` function backed by the triage model."""

    def route_fn(row: dict) -> tuple[str, float]:
        result = triage(build_features(row), model_path, cfg)
        return result.route, result.confidence

    return route_fn
