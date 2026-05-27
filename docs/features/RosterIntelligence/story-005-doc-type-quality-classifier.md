| Property     | Value                                                          |
| ------------ | -------------------------------------------------------------- |
| Story ID     | PD-ML-005                                                      |
| Title        | Roster doc-type / quality classifier                           |
| Epic         | EP-ML — Roster Intelligence                                    |
| Dependencies | PD-ML-002 (dataset), PD-ML-003 (eval)                          |
| Story Type   | Feature                                                        |
| Status       | 🚧 In Progress                                               |
| Source       | REQUIREMENTS.md → §6.2 (F6), §7 (N1); example-files.md (incorrect/) |

## 🗂 Epic Overview — EP-ML

See [overview.md](./overview.md). A small image classifier that answers a cheap, high-value
question **before** any field extraction: *is this attachment actually a readable crew
schedule report?* Wrong documents and unreadable photos get caught early and routed to
review instead of producing garbage fields and confusing downstream rules.

## 📝 Feature Overview — PD-ML-005

### User Story

```gherkin
As an admin
I want obviously-wrong or unreadable roster attachments flagged up front
So that the pipeline doesn't waste OCR on them or, worse, fabricate fields that misfire the rules
```

### Pre-conditions

- The dataset (PD-ML-002) and eval harness (PD-ML-003) exist.
- Seed labels: `docs/example-files/roster-attached-files/correct/` (valid) vs `incorrect/`
  (invalid-format) + form rows whose admin reason was `DOC_INCOMPLETE`.

### Scope

#### Included

- A binary/3-class classifier on the roster image: `VALID_ROSTER | NOT_A_ROSTER |
  UNREADABLE` (the last two both route to `NEEDS_REVIEW`).
- **Augmentation** to mimic real quality variance: downscale/upscale, JPEG recompression,
  rotation, glare/perspective, screenshot artefacts.
- Runs **before** field extraction; `NOT_A_ROSTER`/`UNREADABLE` short-circuits to review.

#### Excluded

- Reading fields (PD-ML-006). Red-box detection (optional; out of epic per overview).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Catches the known-bad fixtures:** the `incorrect/ … invalid formatted` images classify
   as `NOT_A_ROSTER`/`UNREADABLE`; the `correct/` set classifies as `VALID_ROSTER`.
2. **Early routing (N1):** a non-valid classification yields `NEEDS_REVIEW` with a clear
   reason; the pipeline does **not** emit fabricated fields for it.
3. **Threshold-tuned:** decision threshold chosen on the val split to favour recall of
   bad documents (a missed bad doc is worse than an extra review).
4. **Reported via PD-ML-003:** ROC-AUC + confusion matrix on the held-out month.

### Validation Rules

- Confidence below the configured band → route to review (abstain), never force a class.

### Error Scenarios

- Multi-page PDF → classify the page most likely to be the report; if none qualifies →
  `UNREADABLE`.
- Corrupt/zero-byte image → `UNREADABLE` (no crash).

## 🧩 Technical Documentation

### Inference interface

```python
@dataclass
class DocTypeResult:
    label: Literal["VALID_ROSTER","NOT_A_ROSTER","UNREADABLE"]
    confidence: float

def classify_doc(image_path: str, model_path: str, cfg: DocTypeConfig) -> DocTypeResult: ...
```

### Model

**Implemented as:** numpy softmax logistic regression over 11 hand-crafted image features
(same zero-dep, JSON-serialisable pattern as PD-ML-004 triage). No ONNX or GPU needed;
Pi-friendly. Original plan noted CNN / MobileNet / ONNX int8 as one option; the
lightweight feature approach was chosen for consistency with the rest of the stack.

Features (`NUMERIC_FEATURES`): `log_width`, `log_height`, `aspect_ratio`,
`mean_brightness`, `brightness_std`, `edge_density`, `blue_band_score`, `dark_ratio`,
`color_std`, `row_variance_mean`, `col_variance_mean`.

Train off-Pi via `scripts/train_doctype.py` (no dataset-build step — reads fixture images
directly). Artifact: `data/ml/models/doctype.json`.

### Required Configuration

- `DOCTYPE_ENABLED` (default False until validated), `DOCTYPE_MODEL_PATH`,
  `DOCTYPE_MIN_CONF`.

### Security Requirements

- Roster images are PII — training data + model stay local; no cloud inference.

## 🔨 Implementation Plan

