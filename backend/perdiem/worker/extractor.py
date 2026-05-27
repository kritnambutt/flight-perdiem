"""Extractor factory and backend selection (PD-ML-007).

The worker calls `get_extractor(settings.ocr_backend, settings)` once per run
to obtain the configured `Extractor` implementation.  The engine stays pure —
no backend-selection logic leaks into `perdiem.engine`.

Supported backends:
  tesseract  The existing Tesseract+OpenCV extractor (default, always available).
  donut      Donut ML reader only; low-confidence results are NEEDS_REVIEW but
             do NOT automatically re-run Tesseract (use when the model is well
             validated and you want pure ML output).
  hybrid     Donut with automatic Tesseract fallback when overall confidence is
             below DONUT_CONF_FALLBACK — the recommended roll-out mode.

Any unrecognised value falls back to `tesseract` with a warning (safe default).
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from perdiem.engine.ocr.base import Extractor, TesseractExtractor

logger = logging.getLogger(__name__)

_VALID_BACKENDS = frozenset({"tesseract", "donut", "hybrid"})


def get_extractor(backend: str, cfg: object) -> Extractor:
    """Return the `Extractor` for `backend`, configured from `cfg` (Settings).

    `cfg` is the `perdiem.config.Settings` instance; typed as `object` here so
    this module doesn't import Settings at module level (keeps imports light).
    """
    b = (backend or "tesseract").lower().strip()

    if b not in _VALID_BACKENDS:
        logger.warning(
            "Unknown OCR_BACKEND %r — falling back to tesseract. "
            "Valid values: %s", b, ", ".join(sorted(_VALID_BACKENDS)),
        )
        b = "tesseract"

    if b == "tesseract":
        return TesseractExtractor()

    # donut or hybrid — both use DonutExtractor; only conf_fallback differs.
    from perdiem.engine.ocr.base import DonutExtractor
    from perdiem.engine.ocr.ml_extract import DonutConfig

    fallback = getattr(cfg, "donut_conf_fallback", 0.60) if b == "hybrid" else 0.0
    donut_cfg = DonutConfig(
        enabled=getattr(cfg, "donut_enabled", False),
        model_path=getattr(cfg, "donut_model_path", "data/ml/models/donut"),
        conf_fallback=fallback,
        max_pages=getattr(cfg, "donut_max_pages", 2),
    )
    return DonutExtractor(donut_cfg)


def model_version_for(extractor: Extractor) -> str:
    """Derive a cache-safe version string for the extractor's underlying model.

    For TesseractExtractor the version is fixed ("tesseract").
    For DonutExtractor it is the SHA-1 of the model directory's mtime so
    re-training naturally invalidates stale cache entries.
    """
    name = getattr(extractor, "name", "unknown")

    if name == "tesseract":
        return "tesseract"

    # Donut: hash the modification time of the model path (directory or file).
    cfg = getattr(extractor, "_cfg", None)
    model_path = getattr(cfg, "model_path", "") if cfg else ""
    mp = Path(model_path) if model_path else None
    if mp and mp.exists():
        try:
            mtime = str(os.path.getmtime(mp))
            return hashlib.sha1(mtime.encode()).hexdigest()[:12]
        except OSError:
            pass
    return f"{name}-not-trained"
