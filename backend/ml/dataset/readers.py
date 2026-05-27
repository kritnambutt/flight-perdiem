"""Workbook + sheet readers for the ML dataset builder (PD-ML-002).

Tolerant readers for the three workbooks: the two Google-Form response workbooks
(Posting Base, Late Submission) and the CCD payroll master. Each reader yields plain
dataclasses of *raw* fields + provenance; normalisation happens in ``normalise.py``
and the join in ``join.py``.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ml.dataset.models import Source
from ml.dataset.normalise import parse_sheet_month

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Raw row dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RawFormRow:
    """A single form submission, fields still raw (strings as stored)."""

    provenance: str                  # "<workbook>!<sheet>!<row>"
    source: Source
    sheet_month: tuple[str, int]     # submission month from the tab name
    staff_id: str | None
    name: str
    claim_type: str | None
    claim_month_raw: Any             # form's claimed-month cell (messy)
    claimed_days_raw: Any            # "วันที่ 2, วันที่ 3"
    crew_remark: str | None
    admin_remark: str | None         # the disposition text (gold label source)
    roster_links: list[str] = field(default_factory=list)


@dataclass
class MasterRow:
    """A reconciled (paid) row from a CCD master monthly sheet."""

    provenance: str
    staff_id: str | None
    name: str
    period_raw: Any                  # "16 May 2025 - 17 May 2025\n..."
    days_raw: Any
    total_thb_raw: Any
    remark: str | None


# ---------------------------------------------------------------------------
# Column-header matchers (predicate on header text, lower-cased)
# ---------------------------------------------------------------------------

# The admin disposition is NOT in a stably-named column: in Posting Base it lands in
# a column whose header is a status-link URL (with a separate, often-blank "Remark"
# column holding the reason); in Late Submission it lives in "เพิ่มหมายเหตุ (ถ้ามี) 2".
# Rather than chase the header, we harvest disposition text from the trailing cells
# *after the roster upload* (excluding the crew's own remark and any link cells) — see
# ``_harvest_admin_text``. So the matchers below only locate the stable structured
# columns plus the crew_remark and roster anchors.
_PB_MATCHERS: dict[str, Callable[[str], bool]] = {
    "name": lambda h: "name" in h.lower() and "surname" in h.lower(),
    "staff_id": lambda h: "employee code" in h.lower(),
    "claim_type": lambda h: "ประเภทการเบิก" in h and "ล่าช้า" not in h,
    "claim_month": lambda h: "เดือนที่จะเบิก" in h,
    "claimed_days": lambda h: "ช่วงวันที่เบิก" in h and "ล่าช้า" not in h,
    "roster_links": lambda h: "แนบตารางบิน" in h,
    "crew_remark": lambda h: "หมายเหตุ" in h and "ถ้ามี" in h and "2" not in h,
}

_LATE_MATCHERS: dict[str, Callable[[str], bool]] = {
    "name": lambda h: "name" in h.lower() and "surname" in h.lower(),
    "staff_id": lambda h: "employee code" in h.lower(),
    "claim_type": lambda h: "ประเภทการเบิก" in h and "ล่าช้า" in h,
    "claim_month": lambda h: "เดือนที่ทำการเบิกล่าช้า" in h,
    "claimed_days": lambda h: "ช่วงวันที่ทำการเบิกล่าช้า" in h,
    "roster_links": lambda h: "แนบตารางบิน" in h,
    "crew_remark": lambda h: "หมายเหตุ" in h and "ถ้ามี" in h and "2" not in h,
}

_MATCHERS_BY_SOURCE: dict[Source, dict[str, Callable[[str], bool]]] = {
    "POSTING_BASE": _PB_MATCHERS,
    "LATE": _LATE_MATCHERS,
}


# ---------------------------------------------------------------------------
# Cell helpers
# ---------------------------------------------------------------------------

def coerce_staff_id(raw: Any) -> str | None:
    """Float-stored IDs (``1012357.0``) → ``"1012357"``; blanks → ``None``."""
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
    return s or None


def _split_roster_links(raw: Any) -> list[str]:
    if raw is None:
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip().startswith("http")]


def _index_headers(
    headers: Iterable[Any], matchers: dict[str, Callable[[str], bool]]
) -> dict[str, int]:
    cols: dict[str, int] = {}
    for idx, raw in enumerate(headers):
        if raw is None:
            continue
        h = str(raw).strip()
        for field_name, pred in matchers.items():
            if field_name not in cols and pred(h):
                cols[field_name] = idx
    return cols


def _cell(row: tuple, cols: dict[str, int], field_name: str) -> Any:
    idx = cols.get(field_name)
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _harvest_admin_text(row: tuple, cols: dict[str, int]) -> str | None:
    """Collect the admin disposition text from a form row's trailing cells.

    The disposition (``จ่ายเงิน`` / ``ไม่จ่ายเงิน`` / ``รอแก้ไข`` …) sits in one or
    more columns *after* the roster upload, but under inconsistent / URL headers. We
    join every text cell at or after the roster column that is neither a link nor the
    crew's own remark. Returns ``None`` if nothing remains (a blank Remark — handled
    by the blank-Remark rule downstream).
    """
    roster_idx = cols.get("roster_links")
    crew_idx = cols.get("crew_remark")
    start = roster_idx + 1 if roster_idx is not None else 0
    parts: list[str] = []
    for idx in range(start, len(row)):
        if idx == crew_idx:
            continue
        val = row[idx]
        if val is None:
            continue
        s = str(val).strip()
        if not s or s.lower().startswith("http"):
            continue
        parts.append(s)
    return " | ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Form workbook reader
# ---------------------------------------------------------------------------

def read_form_sheet(
    path: str, sheet_name: str, source: Source
) -> tuple[list[RawFormRow], tuple[str, int] | None]:
    """Read one monthly tab of a form workbook → (rows, parsed sheet month).

    Returns ``([], None)`` for a tab whose name can't be parsed to a month — the
    caller records it in the quality report rather than dropping it silently (AC-1).
    """
    sheet_month = parse_sheet_month(sheet_name)
    if sheet_month is None:
        return [], None

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return [], sheet_month
        cols = _index_headers(rows[0], _MATCHERS_BY_SOURCE[source])
        wb_name = Path(path).name
        out: list[RawFormRow] = []
        for row_num, row in enumerate(rows[1:], start=2):
            if all(v is None for v in row):
                continue
            out.append(
                RawFormRow(
                    provenance=f"{wb_name}!{sheet_name}!{row_num}",
                    source=source,
                    sheet_month=sheet_month,
                    staff_id=coerce_staff_id(_cell(row, cols, "staff_id")),
                    name=_str_or_none(_cell(row, cols, "name")) or "",
                    claim_type=_str_or_none(_cell(row, cols, "claim_type")),
                    claim_month_raw=_cell(row, cols, "claim_month"),
                    claimed_days_raw=_cell(row, cols, "claimed_days"),
                    crew_remark=_str_or_none(_cell(row, cols, "crew_remark")),
                    admin_remark=_harvest_admin_text(row, cols),
                    roster_links=_split_roster_links(_cell(row, cols, "roster_links")),
                )
            )
        return out, sheet_month
    finally:
        wb.close()


def form_sheet_names(path: str) -> list[str]:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# CCD master reader (3-row header band)
# ---------------------------------------------------------------------------

_MASTER_FIELDS: dict[str, Callable[[str], bool]] = {
    "staff_id": lambda h: "new id" in h or "id no" in h,
    "name": lambda h: "employee name" in h,
    "period": lambda h: h == "period",
    "days": lambda h: h == "days",
    "total_thb": lambda h: "total perdiem" in h,
    "remark": lambda h: h == "remark",
}


def _scan_master_header(rows: list[tuple]) -> tuple[dict[str, int], int] | None:
    """Locate the master header band; return (column map, data-start row index).

    The master tabs use a title row, then a header row (Item/New ID/Employee
    name/Period/Description) and a sub-header row (Days/Total Perdiem/REMARK). We
    scan the first few rows, union the matched columns, and start data after the
    last header row used.
    """
    cols: dict[str, int] = {}
    last_header_idx = -1
    for r_idx, row in enumerate(rows[:8]):
        for c_idx, raw in enumerate(row):
            if raw is None:
                continue
            h = str(raw).strip().lower()
            for field_name, pred in _MASTER_FIELDS.items():
                if field_name not in cols and pred(h):
                    cols[field_name] = c_idx
                    last_header_idx = max(last_header_idx, r_idx)
    if "staff_id" not in cols or "period" not in cols:
        return None
    return cols, last_header_idx + 1


def read_master_sheet(path: str, sheet_name: str) -> list[MasterRow]:
    """Read one CCD master monthly tab → list[MasterRow].

    Returns ``[]`` for non-reconcilable tabs (no recognisable header) — the caller
    reports them. Data rows are those with a numeric staff-ID cell.
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        scanned = _scan_master_header(rows)
        if scanned is None:
            return []
        cols, data_start = scanned
        wb_name = Path(path).name
        out: list[MasterRow] = []
        for row_num, row in enumerate(rows[data_start:], start=data_start + 1):
            staff_id = coerce_staff_id(_cell(row, cols, "staff_id"))
            # Keep only rows that look like a crew line (numeric id).
            if not staff_id or not staff_id.isdigit():
                continue
            out.append(
                MasterRow(
                    provenance=f"{wb_name}!{sheet_name}!{row_num}",
                    staff_id=staff_id,
                    name=_str_or_none(_cell(row, cols, "name")) or "",
                    period_raw=_cell(row, cols, "period"),
                    days_raw=_cell(row, cols, "days"),
                    total_thb_raw=_cell(row, cols, "total_thb"),
                    remark=_str_or_none(_cell(row, cols, "remark")),
                )
            )
        return out
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# Identity registry from crew-data sheets
# ---------------------------------------------------------------------------