1. ✅ **DONE** Assemble labels (correct/incorrect fixtures) + augmentation pipeline.
   - `backend/ml/doctype/augment.py`: JPEG recompress, down/upscale, rotate, brightness, noise + `make_unreadable_variants()` for synthetic UNREADABLE class.
   - `backend/ml/doctype/train.py`: `load_fixture_images()` with automatic label assignment (`correct/` → `VALID_ROSTER`; `incorrect/*invalid formatted*` → `NOT_A_ROSTER`; other `incorrect/` → `VALID_ROSTER`). UNREADABLE examples synthesised via extreme augmentation.

2. ✅ **DONE** Train classifier off-Pi; serialize to JSON artifact.
   - Implemented as numpy softmax logreg (not ONNX — see Model section above).
   - `scripts/train_doctype.py` reads fixture images directly, no dataset-build step needed.
   - `make ml-train-doctype` shortcut added to Makefile.
   - Achieves ~83% val accuracy on 9 real fixture images with default augmentation.

3. ✅ **DONE** Pure `classify_doc()` scorer with lazy imports.
   - `backend/perdiem/engine/ocr/doctype.py`: `DocTypeConfig`, `DocTypeResult`, `extract_image_features()`, `classify_doc()`, `safe_classify_doc()`.
   - Corrupt/zero-byte/unloadable files caught before model runs → `UNREADABLE` (no crash).
   - Multi-page PDF: first page rasterised via existing `pdf.py`.
   - `safe_classify_doc()` returns `None` when disabled or model missing → pipeline falls back unchanged.

4. ✅ **DONE** Wired as pre-extraction gate in worker + `extract_roster()`.
   - `backend/perdiem/worker/runner.py`: constructs `DocTypeConfig` from settings and passes to `extract_roster()`.
   - `backend/perdiem/engine/ocr/extract.py`: `extract_roster()` accepts optional `doctype_cfg`; non-VALID images return `_empty_result(f"doc-type classifier: {label} (conf=…)")` immediately, skipping Tesseract.
   - `backend/perdiem/config.py` + `.env.example`: `DOCTYPE_ENABLED=false`, `DOCTYPE_MODEL_PATH`, `DOCTYPE_MIN_CONF=0.70`.

5. 📝 **TODO** Score via PD-ML-003; report ROC-AUC + confusion matrix on held-out month.
   - Requires extending `eval_ml.py` / `ml/eval/` to accept a doctype backend and emit image-level metrics.
   - Blocked until more labelled roster images are available in the roster cache (vision split).

## 🏗 Structure

```
backend/ml/doctype/              # training (off-Pi)
├── __init__.py
├── augment.py                   # augmentation: JPEG, scale, rotate, brightness, noise
└── train.py                     # fixture loader, feature matrix, softmax training, JSON artifact
backend/perdiem/engine/ocr/doctype.py   # pure inference: DocTypeConfig, DocTypeResult,
                                         # extract_image_features(), classify_doc(), safe_classify_doc()
backend/perdiem/engine/ocr/extract.py   # modified: extract_roster() accepts doctype_cfg gate
backend/perdiem/worker/runner.py        # modified: constructs DocTypeConfig, passes to extract_roster()
backend/perdiem/config.py               # modified: DOCTYPE_ENABLED, DOCTYPE_MODEL_PATH, DOCTYPE_MIN_CONF
backend/tests/ml/test_doctype.py        # 19 tests (16 pass, 3 skip if fixture images absent)
scripts/train_doctype.py                # CLI training script
.env.example                            # modified: DOCTYPE_* env vars documented
```

## 📌 Notes / Open Questions

- **Model approach deviation:** implemented as numpy softmax logreg over hand-crafted image
  features instead of CNN/ONNX. Rationale: consistent with PD-ML-004 triage, zero extra
  deps, Pi-friendly. Can be upgraded to ONNX/MobileNet later without changing the
  `classify_doc()` interface (swap the artifact format and scorer internals only).

- **Ships disabled by default** (`DOCTYPE_ENABLED=false`). Enable after running
  `make ml-train-doctype` and verifying accuracy on your roster cache. Set in `.env`.

- **PD-ML-003 integration (task 5) is the remaining blocker** for the "Reported via
  PD-ML-003" acceptance criterion. Needs image-level eval metrics in `ml/eval/`.

- **UNREADABLE class is mostly synthetic** — generated by extreme augmentation of
  `VALID_ROSTER` images (severe downscale, near-black, near-white, extreme JPEG). Real
  corrupt fixtures should be added to `incorrect/` as they are encountered to improve
  calibration.

- If the Donut reader (PD-ML-006) ships, this can also act as its **abstention front-end**
  (don't run the heavy reader on junk).
