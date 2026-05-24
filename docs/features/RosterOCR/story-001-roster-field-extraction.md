| Property     | Value                                                     |
| ------------ | --------------------------------------------------------- |
| Story ID     | PD-OCR-001                                                |
| Title        | Roster field & flight-grid extraction (OCR)               |
| Epic         | EP-OCR — Roster Extraction                                |
| Dependencies | Python, Tesseract (pytesseract), OpenCV, Pillow, PyMuPDF  |
| Story Type   | Feature                                                   |
| Source       | REQUIREMENTS.md → §4.4, §6.2 (F4, F6); plan Phase 3       |

## 🗂 Epic Overview — EP-OCR

See [overview.md](./overview.md). This story extracts the printed fields and the
flight grid from a roster, with a confidence score per field.

## 📝 Feature Overview — PD-OCR-001

### User Story

```gherkin
As the per diem validation system
I want to read the staff ID, name, date range, generated date and flight grid from a roster
So that the claim can be matched to its owner and validated against flown DMK↔HKT duty

As an admin
I want low-confidence extractions flagged
So that I review unclear rosters instead of trusting a wrong OCR guess
```

### Pre-conditions

- A cached roster file (image or PDF) exists (PD-ING-002).
- Tesseract + OpenCV available in the runtime image.

### Scope

#### Included

- **Preprocess** (OpenCV/Pillow): orient/deskew, grayscale, threshold, denoise,
  upscale low-res photos.
- Rasterise **PDF** pages to images (PyMuPDF) before OCR.
- Extract **report date range** (`01/03/2026 - 31/03/2026`).
- Extract **staff ID** (7 digits) and **name** from the crew line.
- Extract **generated date** from the footer (`Generated on Mar 09, 2026 19:36`).
- Extract the **flight grid**: per day → list of `(flight_no, orig, dest, time)`.
- **Per-field confidence**; below threshold → `NEEDS_REVIEW`.

#### Excluded

- Red rectangle detection (PD-OCR-002).
- Applying eligibility rules (Validation epic).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Preprocessing** — a configurable pipeline runs before OCR; deskew and
   upscale measurably improve accuracy on the sample phone photo.
2. **Header fields (F4)**
   - Date range parsed into `start_date`, `end_date`.
   - Staff ID validated as 7 digits; name captured as raw + normalised forms.
   - Generated date parsed to a timezone-aware datetime.
3. **Flight grid (F4)**
   - Day columns segmented using the report's grid layout; each cell yields zero
     or more legs `(flight_no like FD####, orig, dest 3-letter, time)`.
   - Multi-leg days are preserved as a list.
4. **Confidence (F6)**
   - Each field carries a 0–1 confidence (Tesseract word confidence + regex
     sanity, e.g. staff ID is 7 digits, dates parse).
   - If any critical field (staff ID, date range, generated date) is below
     threshold → the roster is `NEEDS_REVIEW(low ocr confidence:<field>)`.
5. **Determinism** — same image → same extraction (no random model calls).

### Error Scenarios

- Rotated/upside-down scan → deskew; if still unreadable, low confidence → review.
- Glare/occlusion hiding a field → that field low confidence → review.
- Multi-page PDF → OCR the page(s) containing the report; ignore blanks.
- Non-roster image (wrong attachment) → fields fail sanity → review.

## 🧩 Technical Documentation

### ExtractedRoster model

```python
@dataclass
class Leg:
    flight_no: str        # "FD3012"
    orig: str             # "DMK"
    dest: str             # "HKT"
    time: str | None

@dataclass
class Field[T]:
    value: T | None
    confidence: float     # 0..1

@dataclass
class ExtractedRoster:
    staff_id: Field[str]
    name: Field[str]
    start_date: Field[date]
    end_date: Field[date]
    generated_at: Field[datetime]
    grid: dict[int, list[Leg]]    # day-of-month -> legs
    needs_review: list[str]       # reasons where confidence < threshold
```

### Interface

```python
def extract_roster(roster: RosterRef, cfg: OcrConfig) -> ExtractedRoster: ...
```

### Config

| Setting               | Default | Purpose                          |
| --------------------- | ------- | -------------------------------- |
| `confidence_threshold`| 0.6     | below → NEEDS_REVIEW             |
| `upscale_min_dpi`     | 200     | upscale small photos             |
| `tesseract_lang`      | eng     | printed English report           |

## 🔨 Implementation Plan

1. 📝 **TODO** Preprocess module (deskew, grayscale, threshold, denoise, upscale).
2. 📝 **TODO** PDF rasterisation (PyMuPDF) feeding the same pipeline.
3. 📝 **TODO** Header field extractors (date range, staff id, name, generated date) + regex sanity.
4. 📝 **TODO** Day-cell segmentation + per-cell leg parsing.
5. 📝 **TODO** Confidence scoring + NEEDS_REVIEW reasons.
6. 📝 **TODO** Benchmark on `docs/example-files` sample; record accuracy.
7. 📝 **TODO** (Only if needed) evaluate local PaddleOCR/EasyOCR fallback.

## 🏗 Structure

```
backend/perdiem/engine/ocr/
├── preprocess.py     # deskew, threshold, denoise, upscale
├── extract.py        # header fields + flight grid + confidence
└── pdf.py            # PyMuPDF rasterisation
```

## 📌 Notes / Open Questions

- Time prefixes on legs (`A`/`D` for actual/scheduled) — needed for validation or
  ignore? Likely ignore; only route + flight number matter.
- Tune `confidence_threshold` after benchmarking against real submissions.
