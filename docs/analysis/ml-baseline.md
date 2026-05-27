# ML Baseline — Roster Intelligence (PD-ML-003)

The frozen reference every later EP-ML model reports against. Produced by the eval
harness (`scripts/eval_ml.py`) on the **crew-held-out `test` split** of the dataset
built by PD-ML-002. Re-runnable; the live report (with names) stays local under
`ML_REPORT_DIR`, only aggregate numbers are recorded here.

- **Dataset:** `dev` / `2026-05` — both produce identical rows (5,745 text; 876 test),
  confirming the baseline is stable across version names.
- **Split:** `test` (crew-grouped — no crew appears in train; 876 rows)
- **Ground truth:** admin `disposition` (abundant, complete).
- **Commands run (2026-05-27):**
  ```bash
  make ml-eval ARGS="--dataset-version 2026-05 --split test"
  make ml-eval ARGS="--dataset-version 2026-05 --split test --triage-model data/ml/models/triage.json"
  make ml-eval ARGS="--dataset-version 2026-05 --split test --with-fields"
  ```

## End-to-end decision KPIs

| Backend | auto-pass match | auto-pass % | auto-reject % | review % | disagree |
| --- | ---: | ---: | ---: | ---: | ---: |
| `review_all` (status quo) | — | 0.000 | 0.000 | **1.000** | 0.000 |
| `triage_calibrated` (PD-ML-004) | — | 0.000 | 0.000 | 1.000 | 0.000 |
| `triage@0.70` (advisory cut) | **0.780** | 0.628 | 0.000 | 0.372 | 0.220 |

- **`review_all`** is the manual baseline: every claim is reviewed by hand (auto-pass
  nothing). The win condition for any model is a **lower review %** at **high auto-pass
  match** and **low disagreement**.
- **`triage_calibrated`** uses the threshold calibrated for ≥0.90 auto-pass precision.
  On text-only features that bar is **unreachable**, so the model correctly **abstains**
  (everything → review). This is the N1-safe behaviour, not a regression.
- **`triage@0.70`** shows the achievable tradeoff: auto-pass 63% of claims at **0.78**
  precision (review queue cut to 37%) — but 0.78 is **below a safe auto-pay bar**, so
  triage ships **disabled** (`TRIAGE_ENABLED=false`) and stays advisory for now.

## Reason-hint accuracy (advisory; 295 non-APPROVED rows)

- **Top-1: 0.502 · Top-2: 0.776**

| rule_hint | top-1 acc |
| --- | ---: |
| OUT_OF_SCOPE | 1.000 |
| NONE | 0.533 |
| R4 | 0.408 |
| DOC_INCOMPLETE | 0.333 |
| R8 | 0.250 |
| R7 | 0.200 |

## Per-field extraction (vision split)

Not yet measurable — the vision split is empty until the roster cache is populated
(optional PD-ING-002). The per-field scorers are built and unit-tested; they report
coverage 0 (never inflated) until field labels exist.

## Conclusion → the PD-ML-006 decision gate

Text metadata alone **cannot** safely auto-pass at high precision; its usable signal is
the **reason hint** and **queue prioritisation**, not auto-payment. The strong routing
signal needs **rule-output / OCR-confidence features**, which only exist when the
pipeline runs — i.e. they enter at **PD-ML-007**. Whether the heavy **Donut reader
(PD-ML-006)** is warranted should be re-decided against this baseline once PD-ML-001
(deterministic floor) + PD-ML-007 (rule-feature triage) are measured on the held-out
month. Keep this split **frozen** across experiments.

### Gate decision (2026-05-27): **PD-ML-006 OPEN**

- `triage_calibrated` passes 0% at the safe threshold → text routing cannot close the queue.
- R5 (OCR staff-ID misread) is not in the learned reason classes → model has no signal for
  extraction quality; 92/93 INVALIDs in the Aug-2025 run were R5 misreads.
- Extraction quality is confirmed as the bottleneck → **build the Donut reader**.

Next comparison point: re-run this eval with `--with-fields` once the vision split is
populated from the roster cache (requires running the pipeline with real files).
