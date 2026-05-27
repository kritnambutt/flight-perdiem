"""Train the triage + reason classifier (PD-ML-004) — off-Pi, numpy-only.

Multinomial logistic regression (softmax) fit by full-batch gradient descent with L2
and balanced class weights — tiny, fast, fully serialisable to JSON, and scored at
inference by the pure `perdiem.engine.triage` function with **no training deps**.

Why not LightGBM (the story's first pick): keeping the stack numpy-only matches the
project's zero-extra-dep, Pi-friendly ethos and makes inference a genuinely pure
function. The eval harness (PD-ML-003) keeps the backend swappable if a tree model is
warranted later.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from ml.triage.calibrate import select_autopass_threshold
from ml.triage.features import build_matrix, feature_names, standardization
from perdiem.engine.triage import TRIAGE_CLASSES, reason_target, triage_target


@dataclass
class TrainResult:
    artifact: dict
    train_rows: int
    val_rows: int


def _one_hot(y: list[int], k: int):
    import numpy as np

    Y = np.zeros((len(y), k), dtype=float)
    for i, c in enumerate(y):
        Y[i, c] = 1.0
    return Y


def _balanced_weights(y: list[int], k: int):
    """Per-sample balanced weights, capped and mean-normalised for a stable gradient."""
    import numpy as np

    counts = np.bincount(np.asarray(y), minlength=k).astype(float)
    counts[counts == 0] = 1.0
    w = len(y) / (k * counts)        # balanced: rare classes weigh more
    w = np.clip(w, 0.0, 20.0)        # cap so a tiny class can't blow up the step
    sw = w[np.asarray(y)]
    return sw / sw.mean()            # mean weight = 1 → gradient scale stays sane


def _fit_softmax(X, y: list[int], k: int, *, balance: bool, l2=1e-3, lr=0.2, iters=3000):
    """Fit W (k×F), b (k) by weighted-CE gradient descent. Returns (W, b).

    `balance=False` keeps the natural class distribution — used for the triage head so
    the majority (APPROVED) confidence stays realistic for the auto-pass threshold.
    `balance=True` (reason head) up-weights rare rule_hints so they aren't ignored.
    """
    import numpy as np

    n, f = X.shape
    W = np.zeros((k, f), dtype=float)
    b = np.zeros(k, dtype=float)
    Y = _one_hot(y, k)
    sw = (_balanced_weights(y, k) if balance else np.ones(n))[:, None]   # (n,1)
    # numpy's matmul can raise spurious FP-flag warnings on some BLAS builds; the math
    # here is well-conditioned (clipped logits, standardised features), so silence them.
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        for _ in range(iters):
            logits = np.clip(X @ W.T + b, -30.0, 30.0)   # (n,k)
            logits -= logits.max(axis=1, keepdims=True)
            e = np.exp(logits)
            P = e / e.sum(axis=1, keepdims=True)
            diff = (P - Y) * sw                          # (n,k)
            W -= lr * (diff.T @ X / n + l2 * W)
            b -= lr * (diff.sum(axis=0) / n)
    return W, b


def _predict_proba(X, W, b):
    import numpy as np

    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        logits = np.clip(X @ W.T + b, -30.0, 30.0)
        logits -= logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        return e / e.sum(axis=1, keepdims=True)


def train(
    train_rows: list[dict],
    val_rows: list[dict],
    *,
    dataset_version: str,
    autopass_target_precision: float = 0.90,
    review_band: float = 0.10,
) -> TrainResult:
    """Train both heads and assemble the JSON artifact (thresholds picked on val)."""
    import numpy as np

    names = feature_names(train_rows)
    standardize = standardization(train_rows, names)
    X = build_matrix(train_rows, names, standardize)

    # Triage head.
    t_classes = list(TRIAGE_CLASSES)
    t_index = {c: i for i, c in enumerate(t_classes)}
    y_tri = [t_index[triage_target(r)] for r in train_rows]
    Wt, bt = _fit_softmax(X, y_tri, len(t_classes), balance=False)

    # Reason head (rule_hint). Classes = those seen in training.
    r_classes = sorted({reason_target(r) for r in train_rows})
    r_index = {c: i for i, c in enumerate(r_classes)}
    y_rea = [r_index[reason_target(r)] for r in train_rows]
    Wr, br = _fit_softmax(X, y_rea, len(r_classes), balance=True)

    # Calibrate the auto-pass abstention threshold on the validation split.
    autopass_min_conf = 0.85
    if val_rows:
        Xv = build_matrix(val_rows, names, standardize)
        Pv = _predict_proba(Xv, Wt, bt)
        ap_idx = t_index["AUTO_PASS"]
        confs, correct = [], []
        for i, row in enumerate(val_rows):
            pred = int(np.argmax(Pv[i]))
            if pred == ap_idx:
                confs.append(float(Pv[i, ap_idx]))
                correct.append(triage_target(row) == "AUTO_PASS")
        autopass_min_conf = select_autopass_threshold(
            confs, correct, target_precision=autopass_target_precision
        )

    artifact = {
        "model": "softmax-logreg",
        "trained_at": datetime.now(UTC).isoformat(),
        "dataset_version": dataset_version,
        "feature_names": names,
        "standardize": standardize,
        "triage": {"classes": t_classes, "W": Wt.tolist(), "b": bt.tolist()},
        "reason": {"classes": r_classes, "W": Wr.tolist(), "b": br.tolist()},
        "thresholds": {
            "autopass_min_conf": round(float(autopass_min_conf), 4),
            "review_band": review_band,
        },
    }
    return TrainResult(artifact=artifact, train_rows=len(train_rows), val_rows=len(val_rows))


def save_artifact(artifact: dict, path: str) -> None:
    import os

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(artifact, f)
