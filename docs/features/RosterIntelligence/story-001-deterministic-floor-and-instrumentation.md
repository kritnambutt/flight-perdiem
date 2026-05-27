| Property     | Value                                                          |
| ------------ | -------------------------------------------------------------- |
| Story ID     | PD-ML-001                                                      |
| Title        | Phase 0 — deterministic floor + label/feature instrumentation  |
| Epic         | EP-ML — Roster Intelligence                                    |
| Dependencies | PD-OCR-001 (extraction), PD-VAL-002 (identity), PD-PLAT-001 (verdicts table) |
| Story Type   | Enhancement / Bug                                              |
| Status       | 🚧 In progress — R5 gate + instrumentation done (247 engine tests pass); single-pass OCR deferred to perf track |
| Source       | REQUIREMENTS.md → §5 (R5), §6.2 (F6), §7 (N1); analysis: valid-roster-marked-invalid-r5.md, run-pipeline-performance.md |

## 🗂 Epic Overview — EP-ML

See [overview.md](./overview.md). **Track A (validation correctness).** This story raises the
**deterministic** accuracy floor with no ML, and is **independent of the ML data track** —
the training labels come from the workbooks, not from runs. Its only tie to ML is that the
persisted OCR read becomes a useful *runtime* feature later (PD-ML-007).

## 📝 Feature Overview — PD-ML-001

### User Story

```gherkin
As an admin reviewing per diem claims
I want low-confidence OCR reads sent to review (not silently rejected) and the OCR fields shown
So that an obviously-valid roster is not marked INVALID on an unreliable staff-ID misread

As the engineer measuring the system
I want each run to persist what the OCR actually read, with per-stage timings
So that the Exceptions panel is explainable and I have a measured baseline before any model
```

### Pre-conditions

- The Tesseract/OpenCV extractor (PD-OCR-001) and the rules engine (PD-VAL-001/002) exist.
- The `verdicts` table exists with an `extracted` JSONB column (`db/models.py:112`).

### Scope

#### Included

- **Confidence-gate R5** in `engine/identity.py`: a staff-ID **mismatch** only hard-rejects
  when the roster ID was read at **≥ threshold** confidence; below threshold → `REVIEW`.
- **Persist `extracted`** on each verdict (fields + confidences) so the Exceptions panel
  shows what OCR read (currently written as `None`).
- **Drop the redundant `image_to_string` pass** — rebuild full text from `image_to_data`.
- **Adaptive/optional preprocessing**: make heavy NL-means denoise and OSD auto-orient
  **opt-in** flags (default off; orient as a fallback only).
- **Per-stage + per-item timing** logs in the worker.

#### Excluded

- Any learned model (Track B). OCR process-pool parallelism (perf doc; not a correctness goal).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **R5 confidence gate:** a roster whose staff-ID OCR confidence `< confidence_threshold`
   with a form↔roster ID mismatch yields `NEEDS_REVIEW (R5a)` naming the confidence, **not**
   `INVALID`. A **confident** genuine mismatch still hard-rejects. Re-running the
   `AUGUST 2025` fixtures converts the bulk of the 92 false R5 INVALIDs into reviewable items.
2. **Extracted persisted (N1):** every written verdict carries `extracted` JSON with at
   least `staff_id{value,conf}`, `name{value,conf}`, dates, `generated_at`, `grid_days`.
3. **Single text OCR pass:** `extract_roster` no longer runs both `image_to_string` and
   `image_to_data` on the same page; fixture extractions are field-stable (regression test).
4. **Adaptive preprocessing:** `OcrConfig` gains `denoise: bool=False`, `auto_orient:
   bool=False`; defaults change nothing semantically on clean fixtures.
5. **Timing:** worker logs wall-clock per stage and per item at INFO.

### Validation Rules

- Confidence threshold comes from config (`confidence_threshold`, default 0.6) — not
  hard-coded. Name policy unchanged (ID match + name uncertain → REVIEW; never reject on name).

### Error Scenarios

- Roster staff-ID unreadable/empty → `REVIEW` with reason.
- Text OCR pass fails → OSD-orient + retry once (auto_orient fallback path).

## 🧩 Technical Documentation

### Engine change (identity.py)

```python
if form_id != roster_id:
    if roster.staff_id.confidence < cfg.confidence_threshold:
        return IdentityResult(staff_id_match=False, name_score=0.0, decision="REVIEW",
            reason=f"staff ID uncertain (OCR {roster.staff_id.confidence:.2f}): "
                   f"form={form_id!r} roster={roster_id!r} — verify against roster")
    return IdentityResult(staff_id_match=False, name_score=0.0, decision="REJECT",
        reason=f"staff ID mismatch: form={form_id!r} roster={roster_id!r}")
```

