| Property     | Value                                                          |
| ------------ | -------------------------------------------------------------- |
| Story ID     | PD-ML-003                                                      |
| Title        | Per-field & end-to-end eval harness + baseline                 |
| Epic         | EP-ML — Roster Intelligence                                    |
| Dependencies | PD-ML-002 (dataset)                                            |
| Story Type   | Infrastructure                                                 |
| Status       | ✅ Done — harness + frozen baseline built; scores any backend on the held-out split; 8 tests pass. |
| Source       | REQUIREMENTS.md → §6.2 (F6), §6.3 (F7), §7 (N1)                |

## 🗂 Epic Overview — EP-ML

See [overview.md](./overview.md). The eval harness turns "validation doesn't work" into a
**number** — per-field extraction accuracy and the end-to-end agreement with the CCD master
on a held-out month. It produces the **baseline** that decides whether the heavy Donut reader
(PD-ML-006) is even warranted.

## 📝 Feature Overview — PD-ML-003

### User Story

```gherkin
As the engineer deciding where to invest
I want to measure the current extractor and pipeline against the held-out month's approved outcomes
So that every later model is judged against a fixed baseline, and the Donut decision is evidence-based not guessed
```

### Pre-conditions

- A versioned dataset exists (PD-ML-002), including a held-out **test month**.

### Scope

#### Included

- **Per-field metrics** on the vision split: staff_id exact-match, name normalised-match
  (reuse `identity.normalize`), date-range & generated-date exact-match, grid per-day leg
  precision/recall.
- **End-to-end KPI** on the text+vision data: for a held-out month, **% of claims whose final
  payable days match the CCD master with no human intervention**, the **review-queue size**,
  and the **machine-vs-human disagreement rate**.
- A **baseline run** of the *current* Tesseract+rules pipeline through the harness, recorded
  as the reference all later stories report against.
- A **confusion/error report** bucketed by rule (R1/R4/R5/…) and by failure cause
  (OCR-misread vs genuine reject) so regressions are legible.

#### Excluded

- Training any model. The harness only *scores* an extractor/decision backend.

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Backend-agnostic:** the harness scores any object implementing the extractor interface
   (Tesseract today, Donut later) — same metrics, same held-out split.
2. **Per-field report:** prints/saves staff_id, name, dates, generated-date, grid metrics
   with counts and confidence-stratified breakdown.
3. **End-to-end report:** auto-pass accuracy vs master, review-queue size, disagreement rate.
4. **Baseline recorded:** current pipeline's numbers are committed to the analysis doc as the
   reference; re-runnable to detect regressions.
5. **No leakage:** evaluation uses only the `test` split; assertion fails if a train/val crew
   or month leaks in.

### Validation Rules

- Name match uses the **same** `normalize` + threshold the engine uses (no metric drift).
- Grid scoring keys on `(day, flight_no, orig, dest)`; time is ignored (matches rule scope).

### Error Scenarios

- A field has no ground-truth label → excluded from that field's denominator, counted in a
  coverage line (don't silently inflate accuracy).

## 🧩 Technical Documentation

### Metric interface

```python
@dataclass
class FieldMetrics:
    staff_id_acc: float
    name_match_rate: float
    date_range_acc: float
    generated_date_acc: float
    grid_leg_precision: float
    grid_leg_recall: float

@dataclass
class E2EMetrics:
    auto_pass_match_master: float   # the headline KPI
    review_queue_frac: float
    disagreement_rate: float

def evaluate(extractor: Extractor, dataset_split) -> tuple[FieldMetrics, E2EMetrics]: ...
```

### Required Configuration

- `ML_EVAL_TEST_MONTH` (e.g. `AUGUST 2025`); `ML_REPORT_DIR` (default `data/ml/reports`).

### Security Requirements

- Reports may quote names → kept local; aggregate metrics only when sharing.

## 🔨 Implementation Plan

1. ✅ **DONE** `Extractor` protocol + `TesseractExtractor` adapter (`perdiem/engine/ocr/base.py`), shared with PD-ML-007.
2. ✅ **DONE** Per-field scorers reusing `identity.normalize` + the engine fuzzy/threshold; grid leg P/R (`ml/eval/scorers.py`).
3. ✅ **DONE** End-to-end decision scorer vs the gold disposition (`ml/eval/e2e.py`); baseline = "review everything" (the manual status quo).
4. ✅ **DONE** Leakage guard `assert_no_leakage` (fails if a non-test-split row leaks in).
5. ✅ **DONE** Baseline recorded in [../../analysis/ml-baseline.md](../../analysis/ml-baseline.md); CLI `scripts/eval_ml.py` writes a re-runnable md/json report.

### Notes on what's measurable now

- **Splitting is crew-grouped** (PD-ML-002), which already gives the leakage guarantee
  the story cares about (no crew in both train and test). `ML_EVAL_TEST_MONTH` is
  available for a month-scoped view; the default scores the crew-held-out `test` split.
- **Per-field metrics require the vision split** (cached roster images + field labels).
  The scorers are built and unit-tested; numbers populate once the roster cache is
  populated and field labels exist — until then they report coverage 0 (never inflated).
- The headline KPI on the **text** data is the **decision/routing** quality, which is
  what PD-ML-004 moves.

## 🏗 Structure

```
backend/ml/eval/
├── metrics.py        # FieldMetrics, E2EMetrics
├── scorers.py        # per-field + grid scorers
├── e2e.py            # claims→verdicts→payable vs master
└── run_baseline.py
scripts/eval_ml.py    # CLI: eval_ml.py --backend tesseract --split test
backend/tests/ml/test_eval_metrics.py
```

## 📌 Notes / Open Questions

- **This is the decision gate for PD-ML-006.** If PD-ML-001 (floor) + PD-ML-004 (triage)
  push the headline KPI high enough on the held-out month, the Donut reader may be deferred.
- Keep the held-out month **frozen** across all experiments; rotate only deliberately.
