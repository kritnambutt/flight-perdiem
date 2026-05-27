"""Form response ingestion: read Posting Base and Late Submission Excel workbooks."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Callable, Iterable

from openpyxl import load_workbook

from perdiem.engine.models import Claim
from perdiem.engine.parsing.thai_dates import normalize_claim_month, parse_thai_day_list

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column-header matchers
# Each entry is: field_name → predicate(header_string) → bool
# ---------------------------------------------------------------------------

_PB_MATCHERS: dict[str, Callable[[str], bool]] = {
    "timestamp": lambda h: h.lower() == "timestamp",
    "email": lambda h: "email" in h.lower(),
    "name": lambda h: "name" in h.lower() and "surname" in h.lower(),
    "staff_id": lambda h: "employee code" in h.lower(),
    "position": lambda h: h.lower() == "position",
    "base": lambda h: "permanent" in h.lower() and "base" in h.lower(),
    "claim_type": lambda h: "ประเภทการเบิก" in h and "ล่าช้า" not in h,
    "claim_month": lambda h: "เดือนที่จะเบิก" in h,
    "claimed_days": lambda h: "ช่วงวันที่เบิก" in h and "ล่าช้า" not in h,
    "roster_links": lambda h: "แนบตารางบิน" in h,
    "crew_remark": lambda h: "หมายเหตุ" in h and "ถ้ามี" in h,
    "admin_remark": lambda h: h.lower() == "remark",
}

_LATE_MATCHERS: dict[str, Callable[[str], bool]] = {
    "timestamp": lambda h: h.lower() == "timestamp",
    "email": lambda h: "email" in h.lower(),
    "name": lambda h: "name" in h.lower() and "surname" in h.lower(),
    "staff_id": lambda h: "employee code" in h.lower(),
    "position": lambda h: h.lower() == "position",
    "base": lambda h: "operating base" in h.lower(),
    "claim_type": lambda h: "ประเภทการเบิก" in h and "ล่าช้า" in h,
    "claim_month": lambda h: "เดือนที่ทำการเบิกล่าช้า" in h,
    "claimed_days": lambda h: "ช่วงวันที่ทำการเบิกล่าช้า" in h,
    "roster_links": lambda h: "แนบตารางบิน" in h,
    "crew_remark": lambda h: "หมายเหตุ" in h and "ถ้ามี" in h,
    "admin_remark": lambda h: h.lower() == "remark",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _index_headers(
    headers: Iterable[Any],
    matchers: dict[str, Callable[[str], bool]],
) -> dict[str, int]:
    """Map field names to column indices using predicate functions on header text."""
    cols: dict[str, int] = {}
    for idx, raw in enumerate(headers):
        if raw is None:
            continue
        h = str(raw).strip()
        for field, pred in matchers.items():
            if field not in cols and pred(h):
                cols[field] = idx
    return cols


def _coerce_staff_id(raw: Any) -> str | None:
    """Convert a float-stored staff ID (e.g. 1012357.0) to string integer."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return str(int(float(s)))
    except (ValueError, TypeError):
        return s or None


