| Property     | Value                                                          |
| ------------ | -------------------------------------------------------------- |
| Story ID     | PD-ML-007                                                      |
| Title        | Pluggable ML extractor backend integration                     |
| Epic         | EP-ML — Roster Intelligence                                    |
| Dependencies | PD-ML-006 (Donut reader) and/or PD-ML-004 (triage); PD-ML-003 (eval) |
| Story Type   | Infrastructure                                                 |
| Status       | 🚧 In Progress — tasks 1/2/3/4/5 done; task 6 (PD-ML-003 compare) pending trained model |
| Source       | REQUIREMENTS.md → §6.2 (F4, F6), §6.5 (config), §7 (N1, N2); backend-standards.md (engine purity) |

## 🗂 Epic Overview — EP-ML

See [overview.md](./overview.md). The integration story: let the worker **select** an
extraction backend (Tesseract / Donut / hybrid) and optionally apply the triage model — all
behind the **existing `ExtractedRoster` interface**, so the rules, pairing, dedup, and
reporting code are untouched and the engine stays pure.

## 📝 Feature Overview — PD-ML-007

### User Story

```gherkin
As the operator
I want to switch between the Tesseract and ML extractors by config, with a safe hybrid fallback
So that I can roll the model out gradually, compare against baseline, and never regress on a bad image — without touching the rules engine
```

### Pre-conditions

- At least one ML component is validated (Donut PD-ML-006 and/or triage PD-ML-004).
- The eval harness (PD-ML-003) can compare backends on the held-out month.

### Scope

#### Included

- An **`Extractor` protocol** returning `ExtractedRoster`; implementations: `tesseract`
  (today), `donut` (PD-ML-006), `hybrid` (Donut with Tesseract fallback on low confidence).
- **Config-selectable backend** (`OCR_BACKEND`) read in the worker; the **engine functions
  stay pure** and heavy deps are **lazy-imported** in the ML backend only.
- **OCR-result cache by `file_id`** (serves N2 idempotency; re-runs near-instant) shared by
  all backends.
- Optional **triage routing** (PD-ML-004) applied in the worker as an advisory layer on top
  of rule verdicts.
- The persisted `extracted` (PD-ML-001) records **which backend** produced the fields.

#### Excluded

- Training any model (earlier stories). Frontend changes beyond showing the backend/triage
  hint in the existing Exceptions panel.

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Interface parity (N1):** every backend returns `ExtractedRoster` with per-field
   `Field(value, confidence)`; the rules/identity/pairing code is unchanged and unaware of
   the backend.
2. **Config switch:** `OCR_BACKEND=tesseract|donut|hybrid` selects the extractor at run
   start; invalid value → clear error, default `tesseract`.
3. **Hybrid fallback:** `hybrid` runs the ML reader, and on low overall confidence falls back
   to Tesseract; if still low → `NEEDS_REVIEW`. The fallback path is logged and counted.
4. **Engine purity preserved:** `import perdiem.engine` pulls in **no** torch/onnx; engine
   unit tests run with ML deps absent (lazy import inside `ocr/ml_extract.py`).
5. **Idempotent caching (N2):** the OCR result is cached by `file_id` + backend + model
   version; re-running a month re-uses it; changing the model version invalidates it.
6. **Comparable:** PD-ML-003 can score any backend by name; switching backends produces a
   recorded metrics delta, not a silent change.

### Validation Rules

- Backend, model paths, thresholds, concurrency all come from config (§6.5) — never hard-coded.
- Triage routing is **advisory**: an `AUTO_REJECT`/`AUTO_PASS` still carries the rule-based
  verdict + reason; triage only sets the review queue / hint.

### Error Scenarios

- ML model file missing or fails to load → automatic fall back to `tesseract`, logged once,
  run continues (no crash).
- Cache corruption for a `file_id` → recompute, overwrite, warn.

## 🧩 Technical Documentation

### Extractor protocol (shared with the eval harness PD-ML-003)

```python
class Extractor(Protocol):
    name: str
    def extract(self, roster: RosterRef, cfg: OcrConfig) -> ExtractedRoster: ...

def get_extractor(backend: str, cfg: AppConfig) -> Extractor:
    # "tesseract" -> existing extract_roster
    # "donut"     -> extract_roster_donut (lazy import)
    # "hybrid"    -> donut + tesseract fallback policy
```

### OCR cache key

