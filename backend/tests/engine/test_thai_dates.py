"""Unit tests for Thai date/month parsers (no DB, no filesystem)."""
import pytest

from perdiem.engine.parsing.thai_dates import normalize_claim_month, parse_thai_day_list


class TestParseThaiDayList:
    def test_single_day(self):
        assert parse_thai_day_list("วันที่ 1") == [1]

    def test_two_days(self):
        assert parse_thai_day_list("วันที่ 2, วันที่ 3") == [2, 3]

    def test_many_days(self):
        raw = "วันที่ 2, วันที่ 3, วันที่ 16, วันที่ 17, วันที่ 26, วันที่ 27"
        assert parse_thai_day_list(raw) == [2, 3, 16, 17, 26, 27]

    def test_24_days(self):
        raw = "วันที่ 2, วันที่ 3, วันที่ 4, วันที่ 5, วันที่ 6, วันที่ 7, วันที่ 8, วันที่ 9, วันที่ 10, วันที่ 11, วันที่ 12, วันที่ 13, วันที่ 16, วันที่ 17, วันที่ 18, วันที่ 19, วันที่ 20, วันที่ 21, วันที่ 22, วันที่ 23, วันที่ 24, วันที่ 25, วันที่ 26, วันที่ 28"
        result = parse_thai_day_list(raw)
        assert len(result) == 24
        assert result == sorted(result)

    def test_deduplicates(self):
        assert parse_thai_day_list("วันที่ 5, วันที่ 5") == [5]

    def test_extra_spaces(self):
        assert parse_thai_day_list("วันที่  1,  วันที่  2") == [1, 2]

    def test_empty_string(self):
        assert parse_thai_day_list("") == []

    def test_none(self):
        assert parse_thai_day_list(None) == []

    def test_result_is_sorted(self):
        result = parse_thai_day_list("วันที่ 15, วันที่ 3, วันที่ 9")
        assert result == [3, 9, 15]


class TestNormalizeClaimMonth:
    def test_already_canonical(self):
        assert normalize_claim_month("MARCH 2026") == "MARCH 2026"

    def test_february_2026(self):
        assert normalize_claim_month("FEBRUARY 2026") == "FEBRUARY 2026"

    def test_english_short(self):
        assert normalize_claim_month("FEB", year_hint=2026) == "FEBRUARY 2026"

    def test_english_full_no_year(self):
        assert normalize_claim_month("February", year_hint=2026) == "FEBRUARY 2026"

    def test_english_trailing_space(self):
        assert normalize_claim_month("March ", year_hint=2026) == "MARCH 2026"

    def test_thai_month(self):
        assert normalize_claim_month("มีนาคม", year_hint=2026) == "MARCH 2026"

    def test_thai_december(self):
        assert normalize_claim_month("ธันวาคม", year_hint=2025) == "DECEMBER 2025"

    def test_thai_with_buddhist_year(self):
        # ธันวาคม 2568 BE = December 2025 CE
        assert normalize_claim_month("ธันวาคม 2568") == "DECEMBER 2025"

    def test_english_with_ce_year(self):
        assert normalize_claim_month("December 2025") == "DECEMBER 2025"

    def test_numeric_float_month(self):
        # 11.0 stored as float from Google Sheets → November
        assert normalize_claim_month(11.0, year_hint=2025) == "NOVEMBER 2025"

    def test_febuary_typo(self):
        assert normalize_claim_month("FEBUARY 2025") == "FEBRUARY 2025"

    def test_no_year_no_hint(self):
        # Month without year and no hint → just month name
        assert normalize_claim_month("FEB") == "FEBRUARY"

    def test_empty(self):
        assert normalize_claim_month("") == ""

    def test_none(self):
        assert normalize_claim_month(None) == ""

    def test_january_thai(self):
        assert normalize_claim_month("มกราคม", year_hint=2026) == "JANUARY 2026"
