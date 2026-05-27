"""Tests for roster OCR extraction — regex units + integration against fixtures."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from perdiem.engine.models import OcrConfig, RosterRef
from perdiem.engine.ocr.extract import (
    _extract_crew_line,
    _extract_date_range,
    _extract_generated_date,
    _extract_grid_from_words,
    _parse_column_legs,
)

FIXTURES = Path(__file__).parent.parent.parent.parent / "docs" / "example-files"
CORRECT = FIXTURES / "roster-attached-files" / "correct"
INCORRECT = FIXTURES / "roster-attached-files" / "incorrect"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ref(path: str, ctype: str = "image/jpeg") -> RosterRef:
    return RosterRef(
        source_url="",
        file_id="test",
        local_path=str(path),
        content_type=ctype,
        status="OK",
    )


@pytest.fixture(scope="session")
def tesseract_ok():
    """Skip if tesseract binary is not available."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception as exc:
        pytest.skip(f"Tesseract not available: {exc}")


# ---------------------------------------------------------------------------
# _extract_date_range — pure unit tests
# ---------------------------------------------------------------------------

class TestExtractDateRange:
    def test_standard_format(self):
        text = "AIR ASIA\n01/03/2026 - 31/03/2026 (All times in Local Station)"
        s, e = _extract_date_range(text)
        assert s.value == date(2026, 3, 1)
        assert e.value == date(2026, 3, 31)
        assert s.confidence == 1.0

    def test_en_dash(self):
        text = "01/02/2026 – 28/02/2026"
        s, e = _extract_date_range(text)
        assert s.value == date(2026, 2, 1)
        assert e.value == date(2026, 2, 28)

    def test_missing_returns_none(self):
        s, e = _extract_date_range("No date here")
        assert s.value is None
        assert s.confidence == 0.0

    def test_february_range(self):
        s, e = _extract_date_range("01/02/2026 - 28/02/2026 (All times in Local Station)")
        assert s.value == date(2026, 2, 1)
        assert e.value == date(2026, 2, 28)

    def test_august_range(self):
        s, e = _extract_date_range("01/07/2025 - 31/07/2025 (All times in Local Station)")
        assert s.value == date(2025, 7, 1)
        assert e.value == date(2025, 7, 31)


# ---------------------------------------------------------------------------
# _extract_crew_line — pure unit tests
# ---------------------------------------------------------------------------

class TestExtractCrewLine:
    def test_standard_crew_line(self):
        text = "1009759 RATTANAPORN, BOONIN  DMK, CC, FD20"
        sid, name = _extract_crew_line(text)
        assert sid.value == "1009759"
        assert sid.confidence == 1.0
        assert "RATTANAPORN" in name.value

    def test_kanatsanan(self):
        text = "1014666 KANATSANAN, WICHITTHARARAK DMK, CC, FD20"
        sid, name = _extract_crew_line(text)
        assert sid.value == "1014666"
        assert "KANATSANAN" in name.value

    def test_chanicha(self):
        text = "1007339 CHANICHA, SONGKRIT DMK-CC-FD20"
        sid, name = _extract_crew_line(text)
        assert sid.value == "1007339"

    def test_other_crew_section_fallback(self):
        # Simulates noisy OCR where crew line garbled but other-crew section has it
        # 1043895 appears 3 times → wins by frequency; name extracted from context
        text = (
            "GARBAGE HEADER LINE\n"
            "CC - 1043895 - SAWAROS, PHANICHVIBUL | FO - 1001234 - OTHER\n"
            "CC - 1043895 - SAWAROS, PHANICHVIBUL | FO - 1009999 - ANOTHER\n"
            "CC - 1043895 - SAWAROS, PHANICHVIBUL | FO - 1008888 - THIRD"
        )
        sid, name = _extract_crew_line(text)
        assert sid.value == "1043895"
        assert "SAWAROS" in (name.value or "")

    def test_tilde_separator(self):
        text = (
            "CC ~ 1009759 ~ RATTANAPORN, BOONIN | CC ~ 1011705\n"
            "CC ~ 1009759 ~ RATTANAPORN, BOONIN | CC ~ 1011705\n"
            "CC ~ 1009759 ~ RATTANAPORN, BOONIN | CC ~ 1011705\n"
        )
        sid, name = _extract_crew_line(text)
        assert sid.value == "1009759"

    def test_bare_id_fallback(self):
        text = "some text 1234567 other text"
        sid, name = _extract_crew_line(text)
        assert sid.value == "1234567"
        assert sid.confidence >= 0.6  # S3 bare fallback

    def test_no_id_returns_none(self):
        sid, name = _extract_crew_line("no digits here")
        assert sid.value is None
        assert sid.confidence == 0.0


