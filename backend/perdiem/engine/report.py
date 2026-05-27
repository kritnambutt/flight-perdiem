"""Master report and exception report writers: F11 / F12.

PD-REP-002 — generates fresh .xlsx files returned as bytes for HTTP download.
No in-place workbook editing; no file-system I/O.
"""
from __future__ import annotations

import io
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from perdiem.engine.models import Claim, CrewResult, DayVerdict


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MASTER_HEADERS = [
    "Item",
    "New ID No.",
    "Employee name",
    "Period",
    "Days",
    "Total Perdiem (THB)",
    "Email Address",
    "Cross Checked by Supervisor",
    "REMARK",
]

_EXCEPTION_HEADERS = [
    "Item",
    "Staff ID",
    "Employee Name",
    "Email",
    "Source Ref",
    "Claimed Date",
    "Verdict",
    "Rule",
    "Reason",
    "Roster Link",
]

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Header fill colour matching the reference workbook (yellow-ish)
_HEADER_FILL = PatternFill("solid", fgColor="FFF2CC")
_BANNER_FILL = PatternFill("solid", fgColor="D9E1F2")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_date(d: date) -> str:
    return f"{d.day} {_MONTH_NAMES[d.month]} {d.year}"


def format_periods(periods: list[tuple[date, date]]) -> str:
    """Render merged ranges as newline-separated text (DD Month YYYY - DD Month YYYY)."""
    lines: list[str] = []
    for start, end in periods:
        if start == end:
            lines.append(_format_date(start))
        else:
            lines.append(f"{_format_date(start)} - {_format_date(end)}")
    return "\n".join(lines)


def _apply_header_style(ws, row: int, ncols: int) -> None:
    for col in range(1, ncols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True)
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")


def _set_column_widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _to_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Master report (F11)
# ---------------------------------------------------------------------------


def write_master(results: list[CrewResult], month: str) -> bytes:
    """
    Return the master per diem report for one cycle month as .xlsx bytes.

    Columns follow §4.3: Item, New ID No., Employee name, Period, Days,
    Total Perdiem (THB), Email Address, Cross Checked by Supervisor, REMARK.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = month[:31]  # sheet name max 31 chars

    # Row 1: status banner
    now_str = datetime.now().strftime("%d %b %Y %H:%M")
    ws.append([f"Month: {month}", *[""] * 7, f"Last updated: {now_str}  |  Status: OPEN"])
    for col in range(1, len(_MASTER_HEADERS) + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = _BANNER_FILL
        cell.font = Font(bold=True)

    # Row 2: headers
    ws.append(_MASTER_HEADERS)
    _apply_header_style(ws, row=2, ncols=len(_MASTER_HEADERS))

    # Data rows — sorted by staff_id (deterministic, matches aggregate output)
    for item_no, r in enumerate(results, start=1):
        period_text = format_periods(r.periods)
        ws.append([
            item_no,
            r.staff_id,
            r.name,
            period_text,
            r.days,
            r.total_thb,
            r.email,
            "",          # Cross Checked by Supervisor — filled after web review
            r.remark or "",
        ])
        # Wrap period + remark cells
        data_row = item_no + 2  # banner + header
        ws.cell(row=data_row, column=4).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=data_row, column=9).alignment = Alignment(wrap_text=True, vertical="top")

    # Column widths (approximate, matching reference workbook proportions)
    _set_column_widths(ws, [6, 14, 28, 42, 6, 20, 32, 26, 40])

    return _to_bytes(wb)


# ---------------------------------------------------------------------------
# Exception report (F12)
# ---------------------------------------------------------------------------


def write_exceptions(
    claim_verdicts: list[tuple[Claim, list[DayVerdict]]],
    month: str,
) -> bytes:
    """
    Return the exception report for one cycle month as .xlsx bytes.

    Includes every INVALID and NEEDS_REVIEW verdict with its deciding rule,
    reason, source response ref, and roster link for follow-up.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = (month[:20] + " Exceptions")[:31]

    # Banner
    now_str = datetime.now().strftime("%d %b %Y %H:%M")
    ws.append([
        f"Exception Report — {month}",
        *[""] * (len(_EXCEPTION_HEADERS) - 2),
        f"Generated: {now_str}",
    ])
    for col in range(1, len(_EXCEPTION_HEADERS) + 1):
        ws.cell(row=1, column=col).fill = _BANNER_FILL

    # Headers
    ws.append(_EXCEPTION_HEADERS)
    _apply_header_style(ws, row=2, ncols=len(_EXCEPTION_HEADERS))

    item_no = 1
    for claim, verdicts in claim_verdicts:
        roster_link = claim.roster_links[0] if claim.roster_links else ""
        for v in verdicts:
            if v.verdict not in ("INVALID", "NEEDS_REVIEW"):
                continue
            ws.append([
                item_no,
                claim.staff_id or "",
                claim.name,
                claim.email,
                claim.source_row_ref,
                v.claimed_date.isoformat(),
                v.verdict,
                v.rule,
                v.reason or "",
                roster_link,
            ])
            item_no += 1

    _set_column_widths(ws, [6, 12, 26, 30, 18, 14, 14, 6, 50, 40])

    return _to_bytes(wb)