```
cache_key = sha1(file_id + backend + model_version + ocr_cfg_hash)
# stored as a sidecar JSON or a DB row; value = serialised ExtractedRoster
```

### Required Configuration

| Setting | Default | Purpose |
|---|---|---|
| `OCR_BACKEND` | `tesseract` | extractor selection |
| `DONUT_MODEL_PATH`, `DONUT_CONF_FALLBACK` | — | ML reader + hybrid threshold |
| `TRIAGE_ENABLED`, `TRIAGE_MODEL_PATH` | False / — | advisory routing |
| `OCR_CACHE_DIR` | `data/ml/ocr_cache` | result cache (N2) |

### Security Requirements

- Models + cache are PII-derived → local only, gitignored. Auth-gating of roster previews
  and `extracted` is unchanged (inherited from existing web layer).

## 🔨 Implementation Plan

1. ✅ **DONE** Define `Extractor` protocol + `get_extractor()` factory.
   - `Extractor` protocol in `backend/perdiem/engine/ocr/base.py` (from PD-ML-003).
   - `get_extractor(backend, cfg)` in `backend/perdiem/worker/extractor.py`; selects `TesseractExtractor`, `DonutExtractor`, or hybrid; unknown value warns + falls back to Tesseract.

2. ✅ **DONE** Wrap `extract_roster` as the `tesseract` backend.
   - `TesseractExtractor` in `base.py`; `DonutExtractor` added in PD-ML-006/this story.

3. ✅ **DONE** Wire `donut`/`hybrid` backends with the fallback policy.
   - `donut` backend: `DonutConfig.conf_fallback=0.0` → pure ML output; low-confidence → `NEEDS_REVIEW` but no automatic Tesseract re-run.
   - `hybrid` backend: `conf_fallback=DONUT_CONF_FALLBACK` → Donut + Tesseract safety net; recommended for initial roll-out.
   - `model_version_for(extractor)` derives cache key from model mtime.

4. ✅ **DONE** OCR-result cache keyed by `(file_id, backend, model_version)`.
   - `backend/perdiem/engine/ocr/cache.py`: `load_cached()` / `store_cached()` / `to_dict()` / `from_dict()` — full `ExtractedRoster` JSON serialisation.
   - Cache miss or corrupt entry → silent recompute. Empty `file_id` → not cached.
   - `OCR_CACHE_DIR` config (default `data/ml/ocr_cache`, gitignored).

5. ✅ **DONE** Record producing backend in `extracted`; backend selection wired in worker.
   - `runner.py`: constructs `_extractor` via `get_extractor(settings.ocr_backend, settings)`, checks cache before OCR, stores result in cache after OCR.
   - `_serialise_extracted()` now includes `"backend"` key (auditable in Exceptions panel, N1).
   - `OCR_BACKEND` config + `.env.example` documented.

6. 📝 **TODO** Compare backends via PD-ML-003; record deltas.
   - Run `make ml-eval ARGS="--dataset-version 2026-05 --with-fields"` once the Donut model is trained (PD-ML-006 tasks 3–4) and the vision split is populated.
   - Results to be recorded in `docs/analysis/ml-baseline.md`.

## 🏗 Structure

```
backend/perdiem/worker/extractor.py     # get_extractor() factory + model_version_for() (DONE)
backend/perdiem/engine/ocr/ml_extract.py# pure Donut inference (lazy import) — from PD-ML-006 (DONE)
backend/perdiem/engine/ocr/cache.py     # OCR-result cache: load/store/serialise (DONE)
backend/perdiem/engine/ocr/base.py      # modified: DonutExtractor added (DONE)
backend/perdiem/config.py               # modified: OCR_BACKEND, OCR_CACHE_DIR (DONE)
backend/perdiem/worker/runner.py        # modified: factory + cache + backend tag (DONE)
backend/tests/ml/test_backend_switch.py # 22 tests: factory, cache, engine purity (DONE)
.env.example                            # modified: OCR_BACKEND, OCR_CACHE_DIR (DONE)
```

## 📌 Notes / Open Questions

- Roll out as `hybrid` first (ML with safety net) before trusting `donut` alone.
- The **worker** owns backend selection + caching (side effects); the **engine** only owns
  pure inference functions — consistent with `backend-standards.md` layering.
- If PD-ML-006 is deferred at its gate, this story still delivers value: the cache (N2) +
  triage routing + the protocol that makes the baseline comparisons clean.
