from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

Verdict = Literal["VALID", "VALID_BACKCLAIM", "NEEDS_REVIEW", "INVALID"]


@dataclass
class DayVerdict:
    claimed_date: date
    verdict: Verdict
    rule: str        # "R1", "R2", "R3", "R4", "R5", "R5a", "R6", "R8"
    reason: str | None
    remark: str | None = None  # e.g. back-claim Thai note


@dataclass
class RosterRef:
    source_url: str
    file_id: str | None
    local_path: str | None       # cache/<file_id>.<ext>
    content_type: str | None     # image/jpeg | image/png | application/pdf
    status: Literal["OK", "UNREACHABLE", "UNSUPPORTED"]


@dataclass
class Claim:
    source: Literal["POSTING_BASE", "LATE"]
    source_row_ref: str           # "<path>!<sheet>!<row>" for audit
    timestamp: datetime | None
    email: str
    staff_id: str | None          # Employee Code; None → NEEDS_REVIEW
    name: str
    position: str | None
    base: str | None
    claim_type: str | None
    claim_month: str              # canonical "FEBRUARY 2026"
    claimed_days: list[int] = field(default_factory=list)  # [2, 3]
    roster_links: list[str] = field(default_factory=list)
    crew_remark: str | None = None
    admin_remark: str | None = None


# ---------------------------------------------------------------------------
# OCR models
# ---------------------------------------------------------------------------

_T = TypeVar("_T")


@dataclass
class OcrConfig:
    confidence_threshold: float = 0.6
    upscale_min_width: int = 2000  # upscale if image width < this (pixels)
    # The calendar grid cells are far smaller than the header text, so the grid
    # is OCR'd from a more aggressively upscaled copy of the page.
    grid_upscale_min_width: int = 3500
    tesseract_lang: str = "eng"
    # PD-ML-001: preprocessing steps made configurable. Non-local-means denoise
    # and the Tesseract OSD orientation pass are the two heaviest steps; keeping
    # them on by default preserves current behaviour, but they can be disabled
    # (e.g. for the Pi performance work) without changing the extraction code.
    denoise: bool = True
    auto_orient: bool = True


@dataclass
class Field(Generic[_T]):
    value: _T | None
    confidence: float  # 0..1


@dataclass
class Leg:
    flight_no: str       # "FD3012"
    orig: str | None     # "DMK"
    dest: str | None     # "HKT"
    time: str | None     # "A17:00"


@dataclass
class GridGeometry:
    columns: dict[int, tuple[int, int]]  # day -> (x_left, x_right) in pixels


@dataclass
class RedAnnotation:
    claimed_days: set[int]              # empty when no red mark found (normal case)
    confidence: float                   # 0.0 = not found; 0.6-0.95 = found
    bbox: tuple[int, int, int, int] | None  # (x, y, w, h) of largest contour


@dataclass
class CrewResult:
    staff_id: str
    name: str
    email: str
    periods: list[tuple[date, date]]  # merged consecutive ranges, sorted
    days: int                          # unique payable day count
    total_thb: int                     # days * rate_thb_per_day
    remark: str | None = None          # back-claim notes / reconciliation flags


@dataclass
class ExtractedRoster:
    staff_id: Field[str]
    name: Field[str]
    start_date: Field[date]
    end_date: Field[date]
    generated_at: Field[datetime]
    grid: dict[int, list[Leg]]   # day-of-month -> legs
    needs_review: list[str]      # low-confidence reasons
