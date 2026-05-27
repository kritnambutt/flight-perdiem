"""Roster field and flight-grid extraction from preprocessed images."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

import numpy as np

from perdiem.engine.models import ExtractedRoster, Field, GridGeometry, Leg, OcrConfig, RosterRef

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MONTH_MAP: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# 3-letter tokens that look like airport codes but are not
_NON_AIRPORT: frozenset[str] = frozenset({
    "OFF", "DAY", "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN",
    "REST", "SWP", "BLK", "OFP", "DLR", "AIR", "ALL", "AND", "THE",
    "FOR", "ARE", "YOU", "CAN", "ITS", "NOT", "OVR", "TRU", "ERT",
    "ALT", "ACE", "SET", "HGB", "CPT", "CFC", "SFC", "TFC", "RVR",
    "CSI", "STA", "DEP", "ARR", "ACT", "SCH", "EST", "ATA", "ATD",
    "SID", "DBK", "DLY", "OPS", "OUT", "FIN", "DED", "ADL", "SAL",
})

_FLIGHT_RE = re.compile(r"^FD\d{3,4}$", re.IGNORECASE)
_AIRPORT_RE = re.compile(r"^[A-Z]{3}$")
_DAY_HEADER_RE = re.compile(r"^(\d{1,2})/\d{2}$")
_TIME_RE = re.compile(r"^[AD]?\d{2}:\d{2}$")

# ---------------------------------------------------------------------------
# Header field extractors (pure regex — unit-testable without OCR)
# ---------------------------------------------------------------------------


def _extract_date_range(text: str) -> tuple[Field[date], Field[date]]:
    """Parse 'DD/MM/YYYY - DD/MM/YYYY' from OCR text."""
    m = re.search(
        r"(\d{2})/(\d{2})/(\d{4})\s*[-–]\s*(\d{2})/(\d{2})/(\d{4})",
        text,
    )
    if m:
        try:
            start = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            end = date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
            return Field(start, 1.0), Field(end, 1.0)
        except ValueError as exc:
            logger.debug("Date range parse error: %s", exc)
    return Field(None, 0.0), Field(None, 0.0)


_NAME_TERM = r"(?:\||[~\-]\s*(?:CC|FO|SC|CP)\b|\([A-Z]+\)|\s+Page\s|\s*\Z)"


def _find_name_for_id(staff_id: str, flat: str) -> str | None:
    """Return the crew name associated with staff_id from 'Other Crew' entries."""
    m = re.search(
        rf"\b{re.escape(staff_id)}\b[~\-\xb0\s]{{1,6}}"
        rf"([A-Z][A-Z,\.\s]{{3,45}}?)\s*{_NAME_TERM}",
        flat,
    )
    return _clean_name(m.group(1)) if m else None


def _extract_crew_line(text: str) -> tuple[Field[str], Field[str]]:
    """
    Extract staff ID (7 digits) and name.

    S1: 7-digit ID in crew header followed by a base code (clean screenshots).
    S2: most-frequent 7-digit ID — subject appears on every flight in the
        'Other Crew' section; other crew appear on only some flights.
    S3: 6-digit ID in crew header area → prepend '1' → verify vs full text.
        Handles phone-photo OCR dropping the leading digit from white-on-blue text.
    S4: bare 7-digit ID fallback.
    """
    flat = " ".join(text.split())

    # S1: crew header with base code
    m = re.search(
        r"\b(\d{7})\b\s+([A-Z][A-Z,\.\s]{3,45}?)"
        r"(?=\s+(?:D[AM]K|HKT|CNX|CEI|UTH|NST|HDY|PHS|KUL)\b)",
        flat,
    )
    if m:
        return Field(m.group(1), 1.0), Field(_clean_name(m.group(2)), 0.9)

    # S2: frequency analysis — subject appears on every flight
    from collections import Counter

    all_ids = re.findall(r"\b(\d{7})\b", flat)
    if all_ids:
        counts = Counter(all_ids)
        most_common_id, freq = counts.most_common(1)[0]
        if freq >= 2:
            name = _find_name_for_id(most_common_id, flat)
            conf = 0.9 if freq >= 3 else 0.8
            return Field(most_common_id, conf), Field(name, 0.85 if name else 0.0)

    # S3: 6-digit ID in header area — OCR drops leading '1' from blue-band text
    header = flat[:400]
    for m6 in re.finditer(r"\b(\d{6})\b", header):
        candidate = "1" + m6.group(1)
        if re.search(rf"\b{re.escape(candidate)}\b", flat):
            name = _find_name_for_id(candidate, flat)
            return Field(candidate, 0.75), Field(name, 0.75 if name else 0.0)

    # S4: any 7-digit ID (very low confidence)
    m = re.search(r"\b(\d{7})\b", flat)
    if m:
        return Field(m.group(1), 0.6), Field(None, 0.0)

    return Field(None, 0.0), Field(None, 0.0)


def _clean_name(raw: str) -> str:
    return re.sub(r"\s{2,}", " ", raw).strip().rstrip(",").strip()


# Base codes that follow the crew name in the header band ("… DMK, CC, FD20").
_BASE_LOOKAHEAD = r"(?=\s+(?:D[AM]K|HKT|CNX|CEI|UTH|NST|HDY|PHS|KUL)\b)"
_HEADER_CREW_RE = re.compile(
    rf"\b(\d{{7}})\b\s+([A-Z][A-Z,\.\s]{{3,45}}?){_BASE_LOOKAHEAD}"
)


def _ocr_header_band(img: np.ndarray, cfg: OcrConfig, band_frac: float = 0.22) -> str:
    """OCR just the top crew-header band of the page.

    The crew line (staff ID + name) is printed white-on-blue in the band at the
    top of the report. Full-page preprocessing (adaptive threshold + denoise on
    the upscaled image) destroys that band, so the staff ID is lost and the
    extractor falls back to a wrong/misread 7-digit number elsewhere on the page.
    Reading a *crop* of the band with a simple Otsu threshold recovers it
    reliably (verified on the white-on-blue rosters). Cheap: the crop is small.
    """
    import cv2
    import pytesseract

    if cfg.auto_orient:
        from perdiem.engine.ocr.preprocess import auto_orient

        img = auto_orient(img, lang=cfg.tesseract_lang)

    h, w = img.shape[:2]
    band = img[0 : max(1, int(h * band_frac)), :]
    if band.shape[1] < 2200:
        scale = 2200 / band.shape[1]
        band = cv2.resize(band, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY) if band.ndim == 3 else band
    _thr, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return pytesseract.image_to_string(otsu, lang=cfg.tesseract_lang)


def _extract_crew_from_band(
    img: np.ndarray, cfg: OcrConfig
) -> tuple[Field[str], Field[str]]:
    """Extract staff ID (+ name) from the top header band of the page image.

    This is the authoritative location of the subject's ID, so a read here is
    high-confidence. Returns (None, None) fields when the band can't be read, so
    the caller can fall back to the full-text crew-line strategies.
    """
    flat = " ".join(_ocr_header_band(img, cfg).split())

    # Preferred: "<id> <NAME, NAME> <BASE>" — the exact header crew-line shape.
    m = _HEADER_CREW_RE.search(flat)
    if m:
        return Field(m.group(1), 0.95), Field(_clean_name(m.group(2)), 0.9)

    # Otherwise the first 7-digit token in the band: the subject's crew line is
    # the only 7-digit ID up here (other crew are listed at the foot of the page).
    m2 = re.search(r"\b(\d{7})\b", flat)
    if m2:
        return Field(m2.group(1), 0.85), Field(None, 0.0)

    return Field(None, 0.0), Field(None, 0.0)


def _extract_generated_date(text: str) -> Field[datetime]:
    """Parse 'Generated on Mar 09, 2026 19:36' from OCR text."""
    m = re.search(
        r"Generated\s+on\s+([A-Za-z]{3})\s+(\d{1,2}),?\s+(\d{4})\s+(\d{2}):(\d{2})",
        text,
        re.IGNORECASE,
    )
    if m:
        month = _MONTH_MAP.get(m.group(1).lower())
        if month:
            try:
                dt = datetime(
                    int(m.group(3)), month, int(m.group(2)),
                    int(m.group(4)), int(m.group(5)),
                )
                return Field(dt, 1.0)
            except ValueError as exc:
                logger.debug("Generated-date parse error: %s", exc)
    return Field(None, 0.0)


# ---------------------------------------------------------------------------
# Flight grid extraction
# ---------------------------------------------------------------------------


def _parse_column_legs(words: list[str]) -> list[Leg]:
    """
    Parse Leg objects from a column's word list (sorted top-to-bottom).

    Expected pattern inside a cell: FD#### [time] ORIG DEST [time] [aircraft]
    """
    legs: list[Leg] = []
    i = 0
    while i < len(words):
        w = words[i].strip().upper()
        if _FLIGHT_RE.match(w):
            flight_no = w.upper()
            airports: list[str] = []
            time_val: str | None = None
            j = i + 1
            while j < min(i + 12, len(words)):
                t = words[j].strip().upper()
                if _FLIGHT_RE.match(t):
                    break  # next flight starts
                if len(airports) < 2 and _AIRPORT_RE.match(t) and t not in _NON_AIRPORT:
                    airports.append(t)
                elif time_val is None and _TIME_RE.match(t):
                    time_val = t
                j += 1
            orig = airports[0] if len(airports) > 0 else None
            dest = airports[1] if len(airports) > 1 else None
            legs.append(Leg(flight_no=flight_no, orig=orig, dest=dest, time=time_val))
            i = j
        else:
            i += 1
    return legs


def _extract_grid_from_words(
    word_data: list[tuple[str, int, int, int, int]],
) -> tuple[dict[int, list[Leg]], GridGeometry]:
    """
    Build the day→legs grid and column geometry from word bounding boxes.

    word_data: list of (text, left, top, width, height) tuples.
    Returns (grid, GridGeometry) where GridGeometry.columns maps day → (x_left, x_right).
    """
    # Find day-header anchors (DD/MM pattern), one per column
    headers: list[tuple[int, int, int]] = []  # (day, x_center, top)
    for text, left, top, width, _height in word_data:
        m = _DAY_HEADER_RE.match(text.strip())
        if m:
            day = int(m.group(1))
            if 1 <= day <= 31:
                headers.append((day, left + width // 2, top))

    if not headers:
        return {}, GridGeometry(columns={})

    # Deduplicate headers: keep first occurrence per day
    seen_days: set[int] = set()
    unique_headers: list[tuple[int, int, int]] = []
    for day, xc, top in sorted(headers, key=lambda h: h[2]):  # by y (top-most)
        if day not in seen_days:
            seen_days.add(day)
            unique_headers.append((day, xc, top))

    # Estimate half column-width from median spacing between adjacent headers
    sorted_by_x = sorted(unique_headers, key=lambda h: h[1])
    if len(sorted_by_x) >= 2:
        spacings = sorted(
            sorted_by_x[i + 1][1] - sorted_by_x[i][1]
            for i in range(len(sorted_by_x) - 1)
        )
        median_spacing = spacings[len(spacings) // 2]
        half_w = max(10, int(median_spacing * 0.55))
    else:
        half_w = 40

    geometry = GridGeometry(columns={day: (xc - half_w, xc + half_w) for day, xc, _ in unique_headers})

    grid: dict[int, list[Leg]] = {}
    for day, xc, hdr_top in unique_headers:
        # Collect words in this column band below the header row
        col_words = [
            (top, text)
            for text, left, top, width, _h in word_data
            if (left + width // 2) >= xc - half_w
            and (left + width // 2) <= xc + half_w
            and top > hdr_top
        ]
        col_words.sort(key=lambda x: x[0])
        legs = _parse_column_legs([w for _, w in col_words])
        if legs:
            grid[day] = legs

    return grid, geometry


def _extract_grid(img: np.ndarray, cfg: OcrConfig) -> tuple[dict[int, list[Leg]], GridGeometry]:
    """Run word-level OCR and extract the flight grid + column geometry."""
    import pytesseract

    data = pytesseract.image_to_data(
        img, lang=cfg.tesseract_lang, output_type=pytesseract.Output.DICT
    )
    word_data: list[tuple[str, int, int, int, int]] = [
        (data["text"][i], data["left"][i], data["top"][i], data["width"][i], data["height"][i])
        for i in range(len(data["text"]))
        if str(data["text"][i]).strip() and int(data["conf"][i]) > 0
    ]
    return _extract_grid_from_words(word_data)


def extract_grid_geometry(img: np.ndarray, cfg: OcrConfig | None = None) -> GridGeometry:
    """
    Extract day-column x-boundaries from a preprocessed roster image.
    Pass the result to detect_red_annotation() along with the original colour image.
    """
    if cfg is None:
        cfg = OcrConfig()
    _grid, geometry = _extract_grid(img, cfg)
    return geometry


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def extract_roster(
    roster: RosterRef,
    cfg: OcrConfig | None = None,
    doctype_cfg: "object | None" = None,
) -> ExtractedRoster:
    """
    Extract all roster fields from a downloaded roster image or PDF.

    If `doctype_cfg` is a DocTypeConfig with enabled=True and a loadable model,
    a doc-type pre-check is performed before Tesseract runs. Non-VALID images
    (NOT_A_ROSTER or UNREADABLE) are returned immediately as NEEDS_REVIEW,
    saving OCR time on garbage attachments (PD-ML-005).

    Returns an ExtractedRoster; low-confidence critical fields populate
    needs_review with reasons.
    """
    import pytesseract

    from perdiem.engine.ocr.preprocess import load_image, preprocess

    if cfg is None:
        cfg = OcrConfig()

    if roster.local_path is None:
        return _empty_result("roster not downloaded")

    # Doc-type gate: skip Tesseract for non-roster attachments (PD-ML-005).
    if doctype_cfg is not None:
        from perdiem.engine.ocr.doctype import safe_classify_doc
        dt_result = safe_classify_doc(roster.local_path, doctype_cfg)  # type: ignore[arg-type]
        if dt_result is not None and dt_result.label != "VALID_ROSTER":
            return _empty_result(
                f"doc-type classifier: {dt_result.label} (conf={dt_result.confidence:.2f})"
            )

    # Load page(s)
    if roster.content_type == "application/pdf":
        from perdiem.engine.ocr.pdf import rasterise_pdf
        raw_images = rasterise_pdf(roster.local_path)
    else:
        raw_images = [load_image(roster.local_path)]

    if not raw_images:
        return _empty_result("no pages in file")

    # Preprocess each page; use all pages for text, but page-0 for the grid
    preprocessed = [
        preprocess(
            img, min_width=cfg.upscale_min_width, lang=cfg.tesseract_lang,
            denoise_enabled=cfg.denoise, auto_orient_enabled=cfg.auto_orient,
        )
        for img in raw_images
    ]

    # Merge full text from all pages for header/footer field extraction
    full_text = "\n".join(
        pytesseract.image_to_string(p, lang=cfg.tesseract_lang)
        for p in preprocessed
    )

    start_date, end_date = _extract_date_range(full_text)
    generated_at = _extract_generated_date(full_text)

    # Staff ID + name: read the top header band first (white-on-blue crew line —
    # the authoritative location), then fall back to the full-text strategies.
    # This prevents the extractor from latching onto a misread / other-crew
    # 7-digit number when the band is lost by full-page preprocessing (the cause
    # of false R5 staff-ID mismatches on otherwise-valid rosters).
    band_id, band_name = _extract_crew_from_band(raw_images[0], cfg)
    ft_id, ft_name = _extract_crew_line(full_text)
    if band_id.value is not None:
        staff_id = band_id
        # Name resolution, best source first: the "Other Crew" line for this ID is
        # plain black-on-white text (OCRs cleanly), unlike the white-on-blue band
        # where the name often garbles even when the digits read. Fall back to the
        # band name, then the full-text crew-line name.
        crew_name = _find_name_for_id(band_id.value, " ".join(full_text.split()))
        if crew_name:
            name = Field(crew_name, 0.85)
        elif band_name.value:
            name = band_name
        else:
            name = ft_name
    else:
        staff_id, name = ft_id, ft_name

    # Grid: use the first page (the one with the schedule grid). The grid cells
    # are much smaller than the header text, so OCR them from a more aggressively
    # upscaled copy of the page than the one used for header fields.
    grid_page = preprocess(
        raw_images[0],
        min_width=max(cfg.upscale_min_width, cfg.grid_upscale_min_width),
        lang=cfg.tesseract_lang,
        denoise_enabled=cfg.denoise,
        auto_orient_enabled=cfg.auto_orient,
    )
    grid, _geometry = _extract_grid(grid_page, cfg)

    # Build needs_review list
    needs_review: list[str] = []
    thr = cfg.confidence_threshold
    if staff_id.confidence < thr:
        needs_review.append("low ocr confidence: staff_id")
    if start_date.confidence < thr or end_date.confidence < thr:
        needs_review.append("low ocr confidence: date_range")
    if generated_at.confidence < thr:
        needs_review.append("low ocr confidence: generated_date")
    if not grid:
        needs_review.append("no flights detected in grid")
    elif start_date.value is not None and end_date.value is not None:
        # An active crew roster has duty on many days; a grid populated for only
        # a handful of days across a multi-week span almost always means the
        # cells were too small/blurry to OCR — not a genuinely empty schedule.
        # Surface it so a reviewer checks the image rather than trusting verdicts
        # built on a grid that was never read.
        span = (end_date.value - start_date.value).days + 1
        if span >= 20 and len(grid) < span // 4:
            needs_review.append(
                f"roster grid OCR unreliable: only {len(grid)} of ~{span} days "
                "have readable flights — verify against the roster image"
            )

    return ExtractedRoster(
        staff_id=staff_id,
        name=name,
        start_date=start_date,
        end_date=end_date,
        generated_at=generated_at,
        grid=grid,
        needs_review=needs_review,
    )


def _empty_result(reason: str) -> ExtractedRoster:
    empty: Field = Field(None, 0.0)
    return ExtractedRoster(
        staff_id=empty,
        name=empty,
        start_date=empty,
        end_date=empty,
        generated_at=empty,
        grid={},
        needs_review=[reason],
    )
