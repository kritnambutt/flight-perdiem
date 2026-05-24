# Project Structure Rules

Standardised folder structure for the flight-perdiem project. Only `docs/` exists
today; `backend/` and `frontend/` are created during implementation.

## Root Structure

```
flight-perdiem/
├── backend/             # Python + FastAPI engine, web API, worker, db
├── frontend/            # React + Vite + pnpm + Tailwind SPA
├── docs/                # Requirements, flows, architecture, plans, features
├── docker-compose.yml   # api + worker + db (Pi 5, arm64)
├── .env.example         # env template (DATABASE_URL, POSTGRES_PASSWORD, secrets path)
├── secrets/             # google-credentials.json (gitignored, chmod 600)
└── .claude/             # Claude Code config (rules, skills, agents, hooks)
```

> No `nginx` and no `cloudflared` container: FastAPI serves the SPA + API on one
> origin, and the Pi's existing Cloudflare Tunnel routes a hostname to
> `localhost:8000`. See `docs/architecture/architecture.md`.

## Backend Structure

```
backend/
├── perdiem/
│   ├── engine/          # PURE library — no web/db coupling
│   │   ├── ingest.py            # read form responses -> Claim (F1, F2)
│   │   ├── drive.py             # download roster attachments (F3)
│   │   ├── ocr/                 # preprocess.py, extract.py, redbox.py (F4–F6)
│   │   ├── rules.py             # eligibility rules R1–R8 + validate_claim (F7)
│   │   ├── pairing.py           # out-and-back pairing (R3, F8)
│   │   ├── identity.py          # staff-id + fuzzy name matching (R5, R5a)
│   │   ├── dedup.py             # de-dup + aggregate (R7, F9, F10)
│   │   ├── report.py            # master + exception output (F11, F12)
│   │   └── models.py            # engine dataclasses (Claim, Verdict, …)
│   ├── web/             # FastAPI app layer (main.py, deps.py, auth.py, routes/, schemas.py)
│   ├── worker/          # background job runner (runner.py)
│   ├── db/              # SQLAlchemy models, session, migrations/
│   └── config.py        # env-driven settings (paths, thresholds, Google creds)
├── tests/               # pytest — engine unit tests + API tests; fixtures/ from docs/example-files
├── requirements.txt     # (or pyproject.toml) pinned deps
└── Dockerfile           # multi-stage: node builds SPA -> python serves dist/
```

## Frontend Structure

```
frontend/
├── src/
│   ├── pages/           # RunPage, ResultsPage, ExceptionsPage, ConfigPage, AuditPage, LoginPage
│   ├── components/      # reusable UI (RosterPreview, ProgressBar, VerdictBadge, …)
│   ├── hooks/           # useRun, usePolling, useAuth
│   ├── contexts/        # AuthContext
│   ├── lib/             # API client, fetch wrapper, helpers
│   ├── config/  types/  styles/   # config, TS types, global styles + Tailwind directives
│   ├── App.tsx          # router + layout
│   └── main.tsx         # Vite entrypoint
├── index.html  vite.config.ts  tailwind.config.ts  postcss.config.js
└── package.json  pnpm-lock.yaml
```

## Documentation Structure

```
docs/
├── REQUIREMENTS.md      # living requirements (rules R1–R8, data sources)
├── flows/               # current-flow.md (as-is), system-flow.md (to-be)
├── architecture/        # architecture.md
├── plans/               # implementation-plan.md (Phases 0–10)
├── features/            # epics & stories + implementation-order.md
└── example-files/       # real sample forms + roster (test fixtures)
```

## Conventions

- **File naming:** Python files `snake_case.py`; React components `PascalCase.tsx`;
  TS utilities `camelCase.ts`; dirs kebab-case (frontend) / snake_case (python pkg).
- **Engine purity:** `perdiem/engine/` must not import web or db code — it is
  unit-tested in isolation against `docs/example-files` fixtures.
- **API:** REST, kebab-case URLs (`/api/runs`), proper HTTP methods/status; FastAPI
  auto-docs (OpenAPI) on routes.
- **Environment:** keep secrets out of source control; commit `.env.example`; never
  commit `.env*` or `secrets/`.
- **Tests:** engine unit tests need no DB; API/integration tests use a disposable Postgres.
