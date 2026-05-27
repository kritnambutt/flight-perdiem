"""Triage + rejection-reason inference (PD-ML-004) — pure scorer.

Routes a claim to ``AUTO_PASS | AUTO_REJECT | SEND_TO_REVIEW`` and predicts a ranked
rejection-reason hint, from a serialised model artifact. It **routes, it does not
decide** — R1–R8 stay the auditable arbiter (N1); low confidence abstains to review.

Engine purity: this module owns the *pure feature spec* (so training and inference
never drift) and lazy-imports numpy only inside the scorer, so importing the engine
stays light and needs no training deps (AC-5). Training (`ml/triage/`) imports the
feature builder *from here* — the engine never imports `ml`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

Route = Literal["AUTO_PASS", "AUTO_REJECT", "SEND_TO_REVIEW"]

MONTHS = (
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
)
# Numeric features get standardised (mean/std) at train time; the rest are 0/1.
NUMERIC_FEATURES = ("n_claimed_days", "n_roster_links")

TRIAGE_CLASSES: tuple[Route, ...] = ("AUTO_PASS", "AUTO_REJECT", "SEND_TO_REVIEW")


@dataclass
class TriageConfig:
    enabled: bool = False
    model_path: str = "data/ml/models/triage.json"
    autopass_min_conf: float = 0.85
    review_band: float = 0.10   # abstain if top-2 margin is below this


@dataclass
class TriageResult:
    route: Route
    confidence: float
    reason_hint: list[tuple[str, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure feature spec — shared by training (ml/triage) and inference (here)
# ---------------------------------------------------------------------------

def build_features(row: dict) -> dict[str, float]:
    """Derive non-leaky features from a claim row (no free-text outcome used).

    Inputs only: form `source`, `claim_type`, `cycle_month`, claimed-day count,
    roster-link count, staff-id presence. Never reads `disposition`, `reason_text`,
    `rule_hint`, or `approved` — those are labels.
    """
    feats: dict[str, float] = {}
    feats["src_late"] = 1.0 if row.get("source") == "LATE" else 0.0

    ct = (row.get("claim_type") or "").lower()
    feats["ct_layover"] = 1.0 if "layover" in ct else 0.0
    feats["ct_posting"] = 1.0 if "posting" in ct else 0.0
    feats["ct_present"] = 1.0 if ct else 0.0

    cm = row.get("cycle_month") or ["", 0]
    month = cm[0] if isinstance(cm, list | tuple) and cm else ""
    for m in MONTHS:
        feats[f"month_{m}"] = 1.0 if month == m else 0.0

    feats["n_claimed_days"] = float(len(row.get("claimed_days") or []))
    feats["n_roster_links"] = float(len(row.get("roster_links") or []))
    feats["has_staff_id"] = 1.0 if row.get("staff_id") else 0.0
    return feats


def triage_target(row: dict) -> Route:
    """Gold triage label from the admin disposition."""
    disp = row.get("disposition")
    if disp == "APPROVED":
        return "AUTO_PASS"
    if disp == "REJECTED":
        return "AUTO_REJECT"
    return "SEND_TO_REVIEW"


def reason_target(row: dict) -> str:
    """Gold reason label (rule_hint) for the reason head."""
    return row.get("rule_hint") or "NONE"


# ---------------------------------------------------------------------------
# Inference (lazy numpy)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _load_model(model_path: str) -> dict:
    with open(model_path, encoding="utf-8") as f:
        return json.load(f)


def _vectorize(features: dict[str, float], artifact: dict):
    import numpy as np

    names = artifact["feature_names"]
    standardize = artifact.get("standardize", {})
    x = np.zeros(len(names), dtype=float)
    for i, name in enumerate(names):
        v = float(features.get(name, 0.0))
        if name in standardize:
            mean, std = standardize[name]
            v = (v - mean) / std if std else 0.0
        x[i] = v
    return x


def _softmax(logits):
    import numpy as np

    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        z = np.clip(logits, -30.0, 30.0)
        z -= np.max(z)
        e = np.exp(z)
        return e / e.sum()


def _head_probs(x, head: dict):
    import numpy as np

    W = np.asarray(head["W"], dtype=float)   # (K, F)
    b = np.asarray(head["b"], dtype=float)   # (K,)
    return _softmax(W @ x + b), head["classes"]


def triage(features: dict, model_path: str, cfg: TriageConfig) -> TriageResult:
    """Score one claim's features → TriageResult.

    Abstains to ``SEND_TO_REVIEW`` when an auto-pass/reject is not confident enough or
    the top-2 margin is within the review band — never a silent auto-decision (N1).
    Raises ``FileNotFoundError`` if the artifact is missing; use ``safe_triage`` for
    the rules-only fallback.
    """
    artifact = _load_model(model_path)
    x = _vectorize(features, artifact)

    probs, classes = _head_probs(x, artifact["triage"])
    order = sorted(range(len(classes)), key=lambda i: probs[i], reverse=True)
    top, second = order[0], order[1] if len(order) > 1 else order[0]
    route: Route = classes[top]
    confidence = float(probs[top])
    margin = float(probs[top] - probs[second])

    # Abstention: uncertain margin, or a non-confident auto-pass/reject → review.
    if route != "SEND_TO_REVIEW" and (
        margin < cfg.review_band or confidence < cfg.autopass_min_conf
    ):
        route = "SEND_TO_REVIEW"

    reason_hint: list[tuple[str, float]] = []
    if route != "AUTO_PASS" and "reason" in artifact:
        rp, rclasses = _head_probs(x, artifact["reason"])
        ranked = sorted(zip(rclasses, (float(p) for p in rp)), key=lambda kv: kv[1], reverse=True)
        reason_hint = ranked[:3]

    return TriageResult(route=route, confidence=confidence, reason_hint=reason_hint)


def predict_reason(features: dict, model_path: str) -> list[tuple[str, float]]:
    """Ranked `(rule_hint, prob)` from the reason head — independent of the route.

    Used to report reason-hint accuracy (PD-ML-004 AC-2) and to surface the hint in
    the Exceptions UI. Returns ``[]`` if the artifact has no reason head.
    """
    artifact = _load_model(model_path)
    if "reason" not in artifact:
        return []
    x = _vectorize(features, artifact)
    probs, classes = _head_probs(x, artifact["reason"])
    return sorted(zip(classes, (float(p) for p in probs)), key=lambda kv: kv[1], reverse=True)


def safe_triage(features: dict, cfg: TriageConfig) -> TriageResult | None:
    """Triage with the rules-only fallback (AC error-scenario).

    Returns ``None`` (triage disabled → caller keeps the rule verdict) when triage is
    off or the model file is missing/unreadable — never crashes the run.
    """
    import logging
    import os

    if not cfg.enabled:
        return None
    if not os.path.exists(cfg.model_path):
        logging.getLogger(__name__).warning(
            "triage model missing at %s — falling back to rules-only", cfg.model_path
        )
        return None
    try:
        return triage(features, cfg.model_path, cfg)
    except Exception as exc:  # noqa: BLE001 — triage must never break a run
        logging.getLogger(__name__).warning("triage failed (%s) — rules-only", exc)
        return None
