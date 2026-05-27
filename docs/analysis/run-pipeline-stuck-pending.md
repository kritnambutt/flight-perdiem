# Run Pipeline Stuck at PENDING (Worker Not Running)

**Date:** 2026-05-25  
**Status:** Fixed  
**Symptom:** Clicking **Run pipeline** on the Run page succeeds (no error, a run row appears), but the run stays at **PENDING — Not started** forever. No stages (parsing → downloading → … → done) ever progress.

---

## Observed Behaviour

| Step | Result |
|------|--------|
| `POST /api/runs` | 201 Created — returns `run_id`, files saved to `uploads_dir/<run_id>/` |
| Run appears in "Recent runs" | Yes, status `PENDING`, `started_at = null` ("Not started") |
| Pipeline stages advance | **Never** — stays PENDING indefinitely |

Locally the developer ran **only** two processes:

```
make backend-dev     # FastAPI (the API)
make frontend-dev    # Vite dev server
```

---

## Root Cause

The system is **two separate backend processes**, by design (see `.claude/rules/objective.md`
and `backend-standards.md`):

1. **API** (`perdiem.web.main:app`, via `make backend-dev`)
   On `POST /api/runs` it does three things and returns immediately:
   - inserts a `Run` row with `status="PENDING"` (`repository.create_run`, `runs.py:45`),
   - saves the two uploaded `.xlsx` files under `uploads_dir/<run_id>/`,
   - returns `{"run_id": ...}`.
   It **never executes the pipeline** — endpoints must return quickly; long work is
   delegated to the worker.

2. **Worker** (`perdiem.worker.runner`, a standalone process)
   A polling loop (`runner.py:202`) that every 5s queries for the oldest `PENDING`
   run, then runs the full pipeline, flipping `status` to `RUNNING` and advancing
   `stage` until `DONE`/`FAILED`.

```
Browser ──POST /api/runs──▶ API ──INSERT status=PENDING──▶  Postgres
                                                              │
                                                  (polls every 5s)
                                                              ▼
                                              Worker ──UPDATE status=RUNNING…DONE
```

The API and worker communicate **only through the database** — there is no in-process
queue and the API does not spawn the worker. So with no worker process running, nothing
ever transitions `PENDING → RUNNING`, and the run sits idle.

### Why this wasn't obvious

- The UI shows the run immediately (the API call genuinely succeeded), so it *looks*
  like the pipeline started.
- In **Docker** (`make up`) the worker is a first-class service in `docker-compose.yml`
  (the `worker` container runs `python -m perdiem.worker.runner`), so it "just works"
  there. The gap only appears in **local dev**.
- The `Makefile` had `backend-dev` and `frontend-dev` targets but **no `worker-dev`**,
  so there was no documented way to start the worker outside Docker.

---

## Fix

Added a `worker-dev` target to the `Makefile` (mirrors `backend-dev` — sources `.env`,
runs from `backend/`, uses the venv):

```makefile
.PHONY: worker-dev
worker-dev: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/python -m perdiem.worker.runner
```

…and listed it in `make help` under "Local dev (no Docker)".

### How to run locally (three processes)

Local dev needs **three** terminals, not two:

```
make backend-dev     # terminal 1 — API on :8000
make worker-dev      # terminal 2 — pipeline worker (NEW)
make frontend-dev    # terminal 3 — Vite on :5173
```

With the worker running, an existing PENDING run is picked up within ~5s; the worker log
prints `Picked up run <id>` and the UI's stage/progress begin to advance.

> The two already-PENDING "AUGUST 2025" runs from before the fix will be picked up
> automatically once the worker starts — no need to resubmit.

---

## What You'll Hit Next (downstream dependencies)

Once the worker runs, the pipeline reaches stages that need external tools. These are
**separate** from this bug but worth knowing so the next failure isn't a surprise:

| Stage | Dependency | If missing |
|-------|-----------|-----------|
| `downloading` | Google Drive access via the service account (`scripts/auth_drive.py`) | Roster downloads return non-OK refs; affected claims get `NEEDS_REVIEW` |
| `ocr` | Tesseract + OpenCV installed on the host | OCR wrapped in try/except (`runner.py:134`) — logs a warning, claim proceeds without extracted fields |

The pipeline is defensive (OCR failures don't crash the run), so even without Drive/OCR
fully set up, the run should still reach `DONE` with claims flagged for review rather than
hanging. If a run goes to `FAILED`, check the worker log — the traceback and a
`run_failed` audit entry (with the error string) are written there.

---

## Key Takeaway

The API and worker are **two processes that talk only through Postgres**. Creating a run
(API) and executing it (worker) are decoupled on purpose. Local dev must run the worker
alongside the API:

| Context | Worker started by |
|---------|-------------------|
| Docker (`make up`) | the `worker` service in `docker-compose.yml` (automatic) |
| Local dev | **`make worker-dev`** — a third process you start yourself |
