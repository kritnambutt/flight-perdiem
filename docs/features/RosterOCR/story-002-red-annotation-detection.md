| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-OCR-002                                         |
| Title        | Red annotation detection (optional cross-check)    |
| Epic         | EP-OCR — Roster Extraction                         |
| Dependencies | Python, OpenCV (HSV masking), PD-OCR-001 grid      |
| Story Type   | Feature                                            |
| Status       | ✅ Done — 22 tests passing (138 total across all engine tests) |
| Source       | REQUIREMENTS.md → §4.4, §6.2 (F5); plan Phase 3    |

## 🗂 Epic Overview — EP-OCR

See [overview.md](./overview.md). This story detects the **optional** red
rectangle/oval some crew draw on the roster and maps it to day column(s) for
cross-checking against the form's claimed-day list.

## 📝 Feature Overview — PD-OCR-002

### User Story

```gherkin
As the per diem validation system
I want to detect a red box on the roster IF the crew drew one
So that I can cross-check it against the form's claimed-day list and flag
any mismatch for human review
```

### Pre-conditions

- The roster image is available and the day-column geometry from PD-OCR-001 is known.
- **The red mark is optional.** Most crew do not draw one (observed in sample
  files: only 1 out of 5 correct rosters has a red annotation). Absence of a
  red box is the expected normal case and must never be treated as an error.

### Scope

#### Included

- Attempt to isolate **red** pixels via OpenCV **HSV colour masking** (handles
  the two red hue ranges at the ends of the hue wheel).
- Find the bounding contour(s) of the red mark if present.
- Map the contour's **x-range to day column(s)** using the grid geometry.
- Return the set of visually-claimed day numbers + a confidence.
- Handle hand-drawn ovals/rectangles and slightly wobbly strokes.
- **Cross-check:** when red-box days differ from the form's claimed-day list,
  surface the discrepancy so validation can flag it for review.

#### Excluded

- OCR of text (PD-OCR-001).
- Deciding whether those days are payable (Validation epic).
- Treating a missing red box as invalid — the form list is always the
  authoritative source.

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Red segmentation (F5)** — HSV mask covering both low and high red hue
   bands; morphological close to join strokes; ignore tiny specks (noise).
2. **Column mapping** — the mark's horizontal span is intersected with
   day-column boundaries; any column with ≥15 % overlap is a candidate day.
3. **Output** — `{claimed_days: set[int], confidence: float, bbox}`.
   - When no red mark is found: `claimed_days = set()`, `confidence = 0.0`,
     `bbox = None`. The **caller** then uses the form's claimed-day list
     directly — this is the normal path.
   - When a red mark is found: `claimed_days` contains the matched day
     numbers and `confidence` reflects detection quality (0.6–0.95).
4. **Primary / secondary source of claimed days:**
   - **Primary (always present):** the form's col-10 claimed-day list.
   - **Secondary (optional):** the red box. When present and matching the
     form list → increases confidence. When present but **mismatching** the
     form list → the validation layer must flag the claim for human review.
5. **No mark found (normal case)** — return empty set; caller uses form data
   exclusively. Must not add a `needs_review` flag solely because no box was
   found.
6. **Mismatch detection hook** — `RedAnnotation.claimed_days` is returned
   as-is; the Validation epic compares it against `Claim.claimed_days` (from
   the form) and applies the mismatch rule.

### Error Scenarios

- Red printed elements (not annotations) falsely detected → size/aspect
  filters and "must overlap day columns" reduce false positives; low
  confidence on doubt.
- Faint red on poor photo → may miss; returns empty set so form list is used.
- Mark spanning two columns (e.g. 27–28) → both days returned (expected,
  matches the out-and-back pair).
- Red box days completely outside the grid geometry → `claimed_days = set()`,
  `confidence = 0.2` (box found but unmappable — treat as not found).

## 🧩 Technical Documentation

### Interface

```python
@dataclass
class RedAnnotation:
    claimed_days: set[int]   # empty when no red mark detected
    confidence: float        # 0.0 when not found; 0.6–0.95 when found
    bbox: tuple[int, int, int, int] | None  # (x, y, w, h) of largest contour

def detect_red_annotation(image: np.ndarray, grid_geometry: GridGeometry) -> RedAnnotation:
    """
    image          — original BGR colour image (NOT the binarised OCR image).
    grid_geometry  — day-column x-boundaries from extract_grid_geometry().
    Returns RedAnnotation; empty claimed_days means no red mark found (normal).
    """
```

### GridGeometry (from PD-OCR-001)

```python
@dataclass
class GridGeometry:
    columns: dict[int, tuple[int, int]]  # day -> (x_left, x_right) px
```

### HSV ranges (starting point — tune against fixture images)

```
lower red 1: H  0–10,   S 70–255, V 50–255
lower red 2: H 170–180, S 70–255, V 50–255
```

### Confidence heuristic

| Situation                         | Confidence |
| --------------------------------- | ---------- |
| No red mask pixels found          | 0.0        |
| Box found, no column overlap      | 0.2        |
| Box found, columns mapped         | 0.6 + 0.35 × fill_ratio |

`fill_ratio` = red pixel count / total bounding-box area (0→1).

## 🔨 Implementation Plan

1. ✅ **DONE** `preprocess.py` — added `orient_and_upscale()` that preserves
   BGR colour channels; output shares coordinate space with OCR word boxes.
2. ✅ **DONE** `models.py` — added `GridGeometry` and `RedAnnotation` dataclasses.
3. ✅ **DONE** `extract.py` — refactored `_extract_grid_from_words` to return
   `(grid, GridGeometry)`; exposed `extract_grid_geometry(img, cfg) -> GridGeometry`.
4. ✅ **DONE** `redbox.py` — HSV red mask (two bands) + morphological close.
5. ✅ **DONE** `redbox.py` — contour detection + size/aspect filtering.
6. ✅ **DONE** `redbox.py` — map bbox x-range → day columns via `_map_to_days`.
7. ✅ **DONE** `redbox.py` — confidence heuristic; empty set + 0.0 when no mark.
8. ✅ **DONE** 22 tests passing (138 total, 0 failures):
   - 6 unit tests for `_red_mask` (both hue bands, false-positive colours).
   - 6 unit tests for `_map_to_days` (single, spanning, no-overlap, thresholds).
   - 7 unit tests for `detect_red_annotation` (synthetic images).
   - 3 integration tests on real fixtures (Kanatsanan detected, Chanicha/Sawaros
     correctly return empty without raising).

## 🏗 Structure

```
backend/perdiem/engine/ocr/
└── redbox.py         # HSV mask -> contour -> day columns
```

## 📌 Notes

- **Open Q resolved (REQUIREMENTS §9 Q3):** the red rectangle is **not always
  present**. Observed in fixtures: 4 of 5 correct rosters have no red box.
  Decision: **form col-10 claimed-day list is the authoritative primary
  source**; the red box is an optional visual annotation used only as a
  cross-check. The Validation epic must not require a red box to pay a claim.
- The Kanatsanan fixture (`1775130932681 - Kanatsanan Wichitthararak -.jpg`)
  is currently the only sample with a red annotation and should be used for
  integration testing.
- REQUIREMENTS R6 phrase "form field 4.1 col 10 / red rectangle" treats both
  as equivalent sources of claimed days; this story clarifies that col-10 is
  primary and the red rectangle is secondary/optional.
