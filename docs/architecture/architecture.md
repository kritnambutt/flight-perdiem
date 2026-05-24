# System Architecture — Per Diem Validation System

Architecture for the system specified in
[../REQUIREMENTS.md](../REQUIREMENTS.md), with the flows in
[../flows/system-flow.md](../flows/system-flow.md) and build phases in
[../plans/implementation-plan.md](../plans/implementation-plan.md).

## Decisions (locked by the user)

| Area | Choice |
|------|--------|
| Frontend | **React + Vite**, package manager **pnpm**, styling **Tailwind CSS** |
| Backend | **Python + FastAPI**, local dev in **venv** |
| OCR | **Tesseract + OpenCV** (local, free) |
| Deployment | **Docker** (docker-compose), runs on the **Raspberry Pi 5 (arm64)** |
| Edge / DNS / TLS | **Cloudflare** (DNS + **Cloudflare Tunnel**) — **no nginx**; FastAPI serves the built SPA directly |
| Cost | **Zero recurring cost** — all open-source, self-hosted |

---

## Do we need a database? — Yes (PostgreSQL)

**Yes, the system needs a database.** The pipeline alone is stateless, but the
product around it is not: review state and decisions must **persist between runs
and survive restarts**.

What must be stored:
- **Runs** — each cycle execution, its status/progress, counts, timing.
- **Per-claim verdicts** — VALID / NEEDS_REVIEW / INVALID, the deciding rule,
  extracted roster fields, OCR confidence (so the exception queue can be rebuilt
  without re-OCR).
- **Manual decisions/overrides** — who approved/rejected/corrected, when, why
  (F19) — this is *new* state that exists nowhere else.
- **Audit trail** (N1) and **config** (rotating flight numbers, rate, thresholds
  — F13/F21).

**Database: PostgreSQL** (runs as its own container on the Pi).
- Robust relational store with strong concurrency — the API and the worker write
  the same tables simultaneously (run progress + verdicts), which Postgres
  handles cleanly.
- Rich types (JSONB for extracted fields / counts, proper timestamps,
  constraints/indexes) that keep the audit and verdict data well-structured.
- Still **free and self-hosted**: the official `postgres` image has an
  **arm64** build, so it runs on the Pi at zero cost.
- Accessed via **SQLAlchemy** (+ Alembic migrations); psycopg driver.
- Backup = `pg_dump` (scriptable, can be scheduled).

> The **master report `.xlsx`** and **roster image cache** are *files*, not DB
> rows. Postgres stores metadata/decisions and references those files; the Excel
> output remains the deliverable artifact (§4.3).

> **Pi note:** Postgres needs a bit more RAM than an embedded DB — fine on a Pi
> 4/5 (≥4 GB). Give its data a **persistent Docker volume** and tune modestly
> (small `shared_buffers`) for the low, single-validator load.

---

## Component architecture

```mermaid
flowchart TB
    subgraph Browser
      UI[React + Vite SPA<br/>staff frontend]
    end

    subgraph CF[Cloudflare edge - free]
      DNS[DNS + TLS]
      TUN[Cloudflare Tunnel]
    end

    subgraph Pi[Raspberry Pi 5]
      direction TB
      CFD[cloudflared<br/>existing host tunnel<br/>already configured]
      subgraph DC[Docker compose]
        API[api container<br/>FastAPI + Uvicorn<br/>serves SPA + REST + OCR engine<br/>:8000 on localhost]
        WK[worker<br/>background job runner<br/>same image as api]
        DB[(db container<br/>PostgreSQL<br/>+ volume)]
        CACHE[(roster cache<br/>volume)]
        OUT[(output xlsx<br/>volume)]
        SEC[(credentials<br/>secret mount)]
      end
    end

    subgraph Google[Google APIs - free tier]
      GS[Sheets API<br/>form responses]
      GD[Drive API<br/>roster files]
    end

    UI -->|HTTPS| DNS
    DNS --> TUN
    TUN -. outbound tunnel .-> CFD
    CFD -->|new hostname route<br/>http://localhost:8000| API
    API <--> DB
    WK <--> DB
    API --> CACHE
    WK --> CACHE
    WK --> OUT
    API --> OUT
    API --> SEC
    WK -->|read| GS
    WK -->|download| GD
```