> `RulesConfig` must expose the OCR confidence threshold to the identity check (pass it in),
> keeping the engine pure (no global I/O).

### Persisted `extracted` shape (worker → repository)

```python
extracted = {
    "staff_id": {"value": r.staff_id.value, "conf": r.staff_id.confidence},
    "name":     {"value": r.name.value,     "conf": r.name.confidence},
    "start_date": iso(r.start_date.value), "end_date": iso(r.end_date.value),
    "generated_at": iso(r.generated_at.value),
    "grid_days": len(r.grid), "needs_review": r.needs_review,
}
```

### Required Configuration

| Setting | Default | Purpose |
|---|---|---|
| `confidence_threshold` | 0.6 | R5 reject gate + field review threshold |
| `OcrConfig.denoise` | False | enable heavy NL-means only when needed |
| `OcrConfig.auto_orient` | False | OSD orient as fallback, not every image |

### Security Requirements

- `extracted` may contain PII (name) — it lives in the already auth-gated `verdicts` table.
  Don't log full names at INFO.

## 🔨 Implementation Plan

1. ✅ **DONE** Confidence-gate R5 in `engine/identity.py`. Added `RulesConfig.staff_id_reject_min_confidence` (**0.8**, threaded from config). A mismatch only hard-rejects when the roster ID was read **≥ 0.8** (header-band/frequency reads); the **0.60 bare-fallback misreads** (the real cause of false INVALIDs) route to REVIEW. *(Corrected from an initial 0.6 bar that would not have caught the 0.60 reads.)*
   - 1.1 ✅ **DONE** Unit tests: 0.60 **and** 0.75 mismatch → REVIEW; 1.0 mismatch → REJECT; match unchanged (`test_identity.py`, 19 pass).
   - 1.2 ✅ **DONE** **Header-band staff-ID extraction** (`ocr/extract.py::_extract_crew_from_band`). Crops the top ~22% crew band and OCRs it with Otsu — recovers the white-on-blue staff ID that full-page preprocessing destroyed. Fixes real false mismatches (Late AUG-2025 row 9 Natjaree `1026841`→was `1026885`; row 10 Sujarinee `1009672`→was `1006629`), now read correctly @0.95. Name resolved from the clean black-on-white "Other Crew" line. Verified: 247 engine tests pass.
2. ✅ **DONE** Persist `extracted` in `db/repository.write_verdicts` (was `None`); worker serialises the `ExtractedRoster` + headline confidence.
3. 🚫 **DEFERRED** Drop `image_to_string` / single text pass — this is a **performance** change (B3 in `run-pipeline-performance.md`) with OCR-regression risk; land it with the perf work where it can be benchmarked, not here.
4. ✅ **DONE** Added `denoise`/`auto_orient` flags to `OcrConfig` + `preprocess.py`, wired into `extract.py`. **Default `True` (behaviour-preserving)** rather than off — flipping them off is the perf change and would risk degrading poor-image OCR (the project's core case); defer the default-flip to the perf track.
5. ✅ **DONE** Per-stage (download/ocr/validate) + per-item OCR timing logs in `worker/runner.py`.
6. 📝 **TODO** Re-run `AUGUST 2025` through the full pipeline (needs Postgres + workbooks); record before/after INVALID↔REVIEW counts. *(Engine unit suite already confirms the gate logic; this is the end-to-end confirmation.)*

## 🏗 Structure

```
backend/perdiem/engine/identity.py     # R5 confidence gate
backend/perdiem/engine/ocr/extract.py  # single text pass
backend/perdiem/engine/ocr/preprocess.py
backend/perdiem/engine/models.py       # OcrConfig flags
backend/perdiem/db/repository.py       # persist extracted
backend/perdiem/worker/runner.py       # timing logs
backend/tests/engine/test_identity.py  # +confidence-gate cases
```

## 📌 Notes / Open Questions

- **Parallel, not a prerequisite.** PD-ML-002 (dataset builder) does **not** depend on this
  story — labels come from the workbooks. Ship this for correctness regardless of ML timing.
- Persisted `extracted` becomes a *runtime* feature source for the triage model (PD-ML-004)
  and the hybrid backend (PD-ML-007) — but not a training-label source.
- OCR process-pool parallelism is intentionally out of scope (perf, not correctness).
