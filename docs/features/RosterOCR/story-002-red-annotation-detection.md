| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-OCR-002                                         |
| Title        | Red annotation detection (claimed days)            |
| Epic         | EP-OCR — Roster Extraction                         |
| Dependencies | Python, OpenCV (HSV masking), PD-OCR-001 grid      |
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §4.4, §6.2 (F5); plan Phase 3    |

## 🗂 Epic Overview — EP-OCR

See [overview.md](./overview.md). This story finds the **red rectangle/oval** the
crew draws on the roster and maps it to the day column(s) being claimed.

## 📝 Feature Overview — PD-OCR-002

### User Story

```gherkin
As the per diem validation system
I want to detect the red box the crew drew on the roster
So that I know which specific days they are claiming and can cross-check the form
```

### Pre-conditions

- The roster image is available and the day-column geometry from PD-OCR-001 is known.

### Scope

#### Included

- Isolate **red** pixels via OpenCV **HSV colour masking** (handles the two red
  hue ranges at the ends of the hue wheel).
- Find the bounding contour(s) of the red mark.
- Map the contour's **x-range to day column(s)** using the grid geometry.
- Return the set of claimed day-of-month numbers + a confidence.
- Handle hand-drawn ovals/rectangles and slightly wobbly strokes.

#### Excluded

- OCR of text (PD-OCR-001).
- Deciding whether those days are payable (Validation epic).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Red segmentation (F5)** — HSV mask covering both low and high red hue bands;
   morphological close to join strokes; ignore tiny specks (noise).
2. **Column mapping** — the mark's horizontal span is intersected with day-column
   boundaries; any column with sufficient overlap is a claimed day.
3. **Output** — `{claimed_days: set[int], confidence: float, bbox}`.
4. **Cross-check hook** — claimed days are returned so Validation can reconcile
   them against the form's claimed-day list (the form list is the fallback when
   no red mark is found — see Open Q).
5. **No mark found** — return empty set with low confidence (not an error).

### Error Scenarios

- Red printed elements (not annotations) falsely detected → size/aspect filters
  and "must overlap day columns" reduce false positives; low confidence on doubt.
- Faint red on poor photo → may miss; flag low confidence so the form list is used.
- Mark spanning two columns (e.g. 27–28) → both days returned (expected, matches
  the out-and-back pair).

## 🧩 Technical Documentation

### Interface

```python
@dataclass
class RedAnnotation:
    claimed_days: set[int]
    confidence: float
    bbox: tuple[int, int, int, int] | None

def detect_red_annotation(image, grid_geometry) -> RedAnnotation: ...
```

### HSV ranges (starting point)

```
lower red 1: H 0–10,   S 70–255, V 50–255
lower red 2: H 170–180, S 70–255, V 50–255
```

## 🔨 Implementation Plan

1. 📝 **TODO** HSV red mask (two bands) + morphological close.
2. 📝 **TODO** Contour detection + size/aspect filtering.
3. 📝 **TODO** Map bbox x-range → day columns using grid geometry from PD-OCR-001.
4. 📝 **TODO** Confidence heuristic; empty-set-on-no-mark.
5. 📝 **TODO** Test on the sample roster (expect {27, 28}).

## 🏗 Structure

```
backend/perdiem/engine/ocr/
└── redbox.py         # HSV mask -> contour -> day columns
```

## 📌 Notes / Open Questions

- **Primary source of claimed days?** REQUIREMENTS §9 Q3: is the red box always
  present, or should the form's claimed-day list be primary with the box as
  cross-check? Current lean: form list primary, red box confirms/explains.