def _str_or_none(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _parse_timestamp(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None


def _split_roster_links(raw: Any) -> list[str]:
    """Split a cell that may contain multiple comma-separated Drive URLs."""
    if raw is None:
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip().startswith("http")]


def _cell(row: tuple, cols: dict[str, int], field: str) -> Any:
    idx = cols.get(field)
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _sheet_year(sheet_name: str) -> int | None:
    """Extract the CE year from a sheet name like 'MARCH 26' or 'AUGUST 2025'."""
    m = re.search(r"\b(20\d{2})\b", sheet_name)
    if m:
        return int(m.group(1))
    # Two-digit abbreviated year at end of name (e.g. "MARCH 26")
    m = re.search(r"\b(\d{2})\s*$", sheet_name.strip())
    if m:
        return 2000 + int(m.group(1))
    return None


_MONTH_ALIASES: dict[str, str] = {
    "JANUARY": "JANUARY", "JAN": "JANUARY",
    "FEBRUARY": "FEBRUARY", "FEB": "FEBRUARY", "FEBUARY": "FEBRUARY",
    "MARCH": "MARCH", "MAR": "MARCH",
    "APRIL": "APRIL", "APR": "APRIL",
    "MAY": "MAY",
    "JUNE": "JUNE", "JUN": "JUNE",
    "JULY": "JULY", "JUL": "JULY",
    "AUGUST": "AUGUST", "AUG": "AUGUST",
    "SEPTEMBER": "SEPTEMBER", "SEP": "SEPTEMBER", "SEPT": "SEPTEMBER",
    "OCTOBER": "OCTOBER", "OCT": "OCTOBER",
    "NOVEMBER": "NOVEMBER", "NOV": "NOVEMBER",
    "DECEMBER": "DECEMBER", "DEC": "DECEMBER",
}


def _canonical_month(s: str) -> str | None:
    """Return canonical month name (e.g. 'FEBRUARY') for a token, or None."""
    upper = s.strip().upper()
    for alias in sorted(_MONTH_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{alias}\b", upper):
            return _MONTH_ALIASES[alias]
    return None


def _find_sheet(workbook: Any, cycle_month: str) -> Any | None:
    """
    Find the worksheet matching cycle_month (e.g. 'FEBRUARY 2026').

    Tries: exact name (case-insensitive), abbreviated year (26 for 2026),
    and falls back to just month-name prefix match.
    """
    parts = cycle_month.strip().upper().split()
    if not parts:
        return None
    month_name = parts[0]
    year_full = parts[1] if len(parts) > 1 else ""
    year_short = year_full[-2:] if len(year_full) >= 2 else year_full

    for sheet_name in workbook.sheetnames:
        upper = sheet_name.strip().upper()
        has_month = month_name in upper
        has_year = year_short in upper or year_full in upper
        if has_month and has_year:
            return workbook[sheet_name]

    # Typo-tolerant fallback (e.g. FEBUARY → FEBRUARY already in _MONTH_ALIASES)
    canonical = _MONTH_ALIASES.get(month_name)
    if canonical and canonical != month_name:
        for sheet_name in workbook.sheetnames:
            upper = sheet_name.strip().upper()
            if canonical in upper and (year_short in upper or year_full in upper):
                return workbook[sheet_name]

    return None


def _resolve_sheet(workbook: Any, cycle_month: str, sheet_name: str | None) -> Any | None:
    """
    Pick the worksheet to read.

    When `sheet_name` is given (the admin's explicit choice in the UI) it wins:
    match it exactly, then case-insensitively. If it isn't found, or no override
    was given, fall back to month-based auto-detection (`_find_sheet`).
    """
    if sheet_name:
        if sheet_name in workbook.sheetnames:
            return workbook[sheet_name]
        target = sheet_name.strip().upper()
        for name in workbook.sheetnames:
            if name.strip().upper() == target:
                return workbook[name]
        logger.warning(
            "Requested sheet '%s' not found; falling back to auto-detection", sheet_name
        )
    return _find_sheet(workbook, cycle_month)


def list_sheet_names(source: Any) -> list[str]:
    """Return the worksheet names of a workbook (path or file-like)."""
    wb = load_workbook(source, read_only=True, data_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def suggest_sheet(source: Any, cycle_month: str) -> str | None:
    """Return the sheet name auto-detection would pick for `cycle_month`, if any."""
    wb = load_workbook(source, read_only=True, data_only=True)
    try:
        ws = _find_sheet(wb, cycle_month)
        return ws.title if ws is not None else None
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# Row parsers
# ---------------------------------------------------------------------------

def _parse_pb_row(
    row: tuple,
    cols: dict[str, int],
    sheet_ref: str,
    row_num: int,
) -> Claim:
    g = lambda f: _cell(row, cols, f)
    raw_month = _str_or_none(g("claim_month")) or ""
    # Posting Base month values are already canonical ("MARCH 2026"), keep as-is.
    return Claim(
        source="POSTING_BASE",
        source_row_ref=f"{sheet_ref}!{row_num}",
        timestamp=_parse_timestamp(g("timestamp")),
        email=_str_or_none(g("email")) or "",
        staff_id=_coerce_staff_id(g("staff_id")),
        name=_str_or_none(g("name")) or "",
        position=_str_or_none(g("position")),
        base=_str_or_none(g("base")),
        claim_type=_str_or_none(g("claim_type")),
        claim_month=raw_month.upper().strip(),
        claimed_days=parse_thai_day_list(g("claimed_days")),
        roster_links=_split_roster_links(g("roster_links")),
        crew_remark=_str_or_none(g("crew_remark")),
        admin_remark=_str_or_none(g("admin_remark")),
    )


def _parse_late_row(
    row: tuple,
    cols: dict[str, int],
    sheet_ref: str,
    row_num: int,
    year_hint: int | None,
) -> Claim:
    g = lambda f: _cell(row, cols, f)
    # Late Submission months are messy: "FEB", "มีนาคม", "ธันวาคม 2568", 11.0, etc.
    claim_month = normalize_claim_month(g("claim_month"), year_hint=year_hint)
    return Claim(
        source="LATE",
        source_row_ref=f"{sheet_ref}!{row_num}",
        timestamp=_parse_timestamp(g("timestamp")),
        email=_str_or_none(g("email")) or "",
        staff_id=_coerce_staff_id(g("staff_id")),
        name=_str_or_none(g("name")) or "",
        position=_str_or_none(g("position")),
        base=_str_or_none(g("base")),
        claim_type=_str_or_none(g("claim_type")),
        claim_month=claim_month,
        claimed_days=parse_thai_day_list(g("claimed_days")),
        roster_links=_split_roster_links(g("roster_links")),
        crew_remark=_str_or_none(g("crew_remark")),
        admin_remark=_str_or_none(g("admin_remark")),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_posting_base(
    path: str, cycle_month: str, sheet_name: str | None = None
) -> list[Claim]:
    """
    Read the Posting Base workbook and return all claims for the given cycle month.

    `sheet_name`, when provided, selects the worksheet explicitly (admin override);
    otherwise the month tab is auto-detected. If no tab is found, logs a warning and
    returns an empty list.
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = _resolve_sheet(wb, cycle_month, sheet_name)
        if ws is None:
            logger.warning(
                "Posting Base: no sheet found for '%s' in %s", cycle_month, path
            )
            return []

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        cols = _index_headers(rows[0], _PB_MATCHERS)
        missing = [f for f in ("timestamp", "name", "claimed_days") if f not in cols]
        if missing:
            logger.warning(
                "Posting Base '%s': missing expected columns %s", ws.title, missing
            )

        sheet_ref = f"{path}!{ws.title}"
        claims: list[Claim] = []
        for row_num, row in enumerate(rows[1:], start=2):
            if all(v is None for v in row):
                continue
            claims.append(_parse_pb_row(row, cols, sheet_ref, row_num))
        return claims
    finally:
        wb.close()


def read_late_submission(
    path: str, cycle_month: str, sheet_name: str | None = None
) -> list[Claim]:
    """
    Read the Late Submission workbook and return all claims for the given cycle month.

    cycle_month is the *submission* month (the sheet name), not the claimed month.
    `sheet_name`, when provided, selects the worksheet explicitly (admin override);
    otherwise the month tab is auto-detected. If no tab is found, logs a warning and
    returns an empty list.
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = _resolve_sheet(wb, cycle_month, sheet_name)
        if ws is None:
            logger.warning(
                "Late Submission: no sheet found for '%s' in %s", cycle_month, path
            )
            return []

        year_hint = _sheet_year(ws.title)
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        cols = _index_headers(rows[0], _LATE_MATCHERS)
        missing = [f for f in ("timestamp", "name", "claimed_days") if f not in cols]
        if missing:
            logger.warning(
                "Late Submission '%s': missing expected columns %s", ws.title, missing
            )

        sheet_ref = f"{path}!{ws.title}"
        claims: list[Claim] = []
        for row_num, row in enumerate(rows[1:], start=2):
            if all(v is None for v in row):
                continue
            claims.append(_parse_late_row(row, cols, sheet_ref, row_num, year_hint))
        return claims
    finally:
        wb.close()


def ingest_cycle(
    cycle_month: str,
    pb_path: str | None = None,
    late_path: str | None = None,
    pb_sheet: str | None = None,
    late_sheet: str | None = None,
) -> list[Claim]:
    """
    Read both Posting Base and Late Submission for a cycle month and return
    the merged claim list (no deduplication at this stage).

    Paths default to POSTING_BASE_PATH / LATE_SUBMISSION_PATH env vars if omitted.
    `pb_sheet` / `late_sheet` override sheet auto-detection when supplied.
    """
    from perdiem.config import settings

    pb_path = pb_path or settings.posting_base_path
    late_path = late_path or settings.late_submission_path

    claims: list[Claim] = []
    if pb_path:
        claims.extend(read_posting_base(pb_path, cycle_month, pb_sheet))
    else:
        logger.warning("ingest_cycle: no Posting Base path configured")

    if late_path:
        claims.extend(read_late_submission(late_path, cycle_month, late_sheet))
    else:
        logger.warning("ingest_cycle: no Late Submission path configured")

    return claims
