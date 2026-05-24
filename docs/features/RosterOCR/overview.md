# 🗂 Epic Overview — EP-OCR (Roster Extraction)

The RosterOCR epic turns a **Personal Crew Schedule Report** image/PDF into
structured data: the report date range, staff ID, name, generated date, the
per-day flight grid, and the **red rectangle** the crew drew around the days they
are claiming. All extraction is **local and free** (Tesseract + OpenCV) so it
runs on the Raspberry Pi at zero cost.

See [../../REQUIREMENTS.md](../../REQUIREMENTS.md) (§4.4, §6.2) and
[../../plans/implementation-plan.md](../../plans/implementation-plan.md) (Phase 3).

| Story ID    | Title                                  | Reqs    | Status      |
| ----------- | -------------------------------------- | ------- | ----------- |
| PD-OCR-001  | Roster field & flight-grid extraction  | F4, F6  | 📝 Planned  |
| PD-OCR-002  | Red annotation detection (claimed days)| F5      | 📝 Planned  |

**Why local OCR works here:** the roster is a **machine-printed report**, not
handwriting — so Tesseract with good preprocessing reads it well. The only
hand-drawn mark is the red box, which is found with OpenCV colour segmentation,
not OCR.

**Inputs:** cached roster files from [Ingestion](../Ingestion/overview.md).
**Outputs:** an `ExtractedRoster` per file (with per-field confidence) consumed
by [Validation](../Validation/overview.md).

**Key context**
- Image quality varies (phone photos, rotation, glare) → preprocess + confidence
  scoring; low confidence routes to manual review, never a silent guess.
- Sample roster: staff `1009759 RATTANAPORN BOONIN`, range `01/03/2026 –
  31/03/2026`, generated `Mar 09 2026`, red box on 27–28/03 with `FD3012 DMK→HKT`
  / `FD3006 HKT→DMK`.
