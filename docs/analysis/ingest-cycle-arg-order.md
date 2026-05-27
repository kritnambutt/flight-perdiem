# Pipeline Fails Immediately — `ingest_cycle` Argument Order

**Date:** 2026-05-25  
**Status:** Fixed  
**Symptom:** With the worker running (`make worker-dev`), every run fails at the `parsing`
stage. Two different errors appear depending on the run:

- `openpyxl does not support  file format … Supported formats are: .xlsx,.xlsm,.xltx,.xltm`
- `FileNotFoundError: …/late_submission.xlsx` raised from inside `read_posting_base`
- Warning: `Posting Base: no sheet found for '…/posting_base.xlsx' in …/late_submission.xlsx`

---

## Root Cause

`ingest_cycle` takes **`cycle_month` first**, then the optional paths:

```python
# engine/ingest.py
def ingest_cycle(cycle_month: str, pb_path: str | None = None, late_path: str | None = None)
```

The worker called it with the arguments in the **wrong positional order**:

```python
# worker/runner.py (before)
ingest_cycle(str(posting_path), str(late_path), run.cycle_month)
```

So the parameters bound like this:

| Parameter | Got (wrong) | Should be |
|-----------|-------------|-----------|
| `cycle_month` | `…/posting_base.xlsx` (a path) | `"AUGUST 2025"` |
| `pb_path` | `…/late_submission.xlsx` | `…/posting_base.xlsx` |
| `late_path` | `"AUGUST 2025"` | `…/late_submission.xlsx` |

This single mistake explains every symptom:

1. **"no sheet found for `…/posting_base.xlsx` in `…/late_submission.xlsx`"** —
   `read_posting_base` opened the *late* workbook (`pb_path`) and searched for a worksheet
   whose name was the *posting-base path string* (`cycle_month`). No such sheet → warning,
   returns `[]`.
2. **"openpyxl does not support  file format"** (empty format) —
   `read_late_submission` then did `load_workbook("AUGUST 2025")`. That string has no
   `.xlsx` extension, so openpyxl rejects it (the blank in "support  file" is the empty
   extension).
3. **`FileNotFoundError: …/late_submission.xlsx` from `read_posting_base`** (the other run) —
   for a run whose uploads were never saved, `read_posting_base` tried to open
   `pb_path` (= the late path) and the file didn't exist.

The uploaded files themselves were fine — `file` reported both as valid
"Microsoft Excel 2007+". The bug was purely the call site.

---

## Fix

Call `ingest_cycle` with **keyword arguments** so position can't be confused again:

```python
# worker/runner.py (after)
claims = ingest_cycle(
    cycle_month=run.cycle_month,
    pb_path=str(posting_path),
    late_path=str(late_path),
)
```

---

## Stale Runs From Before the Fix

The two pre-existing `AUGUST 2025` runs are now `FAILED` and won't be retried (the worker
only picks up `PENDING`):

| Run | State on disk | Outcome |
|-----|---------------|---------|
| `442da394…` | **No upload dir** (created during the earlier `/data` read-only 500; files never saved) | Would still FileNotFound — abandon it |
| `98f437e8…` | Both `.xlsx` present and valid | Failed only due to the arg-order bug |

**To verify the fix, submit a fresh run** through the UI. A clean submit now saves valid
files to `data/uploads/<run_id>/` and the worker should advance through the stages.

---

## Key Takeaway

`ingest_cycle(cycle_month, pb_path, late_path)` leads with `cycle_month`, not the paths
(the paths are optional and default to env fixtures). Always call it with keyword
arguments. This was the only call site in the codebase.