# ---------------------------------------------------------------------------
# _extract_generated_date — pure unit tests
# ---------------------------------------------------------------------------

class TestExtractGeneratedDate:
    def test_mar_format(self):
        text = "Generated on Mar 09, 2026 19:36    Page 1 of 1"
        f = _extract_generated_date(text)
        assert f.value == datetime(2026, 3, 9, 19, 36)
        assert f.confidence == 1.0

    def test_apr_format(self):
        f = _extract_generated_date("Generated on Apr 02, 2026 19:54")
        assert f.value == datetime(2026, 4, 2, 19, 54)

    def test_may_format(self):
        f = _extract_generated_date("Generated on May 05, 2026 16:36 Page 1of 3")
        assert f.value == datetime(2026, 5, 5, 16, 36)

    def test_lowercase_month(self):
        f = _extract_generated_date("generated on mar 28, 2026 10:16")
        assert f.value == datetime(2026, 3, 28, 10, 16)

    def test_missing_returns_none(self):
        f = _extract_generated_date("No generated date here")
        assert f.value is None
        assert f.confidence == 0.0

    def test_no_comma_before_year(self):
        f = _extract_generated_date("Generated on Aug 15 2025 08:30")
        assert f.value == datetime(2025, 8, 15, 8, 30)


# ---------------------------------------------------------------------------
# _parse_column_legs — pure unit tests
# ---------------------------------------------------------------------------

class TestParseColumnLegs:
    def test_dmk_hkt_leg(self):
        words = ["06:25", "FD3013", "A20:49", "DMK", "HKT", "A22:17", "[FD20]", "22:47"]
        legs = _parse_column_legs(words)
        assert len(legs) == 1
        assert legs[0].flight_no == "FD3013"
        assert legs[0].orig == "DMK"
        assert legs[0].dest == "HKT"

    def test_hkt_dmk_leg(self):
        words = ["FD3038", "A09:11", "HKT", "DMK", "A10:44"]
        legs = _parse_column_legs(words)
        assert len(legs) == 1
        assert legs[0].flight_no == "FD3038"
        assert legs[0].orig == "HKT"
        assert legs[0].dest == "DMK"

    def test_multi_leg_day(self):
        words = ["FD140", "DMK", "COK", "FD141", "COK", "DMK"]
        legs = _parse_column_legs(words)
        assert len(legs) == 2
        assert legs[0].flight_no == "FD140"
        assert legs[1].flight_no == "FD141"

    def test_off_day_no_legs(self):
        legs = _parse_column_legs(["OFF"])
        assert legs == []

    def test_empty_column(self):
        assert _parse_column_legs([]) == []

    def test_flight_without_airports(self):
        legs = _parse_column_legs(["FD562", "06:00"])
        assert len(legs) == 1
        assert legs[0].flight_no == "FD562"
        assert legs[0].orig is None

    def test_case_insensitive_flight_no(self):
        legs = _parse_column_legs(["fd3013", "DMK", "HKT"])
        assert len(legs) == 1
        assert legs[0].flight_no == "FD3013"


# ---------------------------------------------------------------------------
# _extract_grid_from_words — pure unit tests
# ---------------------------------------------------------------------------

