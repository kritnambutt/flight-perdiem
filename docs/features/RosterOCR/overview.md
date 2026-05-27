# 🗂 Epic Overview — EP-OCR (Roster Extraction)

The RosterOCR epic turns a **Personal Crew Schedule Report** image/PDF into
structured data: the report date range, staff ID, name, generated date, and the
per-day flight grid. An **optional** red rectangle some crew draw on the roster
is detected as a secondary cross-check (most rosters have none — see PD-OCR-002).
All extraction is **local and free** (Tesseract + OpenCV) so it runs on the
Raspberry Pi at zero cost.

See [../../REQUIREMENTS.md](../../REQUIREMENTS.md) (§4.4, §6.2) and
[../../plans/implementation-plan.md](../../plans/implementation-plan.md) (Phase 3).

| Story ID   | Title                                        | Reqs   | Status                   |
| ---------- | -------------------------------------------- | ------ | ------------------------ |
| PD-OCR-001 | Roster field & flight-grid extraction        | F4, F6 | ✅ Done (116 tests)       |
| PD-OCR-002 | Red annotation detection (optional crosscheck)| F5    | ✅ Done (22 tests)        |

**Why local OCR works here:** the roster is a **machine-printed report**, not
handwriting — so Tesseract with good preprocessing reads it well. The optional
hand-drawn red box is found with OpenCV HSV colour segmentation, not OCR.

**Inputs:** cached roster files from [Ingestion](../Ingestion/overview.md).
**Outputs:** an `ExtractedRoster` + `RedAnnotation` per file (with per-field
confidence) consumed by [Validation](../Validation/overview.md).

**Key context**
- Image quality varies (phone photos, rotation, glare) → preprocess + confidence
  scoring; low confidence routes to manual review, never a silent guess.
- **Claimed days source of truth:** form col-10 list (always present). The red
  box on the roster is an optional annotation — 4 of 5 sample rosters have none.
  A mismatch between box days and form days flags the claim for human review.
- Sample roster with red box: staff `1014666 KANATSANAN WICHITTHARARAK`,
  range `01/03/2026 – 31/03/2026`, two red rectangles visible on the grid.
