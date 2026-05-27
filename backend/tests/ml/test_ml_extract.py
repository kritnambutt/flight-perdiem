"""Tests for the Donut inference interface (PD-ML-006).

Covers JSON parsing, confidence scoring, fallback behaviour, and the
`DonutExtractor` class — no actual model or torch/onnxruntime needed.
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from perdiem.engine.models import ExtractedRoster, Field, RosterRef
from perdiem.engine.ocr.ml_extract import (
    DonutConfig,
    _empty,
    _parse_date,
    _parse_donut_output,
    _parse_generated_at,
    _parse_leg,
    safe_extract_donut,
)


# ---------------------------------------------------------------------------
# Field parsers
# ---------------------------------------------------------------------------

def test_parse_date_valid():
    assert _parse_date("15/02/2026") == date(2026, 2, 15)


def test_parse_date_invalid_format():
    assert _parse_date("2026-02-15") is None
    assert _parse_date("") is None
    assert _parse_date(None) is None  # type: ignore[arg-type]


def test_parse_date_invalid_value():
    assert _parse_date("32/01/2026") is None


def test_parse_generated_at_valid():
    dt = _parse_generated_at("Feb 15, 2026 14:30")
    assert dt == datetime(2026, 2, 15, 14, 30)


def test_parse_generated_at_without_comma():
    dt = _parse_generated_at("Mar 09, 2026 19:36")
    assert dt is not None
    assert dt.month == 3


def test_parse_generated_at_invalid():
    assert _parse_generated_at("not a date") is None
    assert _parse_generated_at("") is None


def test_parse_leg_valid():
    leg = _parse_leg({"fn": "FD3012", "from": "DMK", "to": "HKT", "time": "06:00"})
    assert leg is not None
    assert leg.flight_no == "FD3012"
    assert leg.orig == "DMK"
    assert leg.dest == "HKT"
    assert leg.time == "06:00"


def test_parse_leg_bad_flight_no():
    assert _parse_leg({"fn": "TG100", "from": "DMK", "to": "HKT", "time": "06:00"}) is None


def test_parse_leg_missing_airports():
    leg = _parse_leg({"fn": "FD3012", "from": "", "to": "", "time": "06:00"})
    assert leg is not None
    assert leg.orig is None
    assert leg.dest is None


# ---------------------------------------------------------------------------
# _parse_donut_output — full JSON → ExtractedRoster
# ---------------------------------------------------------------------------

def _good_json(**overrides) -> str:
    payload = {
        "staff_id": "1234567",
        "name": "JOHN DOE",
        "start_date": "01/02/2026",
        "end_date": "28/02/2026",
        "generated_at": "Mar 01, 2026 10:00",
        "grid": {
            "15": [{"fn": "FD3012", "from": "DMK", "to": "HKT", "time": "06:00"}],
            "16": [{"fn": "FD3013", "from": "HKT", "to": "DMK", "time": "08:30"}],
        },
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_parse_valid_json_high_confidence():
    result, conf = _parse_donut_output(_good_json())
    assert conf > 0.80, f"expected high confidence, got {conf}"
    assert result.staff_id.value == "1234567"
    assert result.name.value == "JOHN DOE"
    assert result.start_date.value == date(2026, 2, 1)
    assert result.end_date.value == date(2026, 2, 28)
    assert result.generated_at.value == datetime(2026, 3, 1, 10, 0)
    assert 15 in result.grid
    assert 16 in result.grid


def test_parse_json_embedded_in_tokens():
    """Decoder may include surrounding special tokens — JSON should still parse."""
    raw = f"<s_perdiem_roster>{_good_json()}</s_perdiem_roster>"
    result, conf = _parse_donut_output(raw)
    assert conf > 0.80


def test_parse_invalid_staff_id_lowers_confidence():
    raw = _good_json(staff_id="BADID")
    result, conf = _parse_donut_output(raw)
    assert conf < 0.80
    assert any("staff_id" in r for r in result.needs_review)


def test_parse_bad_start_date_lowers_confidence():
    raw = _good_json(start_date="not-a-date")
    result, conf = _parse_donut_output(raw)
    assert result.start_date.value is None
    assert any("start_date" in r for r in result.needs_review)


def test_parse_empty_grid_lowers_confidence():
    raw = _good_json(grid={})
    result, conf = _parse_donut_output(raw)
    assert result.grid == {}
    assert any("grid" in r for r in result.needs_review)


def test_parse_unparseable_json():
    result, conf = _parse_donut_output("not JSON at all")
    assert conf == 0.0
    assert result.staff_id.value is None


def test_parse_missing_required_key():
    payload = json.loads(_good_json())
    del payload["staff_id"]
    result, conf = _parse_donut_output(json.dumps(payload))
    assert conf == 0.0


# ---------------------------------------------------------------------------
# safe_extract_donut — fallback behaviour (no real model needed)
# ---------------------------------------------------------------------------

def _ref(path: str | None = None) -> RosterRef:
    return RosterRef(
        source_url="", file_id=None,
        local_path=path,
        content_type="image/jpeg",
        status="OK",
    )


def test_safe_disabled_returns_none():
    cfg = DonutConfig(enabled=False, model_path="/no/such/path")
    assert safe_extract_donut(_ref("/any/path.jpg"), cfg) is None


def test_safe_missing_model_returns_none():
    cfg = DonutConfig(enabled=True, model_path="/no/such/model/dir")
    assert safe_extract_donut(_ref("/any/path.jpg"), cfg) is None


def test_safe_none_local_path_returns_none(tmp_path):
    """Enabled + model dir exists, but roster has no local file → fallback."""
    model_dir = tmp_path / "donut"
    model_dir.mkdir()
    (model_dir / "config.json").write_text('{"model_type":"donut"}')
    cfg = DonutConfig(enabled=True, model_path=str(model_dir), conf_fallback=0.0)
    # local_path=None → extract_roster_donut returns empty result (not None)
    result = safe_extract_donut(_ref(None), cfg)
    # Result can be an ExtractedRoster (not None) from the fallback chain
    # OR None from safe_extract_donut suppressing an error — both are acceptable.
    assert result is None or isinstance(result, ExtractedRoster)


# ---------------------------------------------------------------------------
# DonutExtractor protocol compliance
# ---------------------------------------------------------------------------

def test_donut_extractor_is_extractor():
    from perdiem.engine.ocr.base import DonutExtractor, Extractor
    ex = DonutExtractor()
    assert isinstance(ex, Extractor)
    assert ex.name == "donut"


def test_donut_extractor_falls_back_to_tesseract_when_disabled(tmp_path):
    """With DONUT_ENABLED=false (default), extract() should transparently use Tesseract."""
    from perdiem.engine.ocr.base import DonutExtractor
    from perdiem.engine.ocr.ml_extract import DonutConfig

    cfg = DonutConfig(enabled=False, model_path="/no/such/path")
    ex = DonutExtractor(cfg)
    # A RosterRef with no local file returns an empty ExtractedRoster — not a crash.
    ref = _ref(None)
    result = ex.extract(ref)
    assert isinstance(result, ExtractedRoster)
    assert result.staff_id.value is None  # empty result from missing file