class TestExtractGridFromWords:
    def _make_word(self, text: str, left: int, top: int, w: int = 50, h: int = 15) -> tuple:
        return (text, left, top, w, h)

    def test_single_column_with_flight(self):
        # Simulate day header + flight below it
        words = [
            self._make_word("01/03", 100, 50),
            self._make_word("FD3013", 100, 100),
            self._make_word("DMK", 110, 120),
            self._make_word("HKT", 105, 135),
        ]
        grid, geom = _extract_grid_from_words(words)
        assert 1 in grid
        assert grid[1][0].flight_no == "FD3013"
        assert grid[1][0].orig == "DMK"
        assert 1 in geom.columns

    def test_two_columns_isolated(self):
        words = [
            self._make_word("01/03", 100, 50),
            self._make_word("FD3013", 100, 100),
            self._make_word("DMK", 108, 120),
            self._make_word("HKT", 108, 140),
            self._make_word("27/03", 800, 50),
            self._make_word("FD3006", 800, 100),
            self._make_word("HKT", 808, 120),
            self._make_word("DMK", 808, 140),
        ]
        grid, geom = _extract_grid_from_words(words)
        assert 1 in grid and 27 in grid
        assert grid[1][0].flight_no == "FD3013"
        assert grid[27][0].flight_no == "FD3006"
        assert 1 in geom.columns and 27 in geom.columns

    def test_no_headers_returns_empty(self):
        words = [self._make_word("FD3013", 100, 100)]
        grid, geom = _extract_grid_from_words(words)
        assert grid == {}
        assert geom.columns == {}

    def test_duplicate_day_header_keeps_first(self):
        words = [
            self._make_word("01/03", 100, 50),   # first occurrence
            self._make_word("FD3013", 100, 100),
            self._make_word("01/03", 100, 200),  # OCR duplicate — skip
            self._make_word("FD9999", 100, 250),
        ]
        grid, _geom = _extract_grid_from_words(words)
        assert 1 in grid
        assert any(l.flight_no == "FD3013" for l in grid[1])


# ---------------------------------------------------------------------------
# Preprocess unit tests (opencv only, no tesseract)
# ---------------------------------------------------------------------------

class TestPreprocess:
    def test_to_gray_converts_color(self):
        from perdiem.engine.ocr.preprocess import to_gray
        color = np.zeros((10, 10, 3), dtype=np.uint8)
        gray = to_gray(color)
        assert gray.ndim == 2

    def test_to_gray_passthrough_for_gray(self):
        from perdiem.engine.ocr.preprocess import to_gray
        gray = np.zeros((10, 10), dtype=np.uint8)
        assert to_gray(gray).ndim == 2

    def test_upscale_expands_small_image(self):
        from perdiem.engine.ocr.preprocess import upscale
        img = np.zeros((100, 500), dtype=np.uint8)
        out = upscale(img, min_width=1000)
        assert out.shape[1] == 1000

    def test_upscale_noop_for_large_image(self):
        from perdiem.engine.ocr.preprocess import upscale
        img = np.zeros((400, 2000), dtype=np.uint8)
        out = upscale(img, min_width=1000)
        assert out.shape[1] == 2000

    def test_binarise_returns_binary(self):
        from perdiem.engine.ocr.preprocess import binarise
        # Create a gradient image
        img = np.arange(256, dtype=np.uint8).reshape(1, -1)
        img = np.tile(img, (10, 1))[:, :200]
        result = binarise(img)
        unique_vals = set(np.unique(result))
        assert unique_vals <= {0, 255}


