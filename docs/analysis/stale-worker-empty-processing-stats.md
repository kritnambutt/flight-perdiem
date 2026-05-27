# Analysis — "Processing time / PDF / images show nothing" after re-running the pipeline

**Date:** 2026-05-25
**Run investigated:** `AUGUST 2025` (status `DONE`)
**Screenshot:** Results page — header reads
`108 crew · 158 submission rows · 200 claimed days`, then
`— processing time · 0 PDF · 0 images`.

## Symptom

After adding the **processing time** and **PDF/image counts** to the Results page,
the user re-ran the pipeline expecting the new stats to appear. Instead:

- **Processing time** renders as `—`.
- **PDF** and **images** both render as `0`.
- The **no roster** chip does not render at all.

## Where the UI reads these values

`frontend/src/pages/ResultsPage.tsx`:

```tsx
const duration = fmtDuration(run?.started_at, run?.finished_at)   // → null if either is missing
...
<span>{duration ?? '—'} processing time</span>
<span>{run.counts.pdf ?? 0} PDF</span>
<span>{run.counts.image ?? 0} images</span>
{(run.counts.no_roster ?? 0) > 0 && <span>{run.counts.no_roster} no roster</span>}
```

So the UI is correct — it simply reflects what the run record contains:

- `duration` is `null` when `started_at` **or** `finished_at` is missing → shows `—`.
- `counts.pdf` / `counts.image` fall back to `0` when those keys are absent.
- the `no roster` chip is hidden when `counts.no_roster` is absent/0.

## What the database actually holds

Querying the live `runs` table:

```
cycle_month = AUGUST 2025
status      = DONE
stage       = done
started_at  = None                ← missing
finished_at = 2026-05-25 05:41:59+00:00
counts      = {'total': 137, 'valid': 0, 'review': 227, 'invalid': 93}
                                   ← no 'pdf', 'image', or 'no_roster' keys
```

The record is missing **exactly** the two things the new UI needs:
`started_at` and the `pdf` / `image` / `no_roster` count keys.

## Root cause — the worker was never restarted

The current source of `backend/perdiem/worker/runner.py` **does** write both:

```python
# started_at, set at the parsing stage
repo.update_run_status(session, run_id, "RUNNING", stage="parsing", progress=5,
                       started_at=dt.datetime.now(dt.timezone.utc))
...
# roster file-type tally, merged into counts
roster_stats = {"pdf": 0, "image": 0, "no_roster": 0}
...
counts = {"total": len(claims), "valid": 0, "review": 0, "invalid": 0}
counts.update(roster_stats)        # → adds pdf/image/no_roster
```

Yet the stored run has neither. That means **the run was produced by an older
version of the worker than the one currently on disk.** The timeline confirms it:

| Time (local) | Event |
|---|---|
| **11:35:30 AM** | Worker process (PID 10851) started → loaded `runner.py` into memory |
| **12:20:57 PM** | `runner.py` edited to add `started_at` + `roster_stats` |
| **12:41:59 PM** | `AUGUST 2025` run finished — processed by the worker still running 11:35 code |

The worker runs as:

```sh
../.venv/bin/python -m perdiem.worker.runner
```

— a plain long-lived process with **no auto-reload**. Only the API has it
(`uvicorn … --reload`). Python loads a module's bytecode once at process start, so
editing `runner.py` afterwards has **no effect** on the already-running worker. When
the pipeline was re-run, the stale worker executed the *old* code path that never
set `started_at` and never merged the roster tally into `counts`.

> The API picking up edits (via `--reload`) while the worker does not is the trap:
> the front-of-house looks updated, but the code that actually writes run stats is
> the background worker, and that one is frozen at its start time.

## Confirmed from the live API + DB (network + DB Navigator)

The `GET /api/runs/{id}` response confirms the missing fields directly:

```json
{
  "status": "DONE", "stage": "done", "progress": 100,
  "counts": { "total": 137, "valid": 0, "review": 227, "invalid": 93 },
  "started_at": null,
  "finished_at": "2026-05-25T05:41:59.416904Z"
}
```

- `started_at: null` → `fmtDuration` returns `null` → processing time renders `—`.
- `counts` has no `pdf`/`image`/`no_roster` keys → those render `0` / hidden.

### Important: the PDF/image tally does **not** come from `claims.roster_refs`

Inspecting the `claims` table, `roster_refs` stores **only the URL**:

```jsonc
// claims.roster_refs — one row
[{"url": "https://drive.google.com/open?id=1dr18w38t..."}]
```

This is because `repository.create_claim` persists just the link:

```python
# repository.py:113
roster_refs=[{"url": u} for u in claim.roster_links],
```

So the resolved `content_type` / `status` / `local_path` from `fetch_rosters` are
**never written to the DB** — you genuinely cannot tell from the `claims` table
whether a roster is a PDF or an image.

**But that DB gap is not why the counts are 0.** The pdf/image tally is computed
**in-memory** during the download stage (from `roster_map`) and written only to
`run.counts`; the GET endpoint returns that stored value verbatim and never
recomputes from `claims`. So the counts are missing for the *same* reason as
`started_at`: the stale worker never executed the code that produces them.

Two distinct layers, easy to conflate:

| Symptom | Immediate cause | Fix |
|---|---|---|
| `started_at` null; `pdf`/`image` keys absent | stale worker running old bytecode | restart worker + re-run |
| can't tell PDF vs image from the DB | `roster_refs` stores only `{url}`; resolved `content_type`/`status` discarded after the run | persist resolved refs back to the claim (enhancement, below) |

## Resolution

1. **Restart the worker** so it loads the updated `runner.py`:

   ```sh
   # stop the running worker (PID 10851 in this session), then from repo root:
   cd backend && set -a && . ../.env && set +a \
     && ../.venv/bin/python -m perdiem.worker.runner
   ```

2. **Trigger a fresh run** from the UI (Run page). The existing `AUGUST 2025`
   record cannot be back-filled for free: `pdf`/`image`/`no_roster` are derived
   during the *download* stage, so the stats only appear on a run executed by the
   new code. A fresh run will populate `started_at`, `finished_at`, and the roster
   tally, and the UI stats will render.

### Optional: make this not happen again

The worker has no reload mechanism, so any future engine/worker edit needs a manual
restart. Options:

- Run the worker under a file-watcher in dev, e.g. `watchmedo auto-restart` (from
  `watchdog`): `watchmedo auto-restart -d perdiem -p '*.py' -- python -m perdiem.worker.runner`.
- Or document a one-liner restart in the `Makefile` and use it after every backend edit.

### Enhancement: persist the resolved roster refs (closes the DB gap)

Today the worker holds the resolved `RosterRef`s (which carry `content_type`,
`status`, `local_path`, `file_id`) only in memory, then throws them away after
computing `run.counts`. Persisting them back onto the claim would make the system
robust: counts become **re-derivable from the DB**, the UI can show per-claim
roster type, and re-runs stay idempotent without depending on `run.counts`.

Sketch (worker, right after `fetch_rosters`):

```python
# perdiem/worker/runner.py — after building roster_map
for i, refs in roster_map.items():
    repo.update_claim_roster_refs(
        session, claim_id_map[i],
        [{"url": r.source_url, "file_id": r.file_id,
          "content_type": r.content_type, "status": r.status} for r in refs],
    )
session.commit()
```

```python
# perdiem/db/repository.py — new helper
def update_claim_roster_refs(session, claim_id, refs: list[dict]) -> None:
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise ValueError(f"Claim {claim_id} not found")
    claim.roster_refs = refs
    session.flush()
```

No schema migration is needed — `claims.roster_refs` is already `JSONB`; this only
enriches the objects stored in it. The `web/results.py` / `exceptions.py` readers
that do `ref.get("url")` keep working unchanged.

## Secondary observation (separate from the "shows nothing" bug)

Even once the worker is restarted, the counts may show `0 PDF / 0 images` with a
large `no roster` number **if Drive downloads fail** in this environment. Evidence
from the current record: `valid: 0`, `review: 227`, `invalid: 93` — zero payable
days is the signature of no usable roster reaching OCR (`fetch_rosters` returning
`UNREACHABLE` for every claim, e.g. missing `gcloud` auth for the service account).
`backend/perdiem/engine/drive.py` resolves a roster to `pdf`/`image` only when the
download succeeds (`status == "OK"`); on auth/permission failure it returns
`status="UNREACHABLE"`, `content_type=None`, which the worker tallies as
`no_roster`.

If a post-restart run still shows `0 PDF / 0 images` with everything under
`no roster`, the next thing to check is Drive auth:

```sh
gcloud auth print-access-token --account=<drive_account>
```

That is a roster-retrieval issue, not the processing-stats bug analysed here.
