"""Doc-type / quality classifier (PD-ML-005) — pure scorer.

Answers one cheap question before any field extraction: is this attachment
actually a readable crew schedule report?

Three outcome labels:
  VALID_ROSTER  — recognisable crew schedule; proceed to field extraction.
  NOT_A_ROSTER  — wrong document type (e.g. PDF not a roster, wrong app).
  UNREADABLE    — image is corrupt, blank, tiny, or too low-quality.

Both non-valid labels route the claim to NEEDS_REVIEW; the pipeline never
emits fabricated fields for them (N1).

Engine purity: this module owns the image feature spec (so training and
inference never drift) and lazy-imports cv2/numpy inside scorers, so importing
the module never pulls in OpenCV or the model at startup.  The training tools
in `ml/doctype/` import `extract_image_features` from here; the engine never
imports `ml`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

logger = logging.getLogger(__name__)

DocTypeLabel = Literal["VALID_ROSTER", "NOT_A_ROSTER", "UNREADABLE"]

# Features that must be z-score standardised at train time.
NUMERIC_FEATURES = (
    "log_width", "log_height", "aspect_ratio",
    "mean_brightness", "brightness_std",
    "edge_density", "blue_band_score",
    "dark_ratio", "color_std",
    "row_variance_mean", "col_variance_mean",
)


@dataclass
class DocTypeConfig:
    enabled: bool = False
    model_path: str = "data/ml/models/doctype.json"
    min_conf: float = 0.70  # below this → abstain; non-VALID treated as review


@dataclass
class DocTypeResult:
    label: DocTypeLabel
    confidence: float


# ---------------------------------------------------------------------------
# Pure feature spec — shared by training (ml/doctype) and inference (here)
# ---------------------------------------------------------------------------

def extract_image_features(image: "np.ndarray") -> dict[str, float]:  # type: ignore[name-defined]
    """Extract doc-type signal from a loaded BGR/BGRA/gray numpy image.

    Returns a dict whose keys match NUMERIC_FEATURES. All values are floats.
    Can be called without OpenCV at import time; cv2/numpy are passed in as
    the live ndarray — callers already have the import.
    """
    import cv2
    import numpy as np

    h, w = image.shape[:2]

    # Normalise to BGR
    if image.ndim == 2:
        bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    else:
        bgr = image

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray_f = gray.astype(np.float32) / 255.0

    feats: dict[str, float] = {}
    feats["log_width"] = float(np.log1p(w))
    feats["log_height"] = float(np.log1p(h))
    feats["aspect_ratio"] = float(w) / max(1, h)
    feats["mean_brightness"] = float(gray_f.mean())
    feats["brightness_std"] = float(gray_f.std())

    # Edge density — grid lines + text produce many edges in a valid roster.
    small = cv2.resize(gray, (min(w, 800), min(h, 800)), interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(small, 50, 150)
    feats["edge_density"] = float((edges > 0).mean())

    # Blue header band — AirAsia roster has a blue band in the top ~20%.
    band_h = max(1, int(h * 0.20))
    band = bgr[:band_h, :]
    b_ch = band[:, :, 0].astype(np.int16)
    g_ch = band[:, :, 1].astype(np.int16)
    r_ch = band[:, :, 2].astype(np.int16)
    blue_mask = ((b_ch - r_ch) > 30) & ((b_ch - g_ch) > 10)
    feats["blue_band_score"] = float(blue_mask.mean())

    # Dark pixel ratio — text + grid lines.
    feats["dark_ratio"] = float((gray_f < 0.30).mean())

    # Colorfulness — mean of per-channel std.
    feats["color_std"] = float(
        np.mean([bgr[:, :, c].astype(np.float32).std() for c in range(3)])
    )

    # Row/column variance — text rows produce high per-row variance.
    row_var = np.var(gray_f, axis=1)
    col_var = np.var(gray_f, axis=0)
    feats["row_variance_mean"] = float(row_var.mean())
    feats["col_variance_mean"] = float(col_var.mean())

    return feats


# ---------------------------------------------------------------------------
# Image loader (handles images + PDFs; lazy deps)
# ---------------------------------------------------------------------------

def _load_best_page(image_path: str) -> "np.ndarray | None":  # type: ignore[name-defined]
    """Load the first (or only) page of an image / PDF into a BGR ndarray.

    Returns None for zero-byte files, corrupt images, and any load error.
    """
    import os

    if not image_path or not os.path.isfile(image_path):
        return None
    if os.path.getsize(image_path) == 0:
        return None

    if image_path.lower().endswith(".pdf"):
        try:
            from perdiem.engine.ocr.pdf import rasterise_pdf
            pages = rasterise_pdf(image_path)
            return pages[0] if pages else None
        except Exception as exc:
            logger.debug("doctype: PDF rasterise failed for %s: %s", image_path, exc)
            return None

    import cv2
    img = cv2.imread(image_path)
    return img  # None if OpenCV couldn't decode it


# ---------------------------------------------------------------------------
# Softmax scorer (pure numpy — no training deps)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _load_artifact(model_path: str) -> dict:
    with open(model_path, encoding="utf-8") as fh:
        return json.load(fh)


def _softmax_predict(x: "np.ndarray", W: "np.ndarray", b: "np.ndarray") -> "np.ndarray":  # type: ignore[name-defined]
    import numpy as np
    logits = np.clip(x @ W.T + b, -30.0, 30.0)
    logits -= logits.max()
    e = np.exp(logits)
    return e / e.sum()


def classify_doc(image_path: str, model_path: str, cfg: DocTypeConfig) -> DocTypeResult:
    """Classify a roster attachment as VALID_ROSTER / NOT_A_ROSTER / UNREADABLE.

    Pre-checks for corrupt / unloadable files are performed before the model
    so the ML scorer only sees images it can actually read a feature vector from.
    """
    import numpy as np

    # Pre-check: unloadable / corrupt / blank
    img = _load_best_page(image_path)
    if img is None:
        return DocTypeResult(label="UNREADABLE", confidence=1.0)
    h, w = img.shape[:2]
    if w < 50 or h < 50:
        return DocTypeResult(label="UNREADABLE", confidence=1.0)

    try:
        artifact = _load_artifact(model_path)
    except Exception as exc:
        logger.debug("doctype: cannot load model %s: %s", model_path, exc)
        raise

    names: list[str] = artifact["feature_names"]
    standardize: dict[str, list[float]] = artifact["standardize"]
    classes: list[str] = artifact["classes"]
    W = np.array(artifact["W"], dtype=float)
    b = np.array(artifact["b"], dtype=float)

    feats = extract_image_features(img)
    x = np.zeros(len(names), dtype=float)
    for i, name in enumerate(names):
        v = float(feats.get(name, 0.0))
        if name in standardize:
            mean, std = standardize[name]
            v = (v - mean) / std if std else 0.0
        x[i] = v

    probs = _softmax_predict(x, W, b)
    top_idx = int(np.argmax(probs))
    label: DocTypeLabel = classes[top_idx]  # type: ignore[assignment]
    confidence = float(probs[top_idx])

    # Abstain: low-confidence VALID_ROSTER prediction → treat as UNREADABLE.
    if label == "VALID_ROSTER" and confidence < cfg.min_conf:
        label = "UNREADABLE"

    return DocTypeResult(label=label, confidence=confidence)


def safe_classify_doc(image_path: str | None, cfg: DocTypeConfig) -> DocTypeResult | None:
    """Classify doc type, returning None when disabled or model is missing.

    Never raises — errors are logged and None is returned so the caller can
    skip the gate and proceed with Tesseract extraction unchanged.
    """
    if not cfg.enabled:
        return None
    if not image_path:
        return None
    import os
    if not os.path.isfile(cfg.model_path):
        logger.debug("doctype: model not found at %s — skipping gate", cfg.model_path)
        return None
    try:
        return classify_doc(image_path, cfg.model_path, cfg)
    except Exception as exc:
        logger.warning("doctype: classification error for %s: %s", image_path, exc)
        return None
