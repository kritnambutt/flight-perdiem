"""Field normalisers for the ML dataset builder (PD-ML-002).

Turns the messy free-text in the three workbooks into canonical fields:
sheet/month names, Thai ``วันที่ N`` day lists, English ``Period`` ranges, and the
admin disposition → ``(class, rule_hint)`` mapping.

Reuses the engine's pure Thai-date helpers where they already exist; everything
here is dataset prep and lives outside ``perdiem/engine``.
"""
from __future__ import annotations

import re
from datetime import date

from ml.dataset.models import Disposition

# Reuse the engine's pure parsers — no duplication of the Thai-month logic.
from perdiem.engine.parsing.thai_dates import (  # noqa: F401  (re-exported for tests)
    normalize_claim_month,
    parse_thai_day_list,
)

# ---------------------------------------------------------------------------
# Sheet-name → (MONTH, YEAR)
# ---------------------------------------------------------------------------

_MONTH_ALIASES: dict[str, int] = {
    "JANUARY": 1, "JAN": 1,
    "FEBRUARY": 2, "FEB": 2, "FEBUARY": 2,        # FEBUARY: recurring typo in tabs
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

# Longest-first so "SEPTEMBER" matches before "SEP", "MARCH" before "MAR".
_ALIASES_SORTED = sorted(_MONTH_ALIASES, key=len, reverse=True)
_NUM_TOKEN = re.compile(r"\b(\d{1,4})\b")


def parse_sheet_month(sheet_name: str) -> tuple[str, int] | None:
    """Parse a worksheet tab name into ``("MONTH", YEAR)`` or ``None``.

    Tolerant of the inconsistent tabs across the three workbooks:

        "AUGUST 2025" / "AUG 2025" / "MAY 26"        → ("AUGUST", 2025) / …
        "12 December 2019" / "06 JUNE 19"            → ("DECEMBER", 2019) / ("JUNE", 2019)
        "FEBUARY 2025" (typo)                        → ("FEBRUARY", 2025)
        "SEPTEMBER 2023 " (trailing space)           → ("SEPTEMBER", 2023)

    Returns ``None`` for non-monthly tabs ("Form Responses 26", "New report",
    "Sheet68", "New Crew data", …) so the caller can report rather than silently
    drop them.
    """
    if not sheet_name:
        return None
    upper = sheet_name.strip().upper()

    month_num: int | None = None
    for alias in _ALIASES_SORTED:
        if re.search(rf"\b{alias}\b", upper):
            month_num = _MONTH_ALIASES[alias]
            break
    if month_num is None:
        return None

    # Year is the LAST numeric token: handles a leading day prefix ("12 December
    # 2019" → 2019, "06 JUNE 19" → 19). 2-digit years map to 2000+nn (all tabs are
    # 2018–2026); 4-digit years pass through.
    nums = _NUM_TOKEN.findall(upper)
    if not nums:
        return None
    last = int(nums[-1])
    year = last if last >= 1000 else 2000 + last
    return _MONTH_NAMES[month_num], year


def month_key(month: str, year: int) -> tuple[str, int]:
    """Canonicalise a (month, year) join key (uppercased canonical month name)."""
    return month.strip().upper(), int(year)


# ---------------------------------------------------------------------------
# Master "Period" column → list of (start, end) date ranges
# ---------------------------------------------------------------------------

_EN_DATE_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})",
)

# A range separator inside a Period cell: hyphen/en/em dash (optionally spaced) or a
# spaced "to". Anchored so it never matches a letter inside a month name.
_RANGE_SEP = re.compile(r"\s*[-–—]\s*|\s+to\s+")


def _parse_en_date(token: str) -> date | None:
    m = _EN_DATE_RE.search(token)
    if not m:
        return None
    day, mon_name, year = m.group(1), m.group(2), m.group(3)
    upper = mon_name.upper()
    num = None
    for alias in _ALIASES_SORTED:
        if upper.startswith(alias):
            num = _MONTH_ALIASES[alias]
            break
    if num is None:
        return None
    try:
        return date(int(year), num, int(day))
    except ValueError:
        return None


