# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Skills — automatic triggers

### task-implementer
Trigger: user asks to implement a story or task from `docs/features/`.

Matching phrases (invoke **before doing anything else**):
- "help to implement this story …"
- "implement story …" / "implement task …"
- "help implement …" (when referring to a docs/features story)
- "/task-implementer"

When triggered, invoke the Skill tool with `skill: "task-implementer"` immediately.

### feature-creation
Trigger: user wants to write a new user story, spec a feature, or capture a requirement.

Matching phrases: "create a story …", "write a user story …", "spec out …", "new feature story …", "/feature-creation".

When triggered, invoke the Skill tool with `skill: "feature-creation"` immediately.

## Commands

All common tasks are in the `Makefile`. Run `make help` for the full list.

### Local dev (three terminals)
```bash
make backend-dev      # FastAPI on :8000, auto-reload
make worker-dev       # pipeline worker, polls DB for PENDING runs
make frontend-dev     # Vite on :5173, proxies /api → :8000
```

### Setup (first time)
```bash
make setup            # copies .env.example → .env (then fill in values)
make install          # creates backend/.venv + installs Python deps + pnpm deps
docker compose up -d db
docker compose up db-init   # one-shot: creates perdiem role + DB
make backend-migrate  # runs Alembic migrations
```

### Tests
```bash
make test             # engine + ML unit tests only — no DB, runs anywhere
make test-all         # all tests including DB integration (needs Docker)
# single file:
cd backend && ../.venv/bin/pytest tests/engine/test_rules.py -v
# single suite:
cd backend && ../.venv/bin/pytest tests/engine/ -v
cd backend && ../.venv/bin/pytest tests/ml/ -v
cd backend && ../.venv/bin/pytest tests/db/ -v   # requires Docker
```

### Quality
```bash
make lint             # ruff check
make format           # ruff format
```

### Docker (full stack / production)
```bash
make up               # build + start api, worker, db
make down             # stop
make logs             # tail api + worker
make migrate          # run Alembic inside the running api container
```

### ML (Roster Intelligence, EP-ML)
```bash
make ml-dataset                             # build labelled dataset from 3 workbooks → data/ml/datasets/
make ml-dataset ARGS="--version 2026-05"    # name the version
backend/.venv/bin/python scripts/eval_ml.py --dataset-version dev --split test
backend/.venv/bin/python scripts/train_triage.py --dataset-version dev
```

## Architecture

### Backend layers (`backend/perdiem/`)

```
engine/   ← PURE library — no FastAPI, SQLAlchemy, or network calls
web/      ← FastAPI: thin routes that call engine functions, persist via db/
worker/   ← background process: polls DB for PENDING runs, executes pipeline
db/       ← SQLAlchemy ORM, Alembic migrations, session, repository
ml/       ← completely separate from engine/web/worker — ML data prep, eval, triage
```

**The engine is sacrosanct.** `perdiem/engine/` must never import from `web`, `worker`, `db`, or `ml`. All rule functions are pure predicates so they can be unit-tested against `docs/example-files/` fixtures with no database or network.

The worker communicates with the API **only through the database** — it polls `runs` for `PENDING` status, updates `stage`/`progress`/`counts`, writes `verdicts`. No direct calls between worker and API.

### Request → pipeline flow

1. Admin uploads two `.xlsx` files via `POST /api/runs` (multipart).
2. API creates a `Run` row (status `PENDING`), saves the files to `UPLOADS_DIR`, returns the run ID immediately.
3. Worker picks it up, runs the pipeline: ingest → download → OCR → validate → dedup → report.
4. Frontend polls `GET /api/runs/{id}` for `status`, `stage`, and `counts`; shows live progress.
5. Results at `GET /api/runs/{id}/results`; exceptions at `GET /api/runs/{id}/exceptions`.

### Engine modules

| Module | Role |
|---|---|
| `ingest.py` | Parses `.xlsx` form responses → `Claim` dataclasses |
| `drive.py` | Downloads roster attachments from Google Drive by file ID |
| `ocr/` | `preprocess.py` → `extract.py` → `redbox.py`; emits `ExtractedRoster` with per-field confidence |
| `rules.py` | R1–R8 predicates + `validate_claim` orchestrator → one `DayVerdict` per claimed day |
| `pairing.py` | R3: out-and-back pairing (DMK→HKT on day N, HKT→DMK on day N+1) |
| `identity.py` | R5/R5a: exact staff ID + fuzzy name matching |
| `dedup.py` | R7: de-duplicate by `(staff_id, date)` across all claims |
| `report.py` | Writes the master xlsx and exception xlsx |
| `triage.py` | PD-ML-004 inference; falls back to rules-only if disabled or model missing |

### Database (6 tables)

`runs → claims → verdicts` (cascade delete). `overrides` track manual approvals/rejections. `audit` is an append-only event log. `config` stores one active row for flight numbers, rate, and thresholds.

Key index: `verdicts(staff_id, claimed_date)` for dedup lookups.

### Frontend

React SPA served by FastAPI from `frontend/dist/`. In dev, Vite (`localhost:5173`) proxies `/api` to `:8000`. Auth is a password-only login that sets an httpOnly JWT cookie; all non-public routes require it.

Pages: `RunPage` (start a run + live polling) → `ResultsPage` + `ExceptionsPage` (review verdicts, override) → `ConfigPage` (flight numbers, rate) → `AuditPage`. UI components are the Catalyst UI Kit (copy-pasted into `src/components/ui/`, not an npm package).

### ML (EP-ML — independent of the web app)

`backend/ml/` and `scripts/` are never imported by the engine, web, or worker. They are offline batch tools that read from the 3 workbooks under `docs/example-files/` and write labelled datasets to `data/ml/` (gitignored, PII). The triage model (`data/ml/models/triage.json`) ships disabled (`TRIAGE_ENABLED=false`) and is advisory only.

## Key invariants

- **N1 (auditability):** every `DayVerdict` carries the deciding `rule` tag (`"R1"`…`"R8"`) and a human-readable `reason`. Never make a payable/rejected decision without a rule tag.
- **N2 (idempotency):** re-running a cycle must produce the same verdicts; no double-counting.
- **One concurrent run at a time** (Pi 5 constraint — enforced by the worker).
- **Roster images are PII** — always serve through the auth-gated `/api/rosters/{file_id}` endpoint, never with a public URL.
- Verdict states: `VALID | VALID_BACKCLAIM | NEEDS_REVIEW | INVALID`.

## Environment

The venv lives at `backend/.venv`. All `make` commands use it automatically. For direct invocations: `backend/.venv/bin/python` / `backend/.venv/bin/pytest`.

Required `.env` keys: `ADMIN_PASSWORD`, `JWT_SECRET`, `POSTGRES_PASSWORD`, `DB_ADMIN_USER`, `DB_ADMIN_PASSWORD`. See `.env.example` for all options. Docker compose overrides `DATABASE_URL`, `ROSTER_CACHE_DIR`, `UPLOADS_DIR`, `REPORTS_DIR` automatically.
