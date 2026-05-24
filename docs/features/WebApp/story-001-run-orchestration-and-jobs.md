| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-WEB-001                                         |
| Title        | Run orchestration & background jobs                |
| Epic         | EP-WEB — Web Application                           |
| Dependencies | FastAPI, worker process, PostgreSQL, engine library|
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §6.6 (F15, F16); plan Phase 8    |

## 🗂 Epic Overview — EP-WEB

See [overview.md](./overview.md). This story lets staff start a cycle run and
watch it progress, with the heavy pipeline running off the request thread.

## 📝 Feature Overview — PD-WEB-001

### User Story

```gherkin
As an admin
I want to pick a cycle month and start a run with one click
So that the whole pipeline runs without me using a terminal

As an admin
I want to see live progress and counts while it runs
So that I know it's working and roughly how long is left
```

### Pre-conditions

- Engine library (Ingestion→Reporting) is importable.
- PostgreSQL is reachable; a worker process is running.

### Scope

#### Included

- `POST /api/runs` — start a run for a month; insert a `runs` row
  (`status=queued`), return `run_id` immediately (F15).
- A **worker** picks up queued runs and executes the pipeline, writing
  progress/verdicts/audit to Postgres.
- `GET /api/runs/{id}` — status + progress stage + counts (F16).
- Run states: `queued → downloading → ocr → validating → aggregating → done`
  (or `error`).
- One concurrent run at a time (protect the Pi).

#### Excluded

- Auth (PD-WEB-002), results/exception UI (PD-WEB-003), reports (PD-WEB-005).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Start run (F15)** — `POST /api/runs {month}` returns `run_id` without
   blocking; the pipeline does **not** run in the request thread.
2. **Worker execution** — the worker claims a queued run, executes
   Ingestion→Validation→Reporting, updating progress at each stage.
3. **Progress (F16)** — `GET /api/runs/{id}` returns `{status, stage, counts:
   {processed, valid, review, reject}}`; the SPA polls it.
4. **Concurrency** — a second start while one is running is queued or rejected
   with a clear message (configurable; default: one at a time).
5. **Crash safety** — a worker restart mid-run leaves the run resumable or marks
   it `error` cleanly; no half-written master sheet.

### Error Scenarios

- Engine raises mid-run → run marked `error` with a message; partial state not published.
- Duplicate start for the same month → return the existing in-flight run.
- Worker down → run stays `queued`; surfaced in the UI as not progressing.

## 🧩 Technical Documentation

### Endpoints

```
POST /api/runs            { month } -> { run_id }
GET  /api/runs/{id}       -> { status, stage, counts, started_at, finished_at }
GET  /api/runs            -> recent runs (history)
```

### Job model

- Runs table is the queue (`status`, `progress`, `counts jsonb`).
- Worker (`python -m perdiem.worker`) polls for `queued`, sets `running`, updates
  progress, finalises `done`/`error`.
- FastAPI BackgroundTasks acceptable as the simplest start; dedicated worker is
  the target (survives request lifecycle).

### Frontend

- `RunPage.tsx`: month picker + **Run** button; progress bar + live counts via
  `useRun` / `usePolling` hooks calling `GET /api/runs/{id}`.

## 🔨 Implementation Plan

1. 📝 **TODO** `runs` schema + repository (see Platform PD-PLAT-001).
2. 📝 **TODO** `POST /api/runs` enqueue; `GET /api/runs/{id}` status.
3. 📝 **TODO** Worker loop: claim → run engine → update progress → finalise.
4. 📝 **TODO** Progress reporting hooks in the engine (stage callbacks).
5. 📝 **TODO** RunPage UI with polling + counts.
6. 📝 **TODO** Concurrency guard + crash-safety tests.

## 🏗 Structure

```
backend/perdiem/web/routes/runs.py     # start + status + history
backend/perdiem/worker/runner.py       # background pipeline executor
frontend/src/pages/RunPage.tsx
frontend/src/hooks/{useRun,usePolling}.ts
```

## 📌 Notes / Open Questions

- Polling vs Server-Sent Events for progress — polling is simplest on the Pi; SSE
  later if needed.
- Resume semantics on worker restart — resumable vs mark-error-and-rerun.