def parse_period(raw: object) -> list[tuple[date, date]]:
    """Parse a master ``Period`` cell into a list of ``(start, end)`` date ranges.

    Handles multi-range cells separated by newlines, e.g.
    ``"26 June 2025 - 27 June 2025\n23 August 2025 - 24 August 2025"`` and a single
    open day (``"3 July 2025"`` → ``(d, d)``). Unparseable fragments are skipped.
    """
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    ranges: list[tuple[date, date]] = []
    for line in re.split(r"[\n;]+", text):
        line = line.strip()
        if not line:
            continue
        # Range separator: a hyphen/dash (with optional spaces) or the word " to ".
        # Must not match letters inside month names (e.g. the 't' in "August").
        parts = _RANGE_SEP.split(line, maxsplit=1)
        start = _parse_en_date(parts[0])
        end = _parse_en_date(parts[1]) if len(parts) > 1 else start
        if start and end:
            ranges.append((start, end))
        elif start:
            ranges.append((start, start))
    return ranges


def days_in_periods(periods: list[tuple[date, date]]) -> int:
    """Inclusive day count across all ranges (each range counts end-start+1)."""
    total = 0
    for start, end in periods:
        if end >= start:
            total += (end - start).days + 1
    return total


# ---------------------------------------------------------------------------
# Admin disposition (the gold WS-3 label) → (class, rule_hint)
# ---------------------------------------------------------------------------

# The admin remark encodes two things that the validation history keeps separate: the
# ACTION taken (pay / no-pay / defer-as-back-claim / await-second-admin) and the REASON
# (which rule tripped). A single remark can carry both — e.g. "รอแก้ไข และทำจ่ายตกเบิก
# … | ไม่มีวันที่ด้านล่างซ้ายมือ" is the DEFER action with an R4 reason. So we scan two
# ordered tables independently. This is the story's "Remark → rule map", split so the
# disposition and the rule_hint don't collapse into one another. Extend as new remarks
# appear; keep negative substrings ahead of the positives they contain.

# Action → disposition. "ไม่จ่ายเงิน" (reject) must precede "จ่ายเงิน" (approve).
ACTION_RULES: list[tuple[str, Disposition]] = [
    ("ไม่จ่ายเงิน", "REJECTED"),
    ("ไม่อนุมัติ", "REJECTED"),
    ("รอแก้ไข", "DEFER_BACKCLAIM"),
    ("ทำจ่ายตกเบิก", "DEFER_BACKCLAIM"),
    ("ตกเบิก", "DEFER_BACKCLAIM"),
    ("รอการตรวจสอบ", "REVIEW"),       # "…จากแอดมินอีกท่าน"
    ("จ่ายเงิน", "APPROVED"),
    ("อนุมัติ", "APPROVED"),
]

# Reason → rule_hint (independent of the action). These are all rejection *reasons*; a
# remark that carries one but no explicit action keyword is taken as a REJECTED.
REASON_RULES: list[tuple[str, str]] = [
    ("ไม่มีวันที่ด้านล่างซ้ายมือ", "R4"),
    ("ไม่มีวันที่ด้านล่างซ้าย", "R4"),
    ("ลงข้อมูลซ้ำ", "R7"),
    ("กรณีเบิกไม่ตรงเดือน", "R8"),
    ("เบิกไม่ตรงเดือน", "R8"),
    ("ต้องแนบ full roster", "DOC_INCOMPLETE"),
    ("full roster", "DOC_INCOMPLETE"),
    ("กรณีเครื่อง AOG", "OUT_OF_SCOPE"),
    ("AOG", "OUT_OF_SCOPE"),
]


def classify_disposition(remark: object) -> tuple[Disposition, str] | None:
    """Map an admin remark to ``(disposition, rule_hint)`` — the gold WS-3 label.

    Two independent ordered scans (see ``ACTION_RULES`` / ``REASON_RULES``):
      * the **action** keyword sets the disposition;
      * the **reason** keyword sets the rule_hint, regardless of the action.

    Resolution when no action keyword is present:
      * a rejection *reason* with no action ⇒ ``REJECTED`` (e.g. a bare "ลงข้อมูลซ้ำ");
      * text present but nothing recognised ⇒ ``("REVIEW", "NONE")`` — never a silent
        guess (N1).

    Returns ``None`` only when the remark is blank, so the caller can apply the
    blank-Remark rule against the master.
    """
    if remark is None:
        return None
    text = str(remark).strip()
    if not text:
        return None

    action: Disposition | None = None
    for needle, disposition in ACTION_RULES:
        if needle in text:
            action = disposition
            break

    rule_hint = "NONE"
    for needle, hint in REASON_RULES:
        if needle in text:
            rule_hint = hint
            break

    if action is None:
        # A rejection reason with no explicit action still means it wasn't paid.
        return ("REJECTED", rule_hint) if rule_hint != "NONE" else ("REVIEW", "NONE")
    return action, rule_hint
