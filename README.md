# flight-perdiem

Automated validation of cabin-crew **per diem (sector allowance)** claims for
AirAsia (DMK base). Cabin crew submit claims via Google Forms and attach their
crew schedule report (roster); this system reads those submissions, OCRs the
rosters, validates each claimed day against the per diem rules, de-duplicates
across submissions, and produces the payable master report — replacing a slow,
fully manual review.

> **Status:** 📐 Design/docs phase. The specification, flows, architecture, and a
> story-level implementation plan are complete; application code is not built yet.

---

## The problem

Per diem is reconciled one month in arrears (working in March → claiming
February). Today an admin opens every Google Form response, reads the attached
roster by eye, checks the route/dates, de-duplicates resubmissions from memory,
and types the result into a master spreadsheet. It doesn't scale and is
error-prone. See [docs/flows/current-flow.md](docs/flows/current-flow.md).

## What the system does

`ingest → retrieve rosters → OCR → validate → de-duplicate → report`, operated
from a web app where staff pick a month, run the pipeline, review flagged claims,
and download the report. See [docs/flows/system-flow.md](docs/flows/system-flow.md).

### Core rules (summary)

- **Route:** only **DMK→HKT** (out) and **HKT→DMK** (return) qualify.
- **Flight numbers:** must be in a **configurable, monthly-rotating** set
  (out: `FD3013/3015`; return: `FD3026/3006/3038/3084`).
- **Pairing:** an outbound on day _N_ pairs with a return on day _N+1_ = **2
  payable days**.
- **Proof:** the roster's *generated date* must support the claimed dates.
- **Identity:** roster must match the submitter — **staff ID** is authoritative;
  names are matched fuzzily (e.g. `Lucksnara S.` ↔ `Lucksnara Sothiratviroj`).
- **De-duplication:** each unique `(staff ID, date)` is counted once across all
  submissions. Rate observed: **400 THB/day**.

Full rules and data sources: [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).

## Tech stack

| Layer | Choice |
| ----- | ------ |
| Frontend | React + Vite + pnpm + **Tailwind CSS** (SPA) |
| Backend | Python + **FastAPI** (serves the SPA **and** the REST API) |
| OCR | **Tesseract + OpenCV** (local, free) |
| Database | **PostgreSQL** |
| Jobs | background **worker** for the long pipeline |
| Deployment | **Docker** compose on a **Raspberry Pi 5**, exposed via the Pi's existing **Cloudflare Tunnel** (no nginx, no open ports) |
| Cost | zero recurring — all open-source / free-tier |

Details: [docs/architecture/architecture.md](docs/architecture/architecture.md).

## Documentation

| Doc | Purpose |
| --- | ------- |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Functional/non-functional requirements, data sources, rules R1–R8 |
| [docs/flows/current-flow.md](docs/flows/current-flow.md) | Today's manual process (as-is) |
| [docs/flows/system-flow.md](docs/flows/system-flow.md) | Target automated pipeline (to-be) |
| [docs/architecture/architecture.md](docs/architecture/architecture.md) | System architecture, containers, schema |
| [docs/plans/implementation-plan.md](docs/plans/implementation-plan.md) | Phased build plan (Phases 0–10) |
| [docs/features/](docs/features/) | Epics & stories (the work, broken down) |
| [docs/features/implementation-order.md](docs/features/implementation-order.md) | The order to build the stories in |
| [docs/example-files/](docs/example-files/) | Real sample forms + roster used as fixtures |

### Features (epics → stories)

| Epic | Scope |
| ---- | ----- |
| [Ingestion](docs/features/Ingestion/overview.md) | Read both Google Form workbooks; download rosters from Drive |
| [RosterOCR](docs/features/RosterOCR/overview.md) | Extract fields/flight grid; detect the red claim box |
| [Validation](docs/features/Validation/overview.md) | Rules engine, name matching, out-and-back pairing |
| [Reporting](docs/features/Reporting/overview.md) | De-duplicate, aggregate, write master + exception reports |
| [WebApp](docs/features/WebApp/overview.md) | Auth, run orchestration, review UI, config/audit, download |
| [Platform](docs/features/Platform/overview.md) | PostgreSQL schema; Docker + Cloudflare deployment |

## Repository layout (target)

```
flight-perdiem/
├── backend/            # Python + FastAPI engine, web API, worker, db
├── frontend/           # React + Vite + pnpm + Tailwind SPA
├── docker-compose.yml  # api + worker + db (Pi 5, arm64)
├── .env.example
├── secrets/            # google-credentials.json (gitignored)
└── docs/               # requirements, flows, architecture, plans, features
```

> Only `docs/` exists today; `backend/` and `frontend/` are created during
> implementation (see the plan and implementation-order).

## Build order

Build the pure engine first, then persistence, then the web app, then deploy. The
sequenced story list (with dependency graph and decision gates) is in
[docs/features/implementation-order.md](docs/features/implementation-order.md).

## Open decisions

A few choices should be settled before the stories they block (tracked in
REQUIREMENTS §9 and the relevant stories):

- **Generated-date rule (R4)** direction — blocks the validation rules engine.
- **Prisma vs Alembic/SQLAlchemy** for DB migrations — blocks the schema story.
- Red-box vs form day-list as the primary source of claimed days.
- Flat 400 THB/day vs rank/route-dependent rate.
- Auth mechanism (Google-restricted vs shared secret).
