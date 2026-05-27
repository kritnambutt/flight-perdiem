"""Parse Thai-language date strings found in the Google Form responses."""
from __future__ import annotations

import re
from typing import Any

_WANTHI_RE = re.compile(r"วันที่\s*(\d+)")

_THAI_MONTH_NUMS: dict[str, int] = {
    "มกราคม": 1,
    "กุมภาพันธ์": 2,
    "มีนาคม": 3,
    "เมษายน": 4,
    "พฤษภาคม": 5,
    "มิถุนายน": 6,
    "กรกฎาคม": 7,
    "กรกฏาคม": 7,   # common misspelling (ฏ for ฎ) seen in form responses
    "สิงหาคม": 8,
    "กันยายน": 9,
    "ตุลาคม": 10,
    "พฤศจิกายน": 11,
    "ธันวาคม": 12,
}

_EN_MONTH_NUMS: dict[str, int] = {
    "JANUARY": 1, "JAN": 1,
    "FEBRUARY": 2, "FEB": 2, "FEBUARY": 2,   # common typo in data
    "MARCH": 3, "MAR": 3,
    "APRIL": 4, "APR": 4,
    "MAY": 5,
    "JUNE": 6, "JUN": 6,
    "JULY": 7, "JUL": 7,
    "AUGUST": 8, "AUG": 8,
    "SEPTEMBER": 9, "SEP": 9, "SEPT": 9,
    "OCTOBER": 10, "OCT": 10,
    "NOVEMBER": 11, "NOV": 11,
    "DECEMBER": 12, "DEC": 12,
}

_MONTH_NAMES: dict[int, str] = {
    1: "JANUARY", 2: "FEBRUARY", 3: "MARCH", 4: "APRIL",
    5: "MAY", 6: "JUNE", 7: "JULY", 8: "AUGUST",
    9: "SEPTEMBER", 10: "OCTOBER", 11: "NOVEMBER", 12: "DECEMBER",
}

# Sorted longest-first so "SEPTEMBER" matches before "SEP".
_EN_ALIASES_SORTED = sorted(_EN_MONTH_NUMS.keys(), key=len, reverse=True)


def parse_thai_day_list(raw: Any) -> list[int]:
    """
    Parse Thai day-number strings into a sorted list of day integers.

        "วันที่ 2, วันที่ 3"  → [2, 3]
        "วันที่ 1"            → [1]
        ""                    → []
    """
    if not raw:
        return []
    return sorted({int(m.group(1)) for m in _WANTHI_RE.finditer(str(raw))})


def normalize_claim_month(raw: Any, year_hint: int | None = None) -> str:
    """
    Normalise various month formats to "MONTH YEAR" (e.g. "FEBRUARY 2026").

    Handles Thai month names, English full names and abbreviations, Buddhist
    calendar years (BE year > 2500 → subtract 543), and numeric month numbers
    (e.g. 11.0 stored as a float → "NOVEMBER"). Falls back to the raw value
    uppercased if the month cannot be identified.
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""

    # Numeric month stored as float (e.g. 11.0 → November)
    try:
        num = int(float(s))
        if 1 <= num <= 12:
            name = _MONTH_NAMES[num]
            return f"{name} {year_hint}" if year_hint else name
    except (ValueError, TypeError):
        pass

    # Extract 4-digit year (CE or Buddhist era)
    year: int | None = year_hint
    year_m = re.search(r"\b(\d{4})\b", s)
    if year_m:
        y = int(year_m.group(1))
        year = y - 543 if y > 2500 else y   # BE → CE conversion

    # Thai month names (checked first; they are unambiguous)
    for thai, num in _THAI_MONTH_NUMS.items():
        if thai in s:
            return f"{_MONTH_NAMES[num]} {year}" if year else _MONTH_NAMES[num]

    # English month names/abbreviations (word-boundary match, longest first)
    upper_s = s.upper()
    for alias in _EN_ALIASES_SORTED:
        if re.search(rf"\b{alias}\b", upper_s):
            return f"{_MONTH_NAMES[_EN_MONTH_NUMS[alias]]} {year}" if year else _MONTH_NAMES[_EN_MONTH_NUMS[alias]]

    return upper_s
