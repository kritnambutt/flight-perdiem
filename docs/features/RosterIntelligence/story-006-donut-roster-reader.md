| Property     | Value                                                          |
| ------------ | -------------------------------------------------------------- |
| Story ID     | PD-ML-006                                                      |
| Title        | Donut roster reader (WS-1) — *decision-gated*                  |
| Epic         | EP-ML — Roster Intelligence                                    |
| Dependencies | PD-ML-002 (dataset), PD-ML-003 (baseline — **gate**), PD-ML-005 (front-end) |
| Story Type   | Feature                                                        |
| Status       | 🚧 In Progress — tasks 1/2/3/4/5 done; 6 needs Pi benchmark + eval run |
| Source       | REQUIREMENTS.md → §6.2 (F4, F6), §7 (N1)                       |

## 🗂 Epic Overview — EP-ML

See [overview.md](./overview.md). The heaviest story: replace the brittle Tesseract-regex
extractor with an **OCR-free image→JSON** model (Donut) that reads variable-quality rosters
directly into the `ExtractedRoster` schema. **Build only if the baseline (PD-ML-003) shows
that the deterministic floor (PD-ML-001) + triage (PD-ML-004) don't clear the accuracy bar.**

## 📝 Feature Overview — PD-ML-006

### User Story

```gherkin
As the per diem validation system
I want to read a roster's staff ID, name, dates, generated date and flight grid even from small/blurry/skewed images
So that R5 stops false-rejecting on misread IDs and R1/R4 stop flagging "no flights" when the grid was simply unreadable
```

### Pre-conditions

- **Decision gate passed:** PD-ML-003 baseline shows extraction is still the bottleneck after
  PD-ML-001 + PD-ML-004.
- A vision dataset (PD-ML-002) + synthetic generator (below) supply enough labelled rosters.

### Scope

#### Included

- Fine-tune **Donut** (`naver-clova-ix/donut`) to emit the `ExtractedRoster` JSON
  (staff_id, name, start/end date, generated_at, grid: day→legs) with a per-field/overall
  **confidence** signal.
- A **synthetic roster generator** (render the templated crew-schedule report with randomised
  values) + **degradation augmentation** (downscale, JPEG, perspective/glare, rotation,
  screenshot artefacts) to overcome the scarce-image problem.
- **ONNX export + int8 quantisation**; CPU inference sized for the Pi batch worker.
- A **hybrid fallback**: when Donut's confidence is low, fall back to the Tesseract extractor
  (never a silent guess — N1).

#### Excluded

- The plumbing that lets the worker *select* this backend — that's PD-ML-007.
- Cloud/GPU inference in production (PII + zero-cost). Training is off-Pi.

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Schema-faithful output:** Donut emits valid `ExtractedRoster` JSON; malformed output is
   caught and treated as low-confidence → fallback/review.
2. **Beats baseline (the whole point):** on the held-out month (PD-ML-003), staff_id
   exact-match and grid leg recall improve materially over the Tesseract baseline; R5 false
   INVALIDs and R1 "no flights" reviews drop.
3. **Per-field confidence + abstention:** low overall confidence → Tesseract fallback, then
   `NEEDS_REVIEW` if still low. Never emit an unflagged guess.
4. **Pi-viable:** quantised model runs within the batch OCR budget (seconds/page acceptable;
   integrated with the OCR cache so re-runs are near-instant — N2).
5. **Deterministic:** same image → same JSON (fixed decoding, no sampling).

### Validation Rules

- Output dates/IDs pass the same sanity checks the regex path uses (7-digit ID, parseable
  dates) before being trusted; failures lower confidence.

### Error Scenarios

- Donut OOM / load failure on Pi → fall back to Tesseract backend; logged, run continues.
- Non-roster image (caught by PD-ML-005) → reader not invoked.

## 🧩 Technical Documentation

### Output contract (identical to the existing engine model)

```python
# Donut decodes to JSON that maps 1:1 onto:
@dataclass
class ExtractedRoster:
    staff_id: Field[str]; name: Field[str]
    start_date: Field[date]; end_date: Field[date]
    generated_at: Field[datetime]
    grid: dict[int, list[Leg]]
    needs_review: list[str]
```

### Inference interface (the backend PD-ML-007 plugs in)

```python
def extract_roster_donut(roster: RosterRef, cfg: OcrConfig, model_path: str) -> ExtractedRoster: ...
# lazy-imports torch/onnxruntime; returns the SAME type as extract_roster()
```

### Required Configuration

- `DONUT_MODEL_PATH`, `DONUT_CONF_FALLBACK` (below → Tesseract), `DONUT_MAX_PAGES`.

### Security Requirements

- Training images + weights are PII-derived → stay local. Synthetic data carries no real PII
  and is the safe portion to share/train widely.

## 🔨 Implementation Plan

1. ✅ **DONE** *(Gate)* PD-ML-003 baseline run on `2026-05` test split confirms extraction is the bottleneck.
   - `triage_calibrated` at safe threshold (0.85): 0% auto-pass → text routing alone cannot close the queue.
   - R5 absent from learned reason classes → model has no signal for OCR quality; 92/93 INVALIDs are OCR misreads.
   - Gate: **PASSED** — build the Donut reader.

