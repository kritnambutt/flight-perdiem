"""Extractor protocol — the backend-agnostic seam for roster extraction.

Defined here (PD-ML-003) so the eval harness can score *any* extractor with the same
metrics, and so PD-ML-007 can later add `donut` / `hybrid` backends behind the same
interface. This module is intentionally light — it imports only engine models, no OCR
or ML deps — so importing the protocol never pulls in Tesseract/torch.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from perdiem.engine.models import ExtractedRoster, RosterRef


@runtime_checkable
class Extractor(Protocol):
    """Anything that turns a roster reference into an `ExtractedRoster`.

    Implementations: `TesseractExtractor` (today), `DonutExtractor` /
    `HybridExtractor` (PD-ML-006/007). The `name` tags which backend produced the
    fields, recorded for audit (N1).
    """

    name: str

    def extract(self, ref: RosterRef) -> ExtractedRoster: ...


class DonutExtractor:
    """Donut-based extractor (PD-ML-006), wrapped as an `Extractor`.

    Lazy-imports `extract_roster_donut` so this class can be referenced without
    loading torch/onnxruntime.  When `safe_extract_donut` returns None (disabled
    or model missing), falls through to the Tesseract extractor so callers never
    get a bare None result.
    """

    name = "donut"

    def __init__(self, cfg: object | None = None) -> None:
        self._cfg = cfg

    def extract(self, ref: RosterRef) -> ExtractedRoster:
        from perdiem.engine.ocr.ml_extract import DonutConfig, safe_extract_donut

        cfg = self._cfg if isinstance(self._cfg, DonutConfig) else DonutConfig()
        result = safe_extract_donut(ref, cfg)
        if result is not None:
            return result
        # Fallback: Tesseract
        from perdiem.engine.ocr.extract import extract_roster
        return extract_roster(ref)


class TesseractExtractor:
    """The current Tesseract+OpenCV extractor, wrapped as an `Extractor`.

    Lazy-imports `extract_roster` so merely referencing the protocol/adapter does not
    load OpenCV/Tesseract (keeps engine unit tests and the protocol import light).
    """

    name = "tesseract"

    def __init__(self, cfg: object | None = None) -> None:
        self._cfg = cfg

    def extract(self, ref: RosterRef) -> ExtractedRoster:
        from perdiem.engine.ocr.extract import extract_roster

        if self._cfg is not None:
            return extract_roster(ref, self._cfg)  # type: ignore[arg-type]
        return extract_roster(ref)
