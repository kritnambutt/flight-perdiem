# Run Pipeline Performance — Downloading + OCR Bottlenecks

**Date:** 2026-05-25
**Status:** Analysis (no code changed yet)
**Symptom:** A full run of ~137 claims (AUGUST 2025) takes **15–20 minutes**.
The two slow stages are `downloading` and `ocr`; `validating`/`aggregating`
are negligible.

```
11:36:41 INFO ingested 137 claims
11:36:41 INFO downloading rosters for 137 claims (cached files reused)
… (long gap)
```

~15–20 min / 137 claims ≈ **7–9 s per claim**, almost all of it in OCR on a
warm file cache (downloads are skipped when `data/cache` already has the file —
140 files are cached today). On a **cold** cache the download stage adds several
more minutes on top.

---

## How the pipeline runs today

The worker processes claims **strictly sequentially**, one stage at a time
(`worker/runner.py`):

- `downloading` — `fetch_rosters(claim)` per claim (`runner.py:122`), each calling
  `_resolve_ref` → `_download_file` per URL (`engine/drive.py:160`).
- `ocr` — `extract_roster(ref)` per claim in a `for` loop (`runner.py:142`).
- `validating` — pure CPU, fast.

One concurrent run at a time is a deliberate Pi-5 constraint, but **within a run
nothing is parallelised**, and each per-item step does more work than it needs.

---

## Bottlenecks (ranked by impact)

### B1 — Access token fetched via `gcloud` subprocess on *every* file  ⟶ download
`_download_file` calls `_get_access_token` for each download
(`engine/drive.py:61`), which spawns `gcloud auth print-access-token`
(`drive.py:44-53`, `timeout=15`). On a cold cache that is **137 subprocess
forks**, each ~0.5–1.5 s, all serial. The token is valid ~1 hour — it should be
fetched **once per run** and reused.

### B2 — Downloads are serial  ⟶ download
`fetch_rosters` resolves URLs in a list comprehension (`drive.py:160`) and the
worker calls it per claim in a dict comprehension (`runner.py:122`). Downloading
is **I/O-bound** (network round-trips) — the ideal case for bounded concurrency.
137 serial HTTPS GETs dominate the cold-cache time.

### B3 — Three Tesseract passes per image  ⟶ ocr (largest steady-state cost)
For each roster, OCR runs Tesseract **three times**:

1. `image_to_osd` for orientation — `auto_orient` (`ocr/preprocess.py:36`)
2. `image_to_string` for header/footer text — (`ocr/extract.py:315`)
3. `image_to_data` for the word grid — `_extract_grid` (`ocr/extract.py:251`)

Passes 2 and 3 analyse the **same page**; `image_to_data` already returns every
word + box, so the full text can be reconstructed from it and pass #2 dropped
entirely (~⅓ of OCR time).

### B4 — `fastNlMeansDenoising` on an upscaled image  ⟶ ocr
`preprocess` upscales to ≥2000 px wide then runs
`cv2.fastNlMeansDenoising(h=10, templateWindowSize=7, searchWindowSize=21)`
(`ocr/preprocess.py:60,91`). Non-local-means is the **slowest** OpenCV filter,
and it runs on the *enlarged* image — multiple seconds each, far worse on Pi-5
arm64. The rosters are machine-printed screenshots, where denoising buys little;
it should be **optional** (config flag) or replaced with a cheap median/bilateral
filter and a smaller `searchWindowSize`.