> No nginx and **no inbound ports opened** to the internet: the Pi's **existing
> `cloudflared`** makes an outbound connection to Cloudflare, which terminates TLS
> and routes a **new public hostname** to the `api` published on
> `localhost:8000`. FastAPI both serves the built SPA static files and the REST
> API on the same origin, so there is no reverse proxy and no
> CORS to manage.

### Responsibilities

| Component | Role |
|-----------|------|
| **React SPA** | Run screen, live progress, results dashboard, exception review queue (roster preview + failing rule), approve/override, config, audit, download (F15–F22). Built by Vite → static files, **served by the api container**. |
| **Cloudflare (edge)** | DNS, TLS termination, and public entry point. Free tier; **Cloudflare Tunnel** removes the need for nginx, port forwarding, or a public IP. |
| **cloudflared** | **Already running on the Pi** (host-level, not in this repo's compose). Dials out to Cloudflare; a new public hostname is mapped to `api` on `localhost:8000`. |
| **api (FastAPI/Uvicorn)** | Serves the **SPA static bundle** + the **REST API** on one origin; auth, reads/writes Postgres, enqueues runs, generates/serves reports. Imports the **engine library**. |
| **worker** | Executes the long pipeline (Google read → download → OCR → validate → aggregate) as a background job; updates run progress in Postgres. Same code/image as api. |
| **engine library** | Pure Python: ingestion, OCR (Tesseract/OpenCV), validation rules R1–R8, dedup, report writer. No web/DB coupling — unit-tested in isolation. |
| **db (PostgreSQL)** | Runs, verdicts, overrides, audit, config. |

---

## Tech stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Frontend | React, Vite, **pnpm**, TypeScript | SPA, built to static assets |
| Styling | **Tailwind CSS** (PostCSS/Vite plugin) | utility-first; purged at build → tiny CSS |
| Frontend serving | **FastAPI StaticFiles** (no nginx) | SPA bundle + API on one origin |
| Edge / DNS / TLS | **Cloudflare** + **cloudflared** (Tunnel) | free; no open ports, no reverse proxy |
| API | FastAPI, Uvicorn | Python; thin layer over engine |
| Background jobs | Worker process polling a Postgres job table (or FastAPI BackgroundTasks for the simplest start) | survives request lifecycle |
| Engine | Python: `openpyxl`, `pandas`, `pytesseract`, `opencv-python-headless`, `Pillow`, `PyMuPDF`/`pdf2image`, Google API client | shared by api + worker |
| OCR | Tesseract (apt) + OpenCV | printed text + HSV red-box detection |
| DB | **PostgreSQL** via SQLAlchemy + Alembic (`psycopg`) | own container + persistent volume |
| Dev (Python) | **venv** + `requirements.txt` / `pyproject.toml` | matches user choice |
| Dev (JS) | **pnpm** + Vite dev server | matches user choice |
| Packaging | **Docker** + docker-compose, arm64 images | runs on Pi |

---

## Repository structure

```
flight-perdiem/
├── backend/                      # Python + FastAPI (venv)
│   ├── perdiem/                  # main package
│   │   ├── engine/               # core validation engine (Phases 1-6) — no web/db coupling
│   │   │   ├── ingest.py         # read Posting Base + Late Submission form responses (F1, F2)
│   │   │   ├── drive.py          # download roster attachments from Google Drive (F3)
│   │   │   ├── ocr/              # roster extraction (Tesseract + OpenCV)
│   │   │   │   ├── preprocess.py # deskew, threshold, denoise, upscale
│   │   │   │   ├── extract.py    # date range, staff ID, name, generated date, flight grid (F4)
│   │   │   │   └── redbox.py     # HSV red-rectangle detection -> claimed days (F5)
│   │   │   ├── rules.py          # eligibility rules R1-R8, R5a (name matching)
│   │   │   ├── pairing.py        # out-and-back pairing across days (R3, F8)
│   │   │   ├── dedup.py          # de-duplicate by (staff_id, date) (R7, F9)
│   │   │   ├── report.py         # write master .xlsx + exception report (F10-F12)
│   │   │   └── models.py         # engine dataclasses (Claim, Verdict, ...)
│   │   ├── web/                  # FastAPI application layer
│   │   │   ├── main.py           # app entrypoint (perdiem.web:app)
│   │   │   ├── deps.py           # dependencies (db session, current user)
│   │   │   ├── auth.py           # login / session / allowed accounts (F14)
│   │   │   ├── routes/           # API endpoints
│   │   │   │   ├── runs.py       # start run, status/progress, results (F15-F17)
│   │   │   │   ├── exceptions.py # review queue (F18)
│   │   │   │   ├── claims.py     # approve / override / correct (F19)
│   │   │   │   ├── reports.py    # publish / download (F20)
│   │   │   │   ├── config.py     # routes / flight numbers / rate (F21)
│   │   │   │   └── audit.py      # audit trail view (F22)
│   │   │   └── schemas.py        # Pydantic request/response models
│   │   ├── worker/               # background job runner
│   │   │   └── runner.py         # pick up queued runs, drive the engine, update progress
│   │   ├── db/                   # persistence (PostgreSQL via SQLAlchemy)
│   │   │   ├── models.py         # runs, claims, verdicts, overrides, audit, config
│   │   │   ├── session.py        # engine/session factory
│   │   │   └── migrations/       # schema migrations (alembic)
│   │   └── config.py             # settings (env-driven): paths, thresholds, Google creds
│   ├── tests/                    # pytest — engine unit tests + API tests
│   │   ├── fixtures/             # copies of docs/example-files for deterministic tests
│   │   ├── test_rules.py
│   │   ├── test_ocr.py
│   │   └── test_api.py
│   ├── requirements.txt          # (or pyproject.toml) pinned deps
│   └── Dockerfile                # multi-stage: node(pnpm build SPA) -> python:3.12-slim + tesseract/opencv, serves dist/
│
├── frontend/                     # React + Vite + pnpm (TypeScript)
│   ├── src/
│   │   ├── pages/                # top-level screens (one per route)
│   │   │   ├── RunPage.tsx       # select cycle month + Run + live progress (F15, F16)
│   │   │   ├── ResultsPage.tsx   # per-crew results dashboard (F17)
│   │   │   ├── ExceptionsPage.tsx# exception review queue + roster preview (F18, F19)
│   │   │   ├── ConfigPage.tsx    # routes / flight numbers / rate / thresholds (F21)
│   │   │   ├── AuditPage.tsx     # audit trail (F22)
│   │   │   └── LoginPage.tsx     # sign in (F14)
│   │   ├── components/           # reusable UI (RosterPreview, ProgressBar, VerdictBadge, ...)
│   │   ├── hooks/                # custom React hooks (useRun, usePolling, useAuth)
│   │   ├── contexts/             # React context providers (AuthContext)
│   │   ├── lib/                  # API client, fetch wrapper, helpers
│   │   ├── config/               # frontend config (API base URL, constants)
│   │   ├── types/                # TypeScript types (shared API shapes)
│   │   ├── styles/               # global styles + Tailwind directives (index.css)
│   │   ├── App.tsx               # router + layout
│   │   └── main.tsx              # Vite entrypoint
│   ├── index.html                # Vite HTML shell
│   ├── vite.config.ts            # dev proxy /api -> backend, build config
│   ├── tailwind.config.ts        # Tailwind theme + content paths
│   ├── postcss.config.js         # PostCSS (tailwindcss + autoprefixer)
│   ├── package.json              # pnpm scripts/deps
│   └── pnpm-lock.yaml            # built to dist/ and served by the api container (no own runtime image)
│
├── docker-compose.yml            # api (FastAPI, serves SPA) + worker + db
├── .env.example                  # env template (DATABASE_URL, POSTGRES_PASSWORD, secrets path)
├── secrets/                      # google-credentials.json (gitignored, chmod 600)
│
└── docs/                         # requirements, flows, plans, architecture, example-files
```

> No `cloudflared` in the repo: the Pi 5 **already runs Cloudflare Tunnel**. To
> publish, just add a new **public hostname** on the existing tunnel pointing at
> the api (e.g. `http://localhost:8000`). The repo only ships the app + compose.

---

## Containers & deployment (Docker on Pi)

Three small services via `docker-compose` (at the repo root), all **arm64** for
the Pi 5 — **no nginx, no cloudflared container** (the Pi already runs one):

| Service | Base image | Purpose |
|---------|-----------|---------|
| `api` | `python:3.12-slim` (+ tesseract, libgl); multi-stage with `node:20-alpine` to build the SPA | FastAPI/Uvicorn — serves SPA **and** REST; published on `127.0.0.1:8000` |
| `worker` | same image as `api` | run pipeline jobs |
| `db` | `postgres:16-alpine` | PostgreSQL (arm64), persistent volume |

The **api Dockerfile** is multi-stage: `node:20-alpine` runs `pnpm build` to
produce the SPA `dist/`, then the `python:3.12-slim` stage installs Tesseract +
OpenCV deps via apt, pip-installs the backend, and copies in `dist/` so FastAPI
serves it with `StaticFiles`. The api is published only on **`127.0.0.1:8000`**
so the **existing host `cloudflared`** can reach it; nothing is exposed to the
LAN/internet directly.

```yaml
# docker-compose.yml (repo root, sketch)
services:
  api:
    build: .                    # multi-stage: builds SPA + python runtime
    command: uvicorn perdiem.web:app --host 0.0.0.0 --port 8000
    env_file: .env              # DATABASE_URL=postgresql+psycopg://perdiem:***@db:5432/perdiem
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - roster-cache:/data/cache
      - output:/data/output
      - ./secrets/google-credentials.json:/run/secrets/google.json:ro
    ports: ["127.0.0.1:8000:8000"]   # localhost only — host cloudflared routes here
    restart: unless-stopped

  worker:
    build: .
    command: python -m perdiem.worker
    env_file: .env              # same DATABASE_URL
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - roster-cache:/data/cache
      - output:/data/output
      - ./secrets/google-credentials.json:/run/secrets/google.json:ro
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: perdiem
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: perdiem
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U perdiem"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  pgdata:
  roster-cache:
  output:
```

**Exposure:** in the Cloudflare dashboard, add a **new public hostname** on the
Pi's existing tunnel → `http://localhost:8000`. No new tunnel, no token in this
repo, no port forwarding.

`api` and `worker` talk to the same **`db` (Postgres)** over the compose network
(`DATABASE_URL` pointing at `db:5432`) and share the cache/output volumes, so the
worker writes results the API can read. Both wait for the db healthcheck before
starting. Run with `docker compose up -d --build`; `restart: unless-stopped`
survives reboot. Apply schema migrations (Alembic) on api startup or as a one-off
`docker compose run --rm api alembic upgrade head`.

> Build/run on the Pi directly (native arm64) or use `docker buildx` for
> multi-arch images. No paid registry needed — build on-device or push to a free
> registry.

---

## Persistence / volumes

| Volume | Holds | Backup |
|--------|-------|--------|
| `pgdata` | PostgreSQL data (runs, verdicts, overrides, audit, config) | `pg_dump` (schedulable) |
| `roster-cache` | downloaded roster images (avoid re-download/OCR, N2) | optional |
| `output` | generated master `.xlsx` + exception reports | **back up** (source of truth) |
| secret mount | Google service-account JSON (read-only, `chmod 600`) | keep out of git |

---

## Request / run flow

```mermaid
sequenceDiagram
    participant U as Staff (React)
    participant W as Cloudflare (DNS+TLS+Tunnel)
    participant A as FastAPI (serves SPA + API)
    participant Q as Worker
    participant D as PostgreSQL
    participant G as Google APIs

    U->>W: POST /api/runs {month}
    W->>A: existing tunnel -> localhost:8000
    A->>D: insert run (status=queued)
    A-->>U: run_id
    Q->>D: pick up queued run
    Q->>G: read responses + download rosters
    Q->>Q: OCR + validate + dedup
    Q->>D: write verdicts, progress, audit
    loop poll
      U->>A: GET /api/runs/{id}
      A->>D: read status/progress
      A-->>U: progress + counts
    end
    U->>A: GET /api/runs/{id}/exceptions
    U->>A: POST /api/claims/{id}/decision
    A->>D: store override; re-aggregate
    U->>A: GET /api/runs/{id}/report
    A-->>U: master.xlsx + exceptions
```

---

## PostgreSQL schema (sketch)

`*_json` columns use **JSONB**; ids are `bigserial`/UUID; timestamps are
`timestamptz`. Managed with Alembic migrations.

```sql
runs(id, cycle_month, status, progress, counts jsonb,
     started_at timestamptz, finished_at timestamptz)
claims(id, run_id -> runs, source, source_row_ref, staff_id, name, email,
       claim_month, claimed_days jsonb, roster_refs jsonb)
verdicts(id, claim_id -> claims, claimed_date date, verdict, rule, reason,
         confidence, extracted jsonb)
overrides(id, claim_id -> claims, decision, decided_by, decided_at timestamptz, note)
audit(id, run_id, claim_id, action, detail jsonb, at timestamptz)
config(key primary key, value jsonb)   -- routes, flight numbers, rate, thresholds
```

Useful indexes: `claims(run_id)`, `verdicts(claim_id)`,
`verdicts(staff_id, claimed_date)` for the dedup/aggregation step (R7).

---

## Local development

**Database (local Postgres for dev):**
```bash
# easiest: just the db service from compose
docker compose up -d db          # compose lives at the repo root
# then point the backend at it
export DATABASE_URL="postgresql+psycopg://perdiem:perdiem@localhost:5432/perdiem"
```

**Backend (venv):**
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# needs tesseract locally: macOS `brew install tesseract`, Debian `apt install tesseract-ocr`
alembic upgrade head          # apply migrations to the dev Postgres
uvicorn perdiem.web:app --reload
```

**Frontend (pnpm + Vite + Tailwind):**
```bash
cd frontend
pnpm install
# Tailwind (one-time scaffold): pnpm add -D tailwindcss postcss autoprefixer && pnpm dlx tailwindcss init -p
# then add the @tailwind directives to src/styles/index.css and import it in main.tsx
pnpm dev          # Vite dev server, proxy /api -> http://localhost:8000
```

Engine logic is tested directly with `pytest` against `docs/example-files`
fixtures — no DB needed for the pure-engine unit tests; API/integration tests use
a disposable Postgres (the `db` container, or a `testcontainers` instance).

---

## Security

- **Edge:** **Cloudflare terminates TLS** and fronts the app via the Pi's
  **existing Cloudflare Tunnel** — a new public hostname is just added to it. **No
  inbound ports** to the internet and the home IP stays hidden; the api is bound
  to `127.0.0.1` only. Optionally add **Cloudflare Access** for an extra auth layer.
- **Auth** on the web app itself (F14) regardless of the edge.
- Roster images and names are **PII** (N5): served only to authenticated staff,
  stored in private volumes.
- Google credentials mounted read-only as a secret; never baked into an image or
  committed. The Cloudflare Tunnel credentials live with the host tunnel (already
  configured), not in this repo.

---

## Why this fits the constraints

- **Zero cost:** every component (React/Vite/pnpm/Tailwind, FastAPI, Tesseract,
  OpenCV, PostgreSQL, Docker, Cloudflare Tunnel) is free/open-source or free-tier;
  Google Sheets/Drive use the free tier. No nginx, no paid hosting.
- **Self-hosted on Pi 5:** small arm64 containers including a modest PostgreSQL,
  batch workload — comfortable on a Pi 5 (≥4 GB). Cloudflare Tunnel publishes it
  with no port forwarding.
- **Maintainable:** engine stays a pure library reused by API, worker, and CLI;
  the website is a thin layer over it.
