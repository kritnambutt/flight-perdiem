# flight-perdiem

Automated validation of cabin-crew **per diem (sector allowance)** claims for
AirAsia (DMK base). Cabin crew submit claims via Google Forms and attach their
crew schedule report (roster); this system reads those submissions, OCRs the
rosters, validates each claimed day against the per diem rules, de-duplicates
across submissions, and produces the payable master report — replacing a slow,
fully manual review.

> **Status:** ✅ Core system complete — engine, DB, web app, and Docker deployment
> are all built and tested. Run `docker compose up -d --build` on the Raspberry Pi to
> go live. 🚧 The **Roster Intelligence (EP-ML)** epic is in progress to harden roster
> extraction + claim triage ([details](#machine-learning--roster-intelligence-ep-ml)).

---

## What the system does

```
Admin uploads two .xlsx files (Google Form responses)
    ↓
Parse both workbooks → one Claim row per form submission
    ↓
Download each crew's roster PDF/image from Google Drive
    ↓
OCR each roster → date range, staff ID, name, generated date, flight grid
    ↓
Validate each claimed day: route (R1), flight number (R2), pairing (R3),
proof date (R4), identity (R5/R5a), period coverage (R6), month routing (R8)
    ↓
De-duplicate by (staff_id, date) across all submissions (R7)
    ↓
Results dashboard → review flagged claims → approve / reject → download report
```

Full eligibility rules and data sources: [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12 + **FastAPI** (serves SPA and REST API on one origin) |
| Engine | Pure Python library — `ingest`, `drive`, `ocr`, `rules`, `pairing`, `identity`, `dedup`, `report` |
| Database | **PostgreSQL 16** (runs, claims, verdicts, overrides, audit, config) |
| OCR | **Tesseract + OpenCV** (local, free, arm64-compatible) |
| Worker | Background Python process — polls DB for queued runs, executes pipeline |
| Frontend | **React + Vite + TypeScript + Tailwind CSS** (SPA served by FastAPI) |
| Deployment | **Docker Compose** on a Raspberry Pi 5, exposed via **Cloudflare Tunnel** |
| Cost | Zero recurring — all open-source / self-hosted |

---

## Repository layout

```
flight-perdiem/
├── backend/
│   ├── perdiem/
│   │   ├── engine/        # pure library: ingest, drive, ocr/{preprocess,extract,redbox,doctype}, rules, pairing, identity, dedup, report
│   │   ├── web/           # FastAPI: main.py, auth.py, deps.py, schemas.py, routes/
│   │   ├── worker/        # background job runner: runner.py
│   │   ├── db/            # SQLAlchemy models, session, repository, Alembic migrations/
│   │   └── config.py      # env-driven settings
│   ├── ml/                # Roster Intelligence (EP-ML) — pure data prep / training, NOT in engine
│   │   ├── dataset/       # PD-ML-002: readers, normalise, join, build, quality_report
│   │   ├── eval/          # PD-ML-003: metrics, scorers, e2e, baseline runner
│   │   ├── triage/        # PD-ML-004: features, train (numpy logreg), calibrate
│   │   └── doctype/       # PD-ML-005: augment, train (image features → numpy logreg)
│   ├── tests/             # engine + ML unit + DB integration tests
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/         # LoginPage, RunPage, ResultsPage, ExceptionsPage, ConfigPage, AuditPage
│       ├── components/    # ProgressBar, VerdictBadge, RosterPreview, DecisionControls
│       ├── hooks/         # usePolling
│       ├── contexts/      # AuthContext
│       └── lib/           # apiClient.ts
├── docker/
│   └── entrypoint.sh      # migrate then serve (api container)
├── scripts/
│   ├── auth_drive.py          # one-time Google Drive auth setup
│   ├── build_ml_dataset.py    # PD-ML-002: build the labelled dataset from the 3 workbooks
│   ├── eval_ml.py             # PD-ML-003: score a backend on the held-out split (baseline)
│   ├── train_triage.py        # PD-ML-004: train the triage + reason classifier
│   ├── train_doctype.py       # PD-ML-005: train the doc-type / quality classifier
│   └── deploy.sh              # build + restart + health check
├── docs/
│   ├── REQUIREMENTS.md
│   ├── flows/             # as-is / to-be / ML build flows (mermaid)
│   ├── analysis/          # API readiness analysis, gap tracking
│   ├── architecture/      # system architecture, ER diagram
│   └── features/          # epics and stories (incl. RosterIntelligence / EP-ML)
├── Dockerfile             # multi-stage: node SPA build → python runtime
├── docker-compose.yml     # api + worker + db
└── .env.example           # env template — copy to .env and fill in values
```

---

## API

The FastAPI backend is self-documenting:

| URL | Description |
|---|---|
| `/api/docs` | Interactive Swagger UI |
| `/api/docs-json` | Raw OpenAPI JSON — import into Postman |
| `/api/health` | Health probe (no auth) |

All other endpoints require an httpOnly JWT cookie set by `POST /api/auth/login`.

<details>
<summary>Full route list</summary>

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/auth/login` | Issue session token (password-only) |
| `POST` | `/api/auth/logout` | Clear session |
| `GET` | `/api/auth/me` | Current user |
| `POST` | `/api/runs` | Start a pipeline run (multipart: month + two xlsx files) |
| `GET` | `/api/runs` | Run history |
| `GET` | `/api/runs/{id}` | Run status + stage + progress counts |
| `GET` | `/api/runs/{id}/results` | Per-crew aggregated payable results |
| `GET` | `/api/runs/{id}/report` | Download master xlsx |
| `GET` | `/api/runs/{id}/exceptions` | Flagged claims (NEEDS_REVIEW / INVALID) |
| `GET` | `/api/runs/{id}/exceptions/export` | Download exception xlsx |
| `POST` | `/api/claims/{id}/decision` | Approve / reject / correct a flagged claim |
| `GET` | `/api/rosters/{file_id}` | Serve cached roster image (auth-gated, PII) |
| `GET` | `/api/config` | Current rules config (flight numbers, rate, thresholds) |
| `PUT` | `/api/config` | Update rules config (audited) |
| `GET` | `/api/audit` | Audit trail — filterable by run, claim, action |

</details>

---

## Running locally (dev)

**Prerequisites:** Python 3.12, Node 20, pnpm, Docker. `make help` lists every
command.

```bash
# 1. Create .env, then fill in the values (ADMIN_PASSWORD, JWT_SECRET,
#    POSTGRES_PASSWORD, DB_ADMIN_USER, DB_ADMIN_PASSWORD)
make setup

# 2. Install backend venv (backend/.venv) + frontend node_modules
make install            # = make backend-install + make frontend-install

# 3. Start Postgres, initialise the perdiem role + database, then migrate
docker compose up -d db          # starts Postgres on 127.0.0.1:5432
docker compose up db-init        # one-shot: creates role + DB (safe to re-run)
make backend-migrate             # runs Alembic migrations
```

Then run the three dev processes, each in its own terminal:

```bash
make backend-dev        # terminal 1 — FastAPI on :8000 (reload)
make worker-dev         # terminal 2 — pipeline worker (processes PENDING runs)
make frontend-dev       # terminal 3 — Vite on :5173 (proxies /api → :8000)
```

Open `http://localhost:5173` (Vite dev) or `http://localhost:8000` (full stack).
Swagger UI at `http://localhost:8000/api/docs`.

> To run the full stack in Docker instead, use `make up`
> (see [Docker](#deploying-on-raspberry-pi-5)).

### Tests

```bash
make test               # run the test suite (engine + ML + DB)
make test-all           # same suite, verbose
make lint               # ruff
```

The DB integration tests use testcontainers and **skip automatically when Docker
isn't available** — so the engine + ML tests still run anywhere. To execute the DB
tests too, have Docker running. Target one suite directly with
`cd backend && ../.venv/bin/pytest tests/ml/ -v` (`tests/engine/`, `tests/ml/`,
`tests/db/`).

---

## Machine learning — Roster Intelligence (EP-ML)

A parallel epic that improves the pipeline's weak point — **roster extraction +
claim triage** — by learning from years of admin-validated history in the three
workbooks (on-time form, back-claim form, CCD master report). It adds **no new
rules**: ML improves the *inputs* and *routing* that feed R1–R8, so auditability
(N1) and idempotency (N2) are preserved. See the build + runtime
[ML flow](docs/flows/ml-flow.md) and the [epic overview](docs/features/RosterIntelligence/overview.md).

> **This is independent of the web app.** The api/worker/frontend never import `ml/`
> or read its output, so `make ml-dataset` is **not** a startup step — run it only when
> you want to (re)build the ML dataset. Running the app needs just the steps in
> [Running locally (dev)](#running-locally-dev).

### Build the labelled dataset (PD-ML-002) — runs locally, no DB

The first ML build assembles a versioned dataset from the three workbooks. It is a
**local batch job** (CPU-only, no DB, no network) and its output is **PII** — it stays
under the gitignored `data/ml/`.

```bash
# From the repo root — reads docs/example-files/, writes data/ml/datasets/<version>/
make ml-dataset

# Name the version explicitly (default: today's date)
make ml-dataset ARGS="--version 2026-05"

# Also build the vision split from a populated roster cache
make ml-dataset ARGS="--version 2026-05 --roster-cache data/cache"
```

Equivalent without `make`:

```bash
backend/.venv/bin/python scripts/build_ml_dataset.py --version 2026-05
backend/.venv/bin/python scripts/build_ml_dataset.py --help   # all flags
```

Output (`data/ml/datasets/<version>/`):

| File | Contents |
|---|---|
| `text.jsonl` | Decision rows (all history, no image) — the abundant label tier |
| `vision.jsonl` | Rows whose roster image resolves to a cached file (empty until the cache is populated) |
| `manifest.json` | Source SHA-256 hashes, row counts, labelling-rule version, rate |
| `quality_report.md` | Auditable rows-per-sheet, disposition distribution, unmatched joins |

Config (optional, via `.env`): `CCD_MASTER_PATH`, `ML_DATASET_DIR`, `DATASET_VERSION`,
`RATE_THB_PER_DAY` (default 400). Defaults point at `docs/example-files/`.

### Eval harness + baseline (PD-ML-003)

Scores any decision/extraction backend on the **crew-held-out `test` split** and writes
a re-runnable report under `ML_REPORT_DIR`. The baseline (`review_all`) is the manual
status quo — review everything — so a model's value is how much review queue it safely
removes. Numbers are recorded in [docs/analysis/ml-baseline.md](docs/analysis/ml-baseline.md).

```bash
backend/.venv/bin/python scripts/eval_ml.py --dataset-version dev --split test
```

### Triage + reason classifier (PD-ML-004)

A numpy logistic-regression model (no heavy deps) that routes claims
(`AUTO_PASS / AUTO_REJECT / SEND_TO_REVIEW`) and predicts a rejection-reason hint. Pure
inference lives in `perdiem/engine/triage.py` and falls back to rules-only when disabled
or the artifact is missing. Trained off-Pi; **ships disabled** (`TRIAGE_ENABLED=false`)
and advisory until richer (rule-output) features are wired in via PD-ML-007.

```bash
make ml-train-triage ARGS="--dataset-version dev"   # → data/ml/models/triage.json
# or directly:
backend/.venv/bin/python scripts/train_triage.py --dataset-version dev
backend/.venv/bin/python scripts/eval_ml.py --dataset-version dev --triage-model data/ml/models/triage.json
```

### Doc-type / quality classifier (PD-ML-005)

A cheap pre-extraction gate that answers one question before Tesseract runs: *is this
attachment actually a readable crew schedule report?* Wrong documents and unreadable
photos are routed to `NEEDS_REVIEW` immediately, saving OCR time and preventing fabricated
fields from misfiring the eligibility rules.

Three outcome labels: `VALID_ROSTER` (proceed to Tesseract) · `NOT_A_ROSTER` (wrong
document) · `UNREADABLE` (corrupt, blank, or too degraded). The classifier is a numpy
softmax over 11 hand-crafted image features (aspect ratio, edge density, blue header band
presence, brightness statistics, …) — no ONNX or GPU needed, Pi-friendly.

Unlike the triage model, **no dataset build step is needed**: the training script reads
labelled images directly from `docs/example-files/roster-attached-files/` and synthesises
`UNREADABLE` examples via extreme augmentation.

```bash
# Train from fixture images → data/ml/models/doctype.json
make ml-train-doctype

# Options
make ml-train-doctype ARGS="--augment 20 --val-split 0.25"

# Enable in the worker (after validating the model)
# Add to .env:
DOCTYPE_ENABLED=true
```

The trained JSON artifact is consumed by `perdiem/engine/ocr/doctype.py` (pure numpy, no
training deps). The worker passes the config to `extract_roster()` as a pre-extraction
gate; when disabled or the artifact is missing, the pipeline falls back to Tesseract
extraction unchanged.

> **Status:** PD-ML-002/003/004/005 are built. **006 (Donut reader) and 007 (runtime
> wiring)** are not yet implemented — see the [ML flow](docs/flows/ml-flow.md) for how
> they plug in later.

---

## Deploying on Raspberry Pi 5

### First-time setup

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 2. Clone the repo
git clone <repo-url> ~/flight-perdiem && cd ~/flight-perdiem

# 3. One-time Google Drive auth (opens a browser — log in as kantaphajasuwan@airasia.com)
python scripts/auth_drive.py

# 4. Configure environment
cp .env.example .env
# Required values in .env:
#   ADMIN_PASSWORD=<strong-password>
#   JWT_SECRET=<run: python -c "import secrets; print(secrets.token_hex(32))">
#   POSTGRES_PASSWORD=<strong-db-password-for-the-perdiem-role>
#   DB_ADMIN_USER=postgres          # Postgres superuser (default: postgres)
#   DB_ADMIN_PASSWORD=<strong-admin-db-password>

# 5. Build and start
./scripts/deploy.sh
```

The app is reachable at `http://localhost:8000`. Migrations run automatically on
every deploy via the `docker/entrypoint.sh` startup script.

### Expose via Cloudflare Tunnel (no open ports)

In the Cloudflare dashboard, on the Pi's existing tunnel → **Public hostnames** →
**Add a public hostname**:

| Field | Value |
|---|---|
| Subdomain | `perdiem` |
| Domain | your domain |
| Service | `HTTP` → `localhost:8000` |

Save. The app is immediately accessible at `https://perdiem.yourdomain.com` over
HTTPS with no nginx, no new tunnel, no open ports to the LAN.

Optionally enable **Cloudflare Access** in front for an extra auth layer.

### Subsequent deploys

```bash
cd ~/flight-perdiem && git pull && ./scripts/deploy.sh
# Tail logs: ./scripts/deploy.sh --logs
```

### Useful commands

```bash
docker compose logs -f api worker                          # live logs
docker compose exec api bash                               # shell in api container
docker compose exec db psql -U perdiem -d perdiem          # database shell (perdiem role)

# Manual migration (normally runs automatically on api start)
docker compose run --rm api sh -c "cd /app/backend && alembic upgrade head"
```

---

## Per diem eligibility rules (summary)

| Rule | Description |
|---|---|
| R1 | Route must be **DMK↔HKT** only |
| R2 | Flight number must be in the **monthly-rotating configurable set** |
| R3 | Outbound DMK→HKT on day N must pair with return HKT→DMK on day N+1 |
| R4 | Roster **generated date** must be ≥ the claimed date (proof of flown duty) |
| R5 | Roster **staff ID** must match form Employee Code (exact) |
| R5a | Roster **name** matched fuzzily — handles initials, spacing, case |
| R6 | Roster date range must cover all claimed days |
| R7 | Each `(staff_id, date)` counted once — de-duplicated across all submissions |
| R8 | Claims for a prior month routed as **back-claims** with Thai remark |

Rate: **400 THB / payable day** (configurable via the Config screen).

---

## Documentation

| Doc | Purpose |
|---|---|
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Full functional spec, rules R1–R8, data sources |
| [docs/architecture/architecture.md](docs/architecture/architecture.md) | System architecture and container diagram |
| [docs/architecture/ER-diagram.md](docs/architecture/ER-diagram.md) | Database ER diagram (6 tables) |
| [docs/flows/system-flow.md](docs/flows/system-flow.md) | To-be automated validation pipeline (mermaid) |
| [docs/flows/ml-flow.md](docs/flows/ml-flow.md) | Roster Intelligence (EP-ML) build + runtime flow, per story |
| [docs/features/RosterIntelligence/overview.md](docs/features/RosterIntelligence/overview.md) | ML epic — stories, two-track build order, decision gate |
| [docs/features/implementation-order.md](docs/features/implementation-order.md) | Story implementation sequence |
| [docs/analysis/webapp-api-readiness.md](docs/analysis/webapp-api-readiness.md) | API gap analysis and auth decision log |
| [docs/example-files/](docs/example-files/) | Real form responses + roster images (test fixtures) |