### B5 — OSD orientation pass is usually a no-op  ⟶ ocr
`auto_orient` runs a whole Tesseract OSD pass (B3 #1) to fix 90/180/270°
rotation. Most rosters are already upright (phone/desktop screenshots), so this
pass almost always returns `rotate=0`. It should be **off by default**, run only
as a fallback when extraction yields nothing.

### B6 — OCR is single-threaded; the box has spare cores  ⟶ ocr
The OCR loop is serial (`runner.py:142`) and each Tesseract call is
single-process. Tesseract is CPU-bound and releases nothing useful to threads,
but **multiple processes** scale near-linearly. Dev box reports 12 logical CPUs;
the Pi 5 has 4. A bounded `ProcessPoolExecutor` (≈3 workers on the Pi, leaving a
core for the OS/DB) with `OMP_THREAD_LIMIT=1` per worker is the single biggest
OCR win.

### B7 — Every PDF page is fully preprocessed + OCR'd  ⟶ ocr
For PDFs, all pages are rasterised at 150 DPI (`ocr/pdf.py:11`), then **each**
page is preprocessed and `image_to_string`'d (`extract.py:308-317`), even though
only page 0 is used for the grid (`extract.py:324`). Multi-page rosters pay N×
preprocessing for marginal text gain.

### B8 — No OCR-result cache (re-runs redo all OCR)  ⟶ re-runs / idempotency
The **file** cache avoids re-downloading (`drive.py:104`), but OCR re-extracts
from scratch on every run. Extraction is deterministic per file — caching the
`ExtractedRoster` keyed by `file_id` would make re-runs near-instant and directly
serves the N2 idempotency goal.

### B9 — No per-stage timing  ⟶ observability
Progress % is logged but not **wall-clock per stage / per item**, so the split
between download and OCR is inferred, not measured. Add timers before tuning.

---

## Recommended plan

Effort = rough size; Impact = expected wall-clock reduction.

| # | Change | Where | Effort | Impact |
|---|--------|-------|--------|--------|
| 1 | Fetch token **once per run**, pass into downloads; reuse a `requests.Session` | `drive.py`, `runner.py` | XS | High (cold cache) |
| 2 | Parallelise downloads with a bounded `ThreadPoolExecutor` (e.g. 8) | `runner.py` (or a `fetch_rosters_many` helper) | S | High (cold cache) |
| 3 | Drop `image_to_string`; rebuild full text from `image_to_data` words | `ocr/extract.py` | S | ~30% OCR |
| 4 | Make denoise optional / lighter (`ocr_denoise` flag, smaller window) | `preprocess.py`, `models.OcrConfig` | S | High per image |
| 5 | Make OSD auto-orient optional, fallback-only (`ocr_auto_orient` flag) | `preprocess.py`, `extract.py` | S | Medium |
| 6 | Parallelise OCR with a bounded `ProcessPoolExecutor` + `OMP_THREAD_LIMIT=1` | `runner.py` | M | ~3–4× on Pi |
| 7 | Cache `ExtractedRoster` by `file_id` (sidecar JSON or DB) | new `ocr/cache.py` + `runner.py` | M | Re-runs ~instant |
| 8 | OCR only the page(s) needed for PDFs | `extract.py` | S | Medium (PDF only) |
| 9 | Per-stage + per-item timing logs | `runner.py` | XS | Observability |

**Suggested order:** start with #9 (measure), then the quick wins #1, #3, #4, #5
(no concurrency, low risk), then the parallelism #2 + #6, and finally the
re-run cache #7.

### New config knobs (env-driven, per project standards — never hard-code)
- `DOWNLOAD_CONCURRENCY` (default 8) — download thread pool size.
- `OCR_CONCURRENCY` (default `min(4, cpu-1)`) — OCR process pool size.
- `OcrConfig.denoise: bool` (default `False`) and `denoise_search_window` (e.g. 9).
- `OcrConfig.auto_orient: bool` (default `False`).

Keep concurrency **bounded** and RAM-aware: upscale + denoise are memory-heavy,
so OCR parallelism on the Pi is capped by RAM as much as by cores — tune
`OCR_CONCURRENCY` down if the box swaps.

---

## Rough expected outcome

- **Cold cache:** download stage from ~minutes → <1 min (token-once + parallel).
- **Warm cache (steady state):** OCR from ~7–9 s/claim → ~2–3 s/claim with
  #3+#4+#5, then divided by the process-pool width (#6). A 137-claim run should
  land in roughly **3–5 minutes**.
- **Re-runs of the same month:** near-instant after #7 (both files and OCR cached).

These are estimates — land #9 first so the before/after is measured, not guessed.

---

## Key takeaway

The pipeline is correct but does **redundant per-item work** (token subprocess
per file, three Tesseract passes, heavy denoise, OSD on upright images) and runs
it **serially** on a multi-core box. The biggest, safest wins are: fetch the
token once, delete one OCR pass, make denoise/OSD opt-in, and run OCR across a
small bounded process pool — all consistent with the project's "bounded
concurrency, cache by file id, engine stays pure" standards (the engine functions
stay pure; concurrency and caching live in the worker).
