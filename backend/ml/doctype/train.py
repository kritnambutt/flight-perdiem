"""Train the doc-type / quality classifier (PD-ML-005) — off-Pi, numpy-only.

Binary/3-class softmax logistic regression over hand-crafted image features.
Same approach as the triage classifier (PD-ML-004): lightweight, fully
serialisable to JSON, and scored at inference with no training deps.

Usage (from the repo root):
    backend/.venv/bin/python scripts/train_doctype.py

The script reads labelled examples from two sources:
  1. docs/example-files/roster-attached-files/correct/    → VALID_ROSTER
  2. docs/example-files/roster-attached-files/incorrect/  → NOT_A_ROSTER
     (files whose name contains "invalid formatted")
     Other incorrect files are valid roster images that fail *rule* checks,
     not document-type checks, so they are labelled VALID_ROSTER.

UNREADABLE examples are synthesised via extreme augmentation of VALID_ROSTER
images (severe downscale, near-black, near-white, extreme JPEG artefacts).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ml.doctype.augment import augment_image, make_unreadable_variants
from perdiem.engine.ocr.doctype import NUMERIC_FEATURES, extract_image_features

logger = logging.getLogger(__name__)

# Labelling convention for the incorrect/ fixture filenames.
_INVALID_FORMAT_MARKER = "invalid formatted"

CLASSES = ["VALID_ROSTER", "NOT_A_ROSTER", "UNREADABLE"]


@dataclass
class TrainResult:
    artifact: dict
    train_rows: int
    val_rows: int


# ---------------------------------------------------------------------------
# Dataset assembly
# ---------------------------------------------------------------------------

def _label_for_incorrect(path: Path) -> str:
    """Return the doc-type label for a file from the incorrect/ directory.

    Only "invalid formatted" files are NOT_A_ROSTER.  The others (wrong date,
    wrong month period) are still valid roster images that passed doc-type but
    fail validation rules — labelled VALID_ROSTER for this classifier.
    """
    return "NOT_A_ROSTER" if _INVALID_FORMAT_MARKER in path.name.lower() else "VALID_ROSTER"


def load_fixture_images(
    correct_dir: str | Path,
    incorrect_dir: str | Path,
) -> list[tuple["np.ndarray", str]]:  # type: ignore[name-defined]
    """Load all fixture images and return (image, label) pairs.

    cv2 is imported lazily here so the rest of the training module stays
    importable even in environments where OpenCV is unavailable.
    """
    import cv2

    pairs: list[tuple] = []
    for directory, label_fn in (
        (Path(correct_dir), lambda _: "VALID_ROSTER"),
        (Path(incorrect_dir), _label_for_incorrect),
    ):
        if not directory.is_dir():
            logger.warning("Fixture directory not found: %s", directory)
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".pdf"}:
                continue
            if path.suffix.lower() == ".pdf":
                try:
                    from perdiem.engine.ocr.pdf import rasterise_pdf
                    pages = rasterise_pdf(str(path))
                    img = pages[0] if pages else None
                except Exception as exc:
                    logger.warning("Cannot rasterise %s: %s", path, exc)
                    img = None
            else:
                img = cv2.imread(str(path))
            if img is None:
                logger.warning("Cannot load %s — skipping", path)
                continue
            label = label_fn(path)
            pairs.append((img, label))
            logger.info("Loaded %s → %s", path.name, label)
    return pairs


def build_feature_rows(
    image_label_pairs: list[tuple["np.ndarray", str]],  # type: ignore[name-defined]
    augment_per_image: int = 10,
) -> list[tuple[dict[str, float], str]]:
    """Extract features from every image (original + augmented variants).

    Returns a list of (feature_dict, label) pairs ready for matrix assembly.
    UNREADABLE examples are synthesised from VALID_ROSTER images.
    """
    rows: list[tuple[dict[str, float], str]] = []

    valid_imgs = [img for img, lbl in image_label_pairs if lbl == "VALID_ROSTER"]

    for img, label in image_label_pairs:
        feats = extract_image_features(img)
        rows.append((feats, label))
        for aug in augment_image(img, n=augment_per_image, seed=hash(label) & 0xFFFF):
            try:
                rows.append((extract_image_features(aug), label))
            except Exception as exc:
                logger.debug("Feature extraction failed on augmented image: %s", exc)

    # Synthesise UNREADABLE examples from VALID_ROSTER images.
    unreadable_target = max(len(rows) // 4, len(valid_imgs) * 4)
    synthesised = 0
    for img in valid_imgs:
        for aug in make_unreadable_variants(img, n=4):
            try:
                rows.append((extract_image_features(aug), "UNREADABLE"))
                synthesised += 1
            except Exception as exc:
                logger.debug("Unreadable synthesis failed: %s", exc)
            if synthesised >= unreadable_target:
                break
        if synthesised >= unreadable_target:
            break

    logger.info("Dataset: %d rows (%s)",
                len(rows),
                ", ".join(f"{lbl}:{sum(1 for _, l in rows if l == lbl)}"
                          for lbl in CLASSES))
    return rows


# ---------------------------------------------------------------------------
# Matrix assembly
# ---------------------------------------------------------------------------

def _feature_names() -> list[str]:
    return list(NUMERIC_FEATURES)


def _standardisation(
    rows: list[tuple[dict[str, float], str]],
    names: list[str],
) -> dict[str, list[float]]:
    import numpy as np

    stats: dict[str, list[float]] = {}
    for name in names:
        vals = np.array([r[0].get(name, 0.0) for r in rows], dtype=float)
        std = float(vals.std())
        stats[name] = [float(vals.mean()), std if std else 1.0]
    return stats


def _build_matrix(
    rows: list[tuple[dict[str, float], str]],
    names: list[str],
    standardize: dict[str, list[float]],
) -> "np.ndarray":  # type: ignore[name-defined]
    import numpy as np

    X = np.zeros((len(rows), len(names)), dtype=float)
    for i, (feats, _) in enumerate(rows):
        for j, name in enumerate(names):
            v = float(feats.get(name, 0.0))
            if name in standardize:
                mean, std = standardize[name]
                v = (v - mean) / std if std else 0.0
            X[i, j] = v
    return X


# ---------------------------------------------------------------------------
# Softmax training (same algorithm as PD-ML-004 triage)
# ---------------------------------------------------------------------------

def _one_hot(y: list[int], k: int) -> "np.ndarray":  # type: ignore[name-defined]
    import numpy as np

    Y = np.zeros((len(y), k), dtype=float)
    for i, c in enumerate(y):
        Y[i, c] = 1.0
    return Y


def _balanced_weights(y: list[int], k: int) -> "np.ndarray":  # type: ignore[name-defined]
    import numpy as np

    counts = np.bincount(np.asarray(y), minlength=k).astype(float)
    counts[counts == 0] = 1.0
    w = len(y) / (k * counts)
    w = np.clip(w, 0.0, 20.0)
    sw = w[np.asarray(y)]
    return sw / sw.mean()


def _fit_softmax(
    X: "np.ndarray",  # type: ignore[name-defined]
    y: list[int],
    k: int,
    *,
    l2: float = 1e-3,
    lr: float = 0.2,
    iters: int = 3000,
) -> tuple["np.ndarray", "np.ndarray"]:  # type: ignore[name-defined]
    import numpy as np

    n, f = X.shape
    W = np.zeros((k, f), dtype=float)
    b = np.zeros(k, dtype=float)
    Y = _one_hot(y, k)
    sw = _balanced_weights(y, k)[:, None]
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        for _ in range(iters):
            logits = np.clip(X @ W.T + b, -30.0, 30.0)
            logits -= logits.max(axis=1, keepdims=True)
            e = np.exp(logits)
            P = e / e.sum(axis=1, keepdims=True)
            diff = (P - Y) * sw
            W -= lr * (diff.T @ X / n + l2 * W)
            b -= lr * (diff.sum(axis=0) / n)
    return W, b


# ---------------------------------------------------------------------------
# Public training entry-point
# ---------------------------------------------------------------------------

def train(
    train_rows: list[tuple[dict[str, float], str]],
    val_rows: list[tuple[dict[str, float], str]],
    *,
    dataset_version: str,
    min_conf: float = 0.70,
) -> TrainResult:
    """Train the softmax classifier and assemble the JSON artifact."""
    import numpy as np

    names = _feature_names()
    standardize = _standardisation(train_rows, names)
    X = _build_matrix(train_rows, names, standardize)

    class_index = {c: i for i, c in enumerate(CLASSES)}
    y = [class_index[lbl] for _, lbl in train_rows]
    W, b = _fit_softmax(X, y, len(CLASSES))

    # Val-set accuracy (informational; threshold is fixed by min_conf).
    val_acc: float | None = None
    if val_rows:
        Xv = _build_matrix(val_rows, names, standardize)
        logits = np.clip(Xv @ W.T + b, -30.0, 30.0)
        logits -= logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        probs = e / e.sum(axis=1, keepdims=True)
        preds = np.argmax(probs, axis=1)
        targets = np.array([class_index[lbl] for _, lbl in val_rows])
        val_acc = float((preds == targets).mean())
        logger.info("Validation accuracy: %.1f%%", val_acc * 100)

    artifact = {
        "model": "softmax-logreg",
        "trained_at": datetime.now(UTC).isoformat(),
        "dataset_version": dataset_version,
        "feature_names": names,
        "standardize": standardize,
        "classes": CLASSES,
        "W": W.tolist(),
        "b": b.tolist(),
        "thresholds": {"min_conf": min_conf},
        "val_accuracy": val_acc,
    }
    return TrainResult(
        artifact=artifact,
        train_rows=len(train_rows),
        val_rows=len(val_rows),
    )


def save_artifact(artifact: dict, path: str) -> None:
    import os

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh)
    logger.info("Saved doctype model to %s", path)
