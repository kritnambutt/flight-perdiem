"""Tests for the pluggable extractor backend (PD-ML-007).

Covers:
  - get_extractor() factory: correct type per backend string
  - Unknown backend falls back to Tesseract with a warning
  - OCR cache: round-trip serialisation, cache hit/miss, corrupt entry recovery
  - model_version_for() returns stable strings
  - Engine purity: importing perdiem.engine pulls in no torch/onnx
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from perdiem.engine.models import ExtractedRoster, Field, Leg, RosterRef
from perdiem.engine.ocr.base import DonutExtractor, TesseractExtractor
from perdiem.engine.ocr.cache import from_dict, load_cached, store_cached, to_dict
from perdiem.worker.extractor import get_extractor, model_version_for


# ---------------------------------------------------------------------------
# get_extractor() factory
# ---------------------------------------------------------------------------

class _FakeCfg:
    donut_enabled = False
    donut_model_path = "/no/such/model"
    donut_conf_fallback = 0.60
    donut_max_pages = 2
    ocr_backend = "tesseract"


def test_factory_tesseract():
    ex = get_extractor("tesseract", _FakeCfg())
    assert isinstance(ex, TesseractExtractor)
    assert ex.name == "tesseract"


def test_factory_donut():
    ex = get_extractor("donut", _FakeCfg())
    assert isinstance(ex, DonutExtractor)
    assert ex.name == "donut"


def test_factory_hybrid():
    ex = get_extractor("hybrid", _FakeCfg())
    assert isinstance(ex, DonutExtractor)
    assert ex.name == "donut"


def test_factory_hybrid_has_nonzero_fallback():
    """hybrid mode must enable Tesseract fallback via conf_fallback > 0."""
    from perdiem.engine.ocr.ml_extract import DonutConfig

    class Cfg(_FakeCfg):
        donut_conf_fallback = 0.65

    ex = get_extractor("hybrid", Cfg())
    cfg = ex._cfg
    assert isinstance(cfg, DonutConfig)
    assert cfg.conf_fallback == 0.65


def test_factory_donut_has_zero_fallback():
    """pure donut mode: conf_fallback=0 → never automatically fall back."""
    from perdiem.engine.ocr.ml_extract import DonutConfig

    ex = get_extractor("donut", _FakeCfg())
    cfg = ex._cfg
    assert isinstance(cfg, DonutConfig)
    assert cfg.conf_fallback == 0.0


def test_factory_unknown_falls_back_to_tesseract(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="perdiem.worker.extractor"):
        ex = get_extractor("magic_ocr", _FakeCfg())
    assert isinstance(ex, TesseractExtractor)
    assert any("magic_ocr" in r.message for r in caplog.records)


def test_factory_empty_string_falls_back_to_tesseract():
    ex = get_extractor("", _FakeCfg())
    assert isinstance(ex, TesseractExtractor)


# ---------------------------------------------------------------------------
# model_version_for()
# ---------------------------------------------------------------------------

def test_model_version_tesseract():
    ex = TesseractExtractor()
    assert model_version_for(ex) == "tesseract"


def test_model_version_donut_no_model():
    ex = get_extractor("donut", _FakeCfg())
    ver = model_version_for(ex)
    assert "not-trained" in ver


def test_model_version_donut_with_model(tmp_path):
    (tmp_path / "config.json").write_text('{"model_type":"donut"}')

    class Cfg(_FakeCfg):
        donut_model_path = str(tmp_path)
        donut_enabled = True

    ex = get_extractor("donut", Cfg())
    ver = model_version_for(ex)
    assert len(ver) == 12  # 12-char hex


def test_model_version_stable_across_calls(tmp_path):
    (tmp_path / "config.json").write_text("{}")

    class Cfg(_FakeCfg):
        donut_model_path = str(tmp_path)

    ex = get_extractor("donut", Cfg())
    assert model_version_for(ex) == model_version_for(ex)


# ---------------------------------------------------------------------------
# OCR cache — serialisation round-trip
# ---------------------------------------------------------------------------

def _sample_roster() -> ExtractedRoster:
    return ExtractedRoster(
        staff_id=Field("1234567", 0.95),
        name=Field("JOHN DOE", 0.80),
        start_date=Field(date(2026, 2, 1), 1.0),
        end_date=Field(date(2026, 2, 28), 1.0),
        generated_at=Field(datetime(2026, 3, 1, 14, 30), 1.0),
        grid={
            15: [Leg("FD3012", "DMK", "HKT", "06:00")],
            16: [Leg("FD3013", "HKT", "DMK", "08:30")],
        },
        needs_review=[],
    )


def test_cache_round_trip(tmp_path):
    roster = _sample_roster()
    store_cached(str(tmp_path), "file123", "tesseract", "v1", roster)
    loaded = load_cached(str(tmp_path), "file123", "tesseract", "v1")
    assert loaded is not None
    assert loaded.staff_id.value == "1234567"
    assert loaded.staff_id.confidence == pytest.approx(0.95)
    assert loaded.start_date.value == date(2026, 2, 1)
    assert loaded.generated_at.value == datetime(2026, 3, 1, 14, 30)
    assert 15 in loaded.grid
    assert loaded.grid[15][0].flight_no == "FD3012"


def test_cache_miss_returns_none(tmp_path):
    assert load_cached(str(tmp_path), "missing_file", "tesseract", "v1") is None


def test_cache_key_includes_backend(tmp_path):
    roster = _sample_roster()
    store_cached(str(tmp_path), "file123", "tesseract", "v1", roster)
    # Different backend → different key → miss
    assert load_cached(str(tmp_path), "file123", "donut", "v1") is None


def test_cache_key_includes_model_version(tmp_path):
    roster = _sample_roster()
    store_cached(str(tmp_path), "file123", "donut", "v1", roster)
    # Different version → miss
    assert load_cached(str(tmp_path), "file123", "donut", "v2") is None


def test_cache_empty_file_id_not_stored(tmp_path):
    roster = _sample_roster()
    store_cached(str(tmp_path), "", "tesseract", "v1", roster)
    files = list(tmp_path.iterdir())
    assert len(files) == 0


def test_cache_corrupt_entry_recovered(tmp_path):
    """A corrupt cache file should be silently deleted and return a miss."""
    store_cached(str(tmp_path), "file123", "tesseract", "v1", _sample_roster())
    # Overwrite with garbage
    for f in tmp_path.glob("*.json"):
        f.write_text("NOT JSON }{")
    result = load_cached(str(tmp_path), "file123", "tesseract", "v1")
    assert result is None
    # File should be removed
    assert not any(tmp_path.glob("*.json"))


def test_cache_null_fields_survive_round_trip(tmp_path):
    empty = Field(None, 0.0)
    roster = ExtractedRoster(
        staff_id=empty, name=empty,
        start_date=empty, end_date=empty, generated_at=empty,
        grid={}, needs_review=["low confidence"],
    )
    store_cached(str(tmp_path), "empty_file", "tesseract", "v1", roster)
    loaded = load_cached(str(tmp_path), "empty_file", "tesseract", "v1")
    assert loaded is not None
    assert loaded.staff_id.value is None
    assert loaded.needs_review == ["low confidence"]


# ---------------------------------------------------------------------------
# to_dict / from_dict (unit-level serialisation)
# ---------------------------------------------------------------------------

def test_to_dict_contains_backend():
    roster = _sample_roster()
    d = to_dict(roster, backend="donut")
    assert d["_backend"] == "donut"


def test_from_dict_round_trip():
    roster = _sample_roster()
    d = to_dict(roster, backend="tesseract")
    loaded = from_dict(d)
    assert loaded.staff_id.value == roster.staff_id.value
    assert loaded.grid[16][0].orig == "HKT"


# ---------------------------------------------------------------------------
# Engine purity check
# ---------------------------------------------------------------------------

def test_engine_imports_no_torch_onnx():
    """Importing perdiem.engine must not pull in torch or onnxruntime."""
    import sys
    # Both modules might be installed but must NOT be imported by the engine.
    torch_before = "torch" in sys.modules
    ort_before = "onnxruntime" in sys.modules

    # Re-importing the engine should not change this.
    import importlib
    import perdiem.engine.models
    import perdiem.engine.rules
    importlib.reload(perdiem.engine.models)

    if not torch_before:
        assert "torch" not in sys.modules, "engine imported torch"
    if not ort_before:
        assert "onnxruntime" not in sys.modules, "engine imported onnxruntime"


def test_ocr_base_imports_no_torch():
    """Importing perdiem.engine.ocr.base must not load torch/onnx."""
    import sys
    torch_before = "torch" in sys.modules
    import perdiem.engine.ocr.base  # noqa: F401
    if not torch_before:
        assert "torch" not in sys.modules
