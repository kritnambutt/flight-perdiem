# Pipeline Fails at `downloading` — `fetch_rosters` Misused by Worker

**Date:** 2026-05-25  
**Status:** Fixed  
**Symptom:** Ingest now succeeds ("ingested 137 claims") but the run fails at the
`downloading` stage:

```
ERROR Run … failed: 'str' object has no attribute 'mkdir'
  File "…/engine/drive.py", line 158, in fetch_rosters
    resolved_cache.mkdir(parents=True, exist_ok=True)
AttributeError: 'str' object has no attribute 'mkdir'
```

---

## Root Cause

Two bugs, both at the worker call site (`runner.py`), plus one latent fragility in the
engine.

### 1. `cache_dir` passed as `str`, treated as `Path`

`drive.py` did:

```python
resolved_cache = cache_dir or Path(settings.roster_cache_dir)
```

The worker passed `cache_dir=settings.roster_cache_dir`, which is a **`str`**. Because the
str is truthy, `resolved_cache` stayed a `str`, and `str` has no `.mkdir()`.

The engine's type hint is `cache_dir: Path | None`, and its tests only ever passed pytest's
`tmp_path` (a `Path`) — so the `str` path was never exercised.

### 2. `fetch_rosters` is per-claim, but the worker called it batch-style

The engine contract (confirmed by `tests/engine/test_drive.py`) is **per claim**:

```python
def fetch_rosters(claim: Claim, cache_dir=None, account=None) -> list[RosterRef]
```

The worker instead passed the **whole list** and treated the result as a **dict**:

```python
roster_map = fetch_rosters(claims, cache_dir=settings.roster_cache_dir)  # wrong
...
refs = roster_map.get(i, [])   # expects dict[int, list[RosterRef]]
```

Even after fixing bug #1, the next line (`for url in claim.roster_links`) would have failed
because `claim` was actually a `list`.

---

## Fix

**Engine (`drive.py`) — coerce to `Path` defensively** (closes the `str`/`Path` gap for any
caller):

```python
resolved_cache = Path(cache_dir) if cache_dir is not None else Path(settings.roster_cache_dir)
```

**Worker (`runner.py`) — loop per claim and build the index→refs map itself**, passing a
`Path`:

```python
from perdiem.engine.drive import fetch_rosters
cache_path = Path(settings.roster_cache_dir)
roster_map: dict[int, list[RosterRef]] = {
    i: fetch_rosters(claim, cache_dir=cache_path)
    for i, claim in enumerate(claims)
}
```

`tests/engine/test_drive.py` (18 tests) still passes — the engine contract is unchanged.

---

## Also Fixed: `ocr` and `validating` Stages (same class of bug)

A proactive pass over the next two stages found the same worker↔engine mismatch, fixed in the
same change:

**`ocr` — `extract_roster` misused.** `extract_roster(roster: RosterRef) -> ExtractedRoster`
loads the image and runs `preprocess` *internally*, and always returns an `ExtractedRoster`
(an empty `_empty_result` when the file is missing). The worker had pre-called
`preprocess(local_path)` (passing a path where an `np.ndarray` was expected) and fed the
result into `extract_roster` (which wanted a `RosterRef`). Both calls were wrong; the
`preprocess` failure was hidden by the stage's try/except, so OCR silently produced nothing.

```python
# before:  img = preprocess(ok_refs[0].local_path); extracted_map[i] = extract_roster(img)
# after:   extracted_map[i] = extract_roster(ok_refs[0])
```

**`validating` — `None` passed for required args.** `validate_claim(claim, roster, red, cfg)`
dereferences `red.claimed_days` (rules.py:100) and `roster.start_date` (rules.py:105), but the
worker passed `extracted` (None when a claim has no roster) and `red_ann = None` (always). Fixed
by always supplying real objects:

```python
empty_extracted = extract_roster(empty_ref)          # engine's _empty_result, reused
empty_red = RedAnnotation(claimed_days=set(), confidence=0.0, bbox=None)
...
extracted = extracted_map.get(i) or empty_extracted
verdicts = validate_claim(claim, extracted, empty_red, cfg)
```

### Known limitation (not a crash — a feature gap)

Red-box detection (`detect_red_annotation`) is **not yet wired into the worker**. It needs the
original colour image plus grid geometry, which `extract_roster` computes internally but does
not expose. Until that's plumbed through, `red` is always an empty `RedAnnotation`, so
`validate_claim` falls back to the **form's** `claimed_days` rather than the days the crew
red-boxed on the roster. This is per `detect_red_annotation`'s own contract ("no mark found →
caller uses the form's claimed-day list") and is correct as a fallback, but the red-box feature
(R-rules) should be completed separately.

Engine guard: `drive.fetch_rosters` now coerces `cache_dir` to `Path`, closing the
`str`/`Path` gap for any caller (the type hint was already `Path | None`).

---

## Key Takeaway

The engine is the **pure, per-item primitive**; orchestration (looping over claims, building
maps) belongs in the worker. This was the second of **three** worker↔engine call-site
mismatches found in the pipeline (after [ingest-cycle-arg-order](./ingest-cycle-arg-order.md)):
`downloading`, `ocr`, and `validating` were all written against assumed signatures that differed
from the engine's actual contract — a sign the worker's later stages had never been run
end-to-end. All 263 non-integration tests pass after the fixes.
