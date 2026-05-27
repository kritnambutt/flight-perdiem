"""PIL-based synthetic crew schedule image renderer (PD-ML-006).

Renders a `SyntheticRosterData` into a BGR numpy array (OpenCV convention)
that mimics the AirAsia crew schedule report format:
  - Dark-blue header band with staff ID + name
  - Date-range bar
  - 7-column weekly grid (DD/MM headers, flight cells)
  - "Generated on …" footer

The rendering is realistic enough for Donut fine-tuning but not a pixel-for-
pixel clone — variation across samples (see `augment.py`) matters more than
fidelity.
"""
from __future__ import annotations

from datetime import timedelta

from ml.roster_gen.schema import SyntheticRosterData

# ── Palette ──────────────────────────────────────────────────────────────────

_BLUE      = (27, 58, 107)
_WHITE     = (255, 255, 255)
_BLACK     = (20, 20, 20)
_LIGHT_BG  = (245, 247, 250)
_CELL_BG   = (252, 252, 252)
_BORDER    = (190, 200, 215)
_GRAY_TEXT = (130, 130, 130)

# ── Layout constants ─────────────────────────────────────────────────────────

_W           = 1600
_H           = 1200
_HEADER_H    = 195      # blue band height
_DATEBAR_H   = 48       # date-range bar below header
_FOOTER_H    = 60       # generated-on footer
_DAYS_PER_ROW = 7       # columns per week row


def render_roster(data: SyntheticRosterData) -> "np.ndarray":  # type: ignore[name-defined]
    """Return a BGR uint8 numpy array of the synthetic roster image."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (_W, _H), _WHITE)
    draw = ImageDraw.Draw(img)

    # ── Fonts ────────────────────────────────────────────────────────────────
    try:
        f_title  = ImageFont.load_default(size=26)
        f_header = ImageFont.load_default(size=19)
        f_body   = ImageFont.load_default(size=15)
        f_cell   = ImageFont.load_default(size=13)
        f_tiny   = ImageFont.load_default(size=11)
    except TypeError:
        f_title = f_header = f_body = f_cell = f_tiny = ImageFont.load_default()

    # ── Header band ─────────────────────────────────────────────────────────
    draw.rectangle([(0, 0), (_W, _HEADER_H)], fill=_BLUE)
    draw.text(
        (_W // 2, 22), "Crew Schedule Report",
        fill=_WHITE, font=f_title, anchor="mt",
    )
    crew_line = f"{data.staff_id}  {data.name},  {data.position}  {data.base}"
    draw.text((_W // 2, 70), crew_line, fill=_WHITE, font=f_header, anchor="mt")
    draw.text(
        (_W // 2, 115),
        f"Position: {data.position}   Base: {data.base}",
        fill=(180, 200, 230), font=f_body, anchor="mt",
    )

    # ── Date-range bar ───────────────────────────────────────────────────────
    bar_y = _HEADER_H
    draw.rectangle([(0, bar_y), (_W, bar_y + _DATEBAR_H)], fill=_LIGHT_BG)
    draw.line([(0, bar_y), (_W, bar_y)], fill=_BORDER, width=1)
    dr_text = (
        f"Schedule Period:  "
        f"{data.start_date.strftime('%d/%m/%Y')} – {data.end_date.strftime('%d/%m/%Y')}"
    )
    draw.text((_W // 2, bar_y + _DATEBAR_H // 2), dr_text, fill=_BLACK, font=f_body, anchor="mm")

    # ── Flight grid ──────────────────────────────────────────────────────────
    grid_y     = bar_y + _DATEBAR_H
    grid_h     = _H - grid_y - _FOOTER_H
    days_count = (data.end_date - data.start_date).days + 1
    n_weeks    = max(1, (days_count + _DAYS_PER_ROW - 1) // _DAYS_PER_ROW)
    row_h      = grid_h // n_weeks
    col_w      = _W // _DAYS_PER_ROW

    current  = data.start_date
    week_idx = 0

    while current <= data.end_date:
        col_idx = 0
        while current <= data.end_date and col_idx < _DAYS_PER_ROW:
            cx = col_idx * col_w
            cy = grid_y + week_idx * row_h

            # Cell background + border
            draw.rectangle(
                [(cx, cy), (cx + col_w - 1, cy + row_h - 1)],
                fill=_CELL_BG, outline=_BORDER,
            )

            # Day header
            day_label = current.strftime("%d/%m")
            draw.text(
                (cx + col_w // 2, cy + 5), day_label,
                fill=_BLACK, font=f_cell, anchor="mt",
            )
            draw.line([(cx + 2, cy + 22), (cx + col_w - 3, cy + 22)], fill=_BORDER, width=1)

            # Flight legs in this cell
            legs = data.grid.get(current.day, [])
            ty = cy + 27
            for leg in legs[:3]:
                draw.text((cx + 5, ty), leg.flight_no, fill=_BLACK, font=f_tiny)
                ty += 14
                draw.text(
                    (cx + 5, ty), f"{leg.orig}→{leg.dest}",
                    fill=_BLACK, font=f_tiny,
                )
                ty += 13
                draw.text((cx + 5, ty), leg.dep_time, fill=_GRAY_TEXT, font=f_tiny)
                ty += 14

            if not legs:
                draw.text(
                    (cx + col_w // 2, cy + row_h // 2), "OFF",
                    fill=_GRAY_TEXT, font=f_tiny, anchor="mm",
                )

            col_idx += 1
            current += timedelta(days=1)

        week_idx += 1

    # ── Footer ───────────────────────────────────────────────────────────────
    footer_y = _H - _FOOTER_H
    draw.line([(0, footer_y), (_W, footer_y)], fill=_BORDER, width=1)
    gen_text = f"Generated on {data.generated_at.strftime('%b %d, %Y %H:%M')}"
    draw.text(
        (_W // 2, footer_y + _FOOTER_H // 2), gen_text,
        fill=_GRAY_TEXT, font=f_body, anchor="mm",
    )

    # ── Convert PIL RGB → OpenCV BGR uint8 ──────────────────────────────────
    return np.array(img)[:, :, ::-1].copy()  # RGB→BGR