2. ✅ **DONE** Synthetic roster generator + degradation augmentation (`backend/ml/roster_gen/`).
   - `schema.py`: `SyntheticRosterData`, `SyntheticLeg`, `to_label_json()` (keeps image+label in sync).
   - `generate.py`: `generate_roster()` / `generate_batch()` — randomised staff IDs, Thai-English names, DMK↔HKT out-and-back pairs, generated_at always after end_date (R4).
   - `renderer.py`: PIL-based `render_roster()` → BGR ndarray. AirAsia-layout: blue header band, date bar, 7-column weekly grid, footer.
   - Augmentation for training: reuse `ml/doctype/augment.py` (JPEG, scale, rotate, brightness, noise).

3. ✅ **DONE** Donut fine-tuning script written (GPU required to run).
   - `backend/ml/donut/train.py`: `DonutTrainConfig`, `RosterDataset` (PyTorch), `train()`.
     Generates synthetic images on-the-fly in a temp dir, mixes in real vision rows when present,
     fine-tunes `naver-clova-ix/donut-base` with HuggingFace `Seq2SeqTrainer`.
   - `scripts/train_donut.py`: CLI entry point with `--synthetic-n`, `--aug-per-image`, `--epochs`,
     `--vision-jsonl`, `--out`; fallback message if `transformers` not installed.
   - `make ml-train-donut` target added to Makefile.
   - **To actually run:** install `pip install transformers torch accelerate` on a GPU machine,
     then `make ml-train-donut` (or run on Google Colab).
   - Real vision split `data/ml/datasets/2026-05/vision.jsonl` still has 0 rows — populate
     roster cache first for real-data mixing.

4. ✅ **DONE** ONNX export + int8 quantise; benchmark on Pi-class CPU.
   - `scripts/export_donut_onnx.py`: exports encoder + decoder as separate ONNX graphs
     (dynamic seq-len axes); int8 `quantize_dynamic` via onnxruntime; saves `processor/`.
     Target < 500 MB combined. `make ml-export-donut` entry point.
   - `scripts/bench_donut.py`: measures encode + decode latency (averaged over N runs),
     token/s, Pi verdict. `make ml-bench-donut` entry point.
   - Fixed `_run_onnx` in `ml_extract.py` to pass the full accumulated token sequence
     at each decode step (previous code passed only the last token — broke self-attention).
   - **To run on Colab** (after training): `python scripts/export_donut_onnx.py --model data/ml/models/donut --out data/ml/models/donut-onnx`
   - **Pi benchmark**: copy `*_q8.onnx` + `processor/` to the Pi, then `make ml-bench-donut ARGS="--onnx-dir <path> --image <roster> --n 1"`.

5. ✅ **DONE** `extract_roster_donut()` with JSON-validation + confidence + Tesseract fallback.
   - `backend/perdiem/engine/ocr/ml_extract.py`: `DonutConfig`, `_parse_donut_output()` (field validation + confidence score), `extract_roster_donut()` (Donut → fallback to Tesseract if conf < threshold), `safe_extract_donut()` (returns None when disabled/missing).
   - `backend/perdiem/engine/ocr/base.py`: `DonutExtractor` class implementing `Extractor` protocol.
   - `backend/perdiem/config.py` + `.env.example`: `DONUT_ENABLED`, `DONUT_MODEL_PATH`, `DONUT_CONF_FALLBACK`, `DONUT_MAX_PAGES`.
   - Dispatches: HuggingFace dir (torch) or `*.onnx` dir (onnxruntime) based on what's at `model_path`.

6. 📝 **TODO** Score via PD-ML-003 against baseline; record deltas.
   - Requires task 3 + 4 (trained + quantised model) first.
   - Run `make ml-eval ARGS="--dataset-version 2026-05 --with-fields"` once vision rows are populated.

## 🏗 Structure

```
backend/ml/roster_gen/                     # synthetic generator (DONE)
├── __init__.py
├── schema.py                              # SyntheticRosterData, SyntheticLeg, to_label_json()
├── generate.py                            # generate_roster(), generate_batch()
└── renderer.py                            # render_roster() → BGR ndarray (PIL-based)
backend/ml/donut/                          # fine-tune + ONNX export (DONE)
backend/perdiem/engine/ocr/ml_extract.py   # pure inference: DonutConfig, extract_roster_donut(),
                                            # safe_extract_donut(), _parse_donut_output() (DONE)
backend/perdiem/engine/ocr/base.py         # modified: DonutExtractor class added (DONE)
backend/perdiem/config.py                  # modified: DONUT_* settings (DONE)
backend/tests/ml/test_roster_gen.py        # 17 tests (DONE)
backend/tests/ml/test_ml_extract.py        # 21 tests (DONE)
data/ml/models/donut/                      # trained model artifact (gitignored)
data/ml/models/donut-onnx/                 # ONNX + int8 export (gitignored, produced by export_donut_onnx.py)
.env.example                               # modified: DONUT_* env vars (DONE)
```

## 📌 Notes / Open Questions

- **Alternative if Donut is too heavy on Pi:** LayoutLMv3 token-classification *keeping*
  Tesseract for OCR, or TrOCR as a targeted recogniser for just the hard regions. Decide
  during step 3–4 from the Pi benchmark.
- Synthetic data is the lever for the scarce-image problem — invest there before more labelling.
- Inference plumbing (backend selection, hybrid policy) is **PD-ML-007**, kept separate so
  this story is purely "the model + its contract".