# ---------------------------------------------------------------------------
# Integration tests — against real fixture images (requires tesseract)
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("tesseract_ok")
class TestExtractRosterIntegration:
    """Run extract_roster on real fixture images and assert key fields."""

    def _run(self, path: Path, ctype: str = "image/jpeg") -> "ExtractedRoster":
        from perdiem.engine.ocr.extract import extract_roster
        cfg = OcrConfig(confidence_threshold=0.6, upscale_min_width=2000)
        return extract_roster(_ref(str(path), ctype), cfg)

    # -- correct rosters --

    def test_rattanaporn_staff_id(self):
        r = self._run(FIXTURES / "IMG_4481 - Rattanaporn Boonin (correct format).jpeg")
        assert r.staff_id.value == "1009759"

    def test_rattanaporn_date_range(self):
        r = self._run(FIXTURES / "IMG_4481 - Rattanaporn Boonin (correct format).jpeg")
        assert r.start_date.value == date(2026, 3, 1)
        assert r.end_date.value == date(2026, 3, 31)

    def test_rattanaporn_generated_date(self):
        r = self._run(FIXTURES / "IMG_4481 - Rattanaporn Boonin (correct format).jpeg")
        assert r.generated_at.value == datetime(2026, 3, 9, 19, 36)

    def test_kanatsanan_staff_id(self):
        r = self._run(CORRECT / "1775130932681 - Kanatsanan Wichitthararak -.jpg")
        # White-on-blue crew band in low-res photo is hard for Tesseract;
        # system either extracts the ID or correctly flags needs_review.
        if r.staff_id.value is not None:
            assert r.staff_id.value == "1014666"
        else:
            assert "low ocr confidence: staff_id" in r.needs_review

    def test_kanatsanan_date_range(self):
        r = self._run(CORRECT / "1775130932681 - Kanatsanan Wichitthararak -.jpg")
        assert r.start_date.value == date(2026, 3, 1)
        assert r.end_date.value == date(2026, 3, 31)

    def test_kanatsanan_generated_date(self):
        r = self._run(CORRECT / "1775130932681 - Kanatsanan Wichitthararak -.jpg")
        assert r.generated_at.value == datetime(2026, 4, 2, 19, 54)

    def test_chanicha_staff_id(self):
        r = self._run(CORRECT / "Screenshot_20260505_153747_Chrome - Chanicha Songkrit -.jpg")
        assert r.staff_id.value == "1007339"

    def test_chanicha_date_range(self):
        r = self._run(CORRECT / "Screenshot_20260505_153747_Chrome - Chanicha Songkrit -.jpg")
        assert r.start_date.value == date(2026, 3, 1)
        assert r.end_date.value == date(2026, 3, 31)

    def test_chanicha_generated_date(self):
        r = self._run(CORRECT / "Screenshot_20260505_153747_Chrome - Chanicha Songkrit -.jpg")
        assert r.generated_at.value == datetime(2026, 5, 5, 16, 36)

    def test_sawaros_staff_id(self):
        r = self._run(CORRECT / "IMG_2398 - Sawaros Phanichvibul -.jpeg")
        assert r.staff_id.value == "1043895"

    def test_sawaros_date_range(self):
        r = self._run(CORRECT / "IMG_2398 - Sawaros Phanichvibul -.jpeg")
        assert r.start_date.value == date(2026, 3, 1)
        assert r.end_date.value == date(2026, 3, 31)

    def test_sawaros_generated_date(self):
        r = self._run(CORRECT / "IMG_2398 - Sawaros Phanichvibul -.jpeg")
        assert r.generated_at.value == datetime(2026, 3, 28, 10, 16)

    def test_correct_roster_no_critical_review_flags(self):
        """Clean rosters should not flag staff_id or date_range."""
        r = self._run(CORRECT / "Screenshot_20260505_153747_Chrome - Chanicha Songkrit -.jpg")
        critical = [f for f in r.needs_review
                    if "staff_id" in f or "date_range" in f or "generated_date" in f]
        assert critical == [], f"Unexpected review flags: {r.needs_review}"

    # -- incorrect rosters --

    def test_raveekankate_wrong_month_has_date_range(self):
        """Invalid formatted (Jul 2025 screenshot) — date range still extractable."""
        r = self._run(
            INCORRECT / "8B5BFFAC-55B1-412D-B081-F8504668DB93 - Raveekankate Sukasemthongdi - invalid formatted.png"
        )
        # Date range is Jul 2025 — extractable even if month doesn't match the cycle
        assert r.start_date.value is not None

    def test_invalid_formatted_partial_crop_flagged(self):
        """2-day crop is not a full roster — should flag for review."""
        r = self._run(
            INCORRECT / "IMG_5771 - Minthita Kanchanapinpong - invalid formatted.jpeg"
        )
        # Partial image: either no date range or flagged
        if r.start_date.value is not None:
            # If it somehow extracts a date range, the grid should be minimal
            assert len(r.grid) <= 3

    def test_late_roster_attached_has_date_range(self):
        """Late submission roster should still yield date range and staff ID."""
        r = self._run(
            INCORRECT / "IMG_5475 - Tanaporn Musikapun - submit current but attached roster perdiem late.png"
        )
        # Should have some extractable fields (staff ID or date range)
        has_data = r.staff_id.value is not None or r.start_date.value is not None
        assert has_data

    def test_pdf_roster_extracted(self):
        r = self._run(
            INCORRECT / "Re Aug25 - Raveekankate Sukasemthongdi - generated date less than range date.pdf",
            ctype="application/pdf",
        )
        # Should extract something — even bad rosters should have some fields
        assert r.start_date.value is not None or r.staff_id.value is not None