_CREW_DATA_SHEET_HINTS = ("crew data", "crew data for number")


def _is_crew_data_sheet(name: str) -> bool:
    low = name.strip().lower()
    return any(hint in low for hint in _CREW_DATA_SHEET_HINTS)


def read_identity_registry(path: str) -> dict[str, dict[str, str]]:
    """Build ``staff_id -> {name_en, name_th}`` from the master's crew-data sheets.

    Used for R5/R5a reconciliation and as identity labels. Scans every tab whose
    name looks like crew data; finds the header row by its "New ID" / "FullName"
    columns. Later sheets win on duplicate IDs (most recent record).
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    registry: dict[str, dict[str, str]] = {}
    try:
        for sheet_name in wb.sheetnames:
            if not _is_crew_data_sheet(sheet_name):
                continue
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))
            # Find header row containing a "New ID" cell.
            hdr_idx = None
            id_col = name_en_col = name_th_col = None
            for r_idx, row in enumerate(rows[:10]):
                lowered = [str(c).strip().lower() if c is not None else "" for c in row]
                if any("new id" in c for c in lowered):
                    hdr_idx = r_idx
                    for c_idx, h in enumerate(lowered):
                        if id_col is None and "new id" in h:
                            id_col = c_idx
                        if name_en_col is None and h == "fullnameeng":
                            name_en_col = c_idx
                        if name_th_col is None and h == "fullnametha":
                            name_th_col = c_idx
                    break
            if hdr_idx is None or id_col is None:
                continue
            for row in rows[hdr_idx + 1:]:
                staff_id = coerce_staff_id(row[id_col] if id_col < len(row) else None)
                if not staff_id or not staff_id.isdigit():
                    continue
                name_en = (
                    _str_or_none(row[name_en_col])
                    if name_en_col is not None and name_en_col < len(row)
                    else None
                )
                name_th = (
                    _str_or_none(row[name_th_col])
                    if name_th_col is not None and name_th_col < len(row)
                    else None
                )
                existing = registry.get(staff_id, {})
                # Merge: a later crew-data sheet may lack name columns — never let an
                # empty value clobber a name already captured from a richer sheet.
                registry[staff_id] = {
                    "name_en": name_en or existing.get("name_en", ""),
                    "name_th": name_th or existing.get("name_th", ""),
                }
        return registry
    finally:
        wb.close()
