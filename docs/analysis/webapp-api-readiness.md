# WebApp API Readiness Analysis

**Date:** 2026-05-24  
**Scope:** All five EP-WEB stories (PD-WEB-001 through PD-WEB-005) examined
against what is needed to begin implementation, with specific attention to:
- Complete REST route inventory
- Swagger UI at `/api/docs` and raw spec at `/api/docs-json`
- Frontend ↔ API alignment
- Gaps and open decisions that must be resolved before coding starts

---

## 1. Current Implementation State

| Layer | Status |
|-------|--------|
| `backend/perdiem/engine/` | **Complete** — ingest, drive, OCR, rules, pairing, identity, dedup, report |
| `backend/perdiem/db/` | **Complete** — ORM models, Alembic migration, repository, 20 integration tests |
| `backend/perdiem/web/` | **Missing** — no FastAPI app, no routes, no auth, no worker |
| `backend/perdiem/worker/` | **Missing** |
| `frontend/` | **Missing** — React/Vite/Tailwind scaffold not yet created |

The engine (Milestone 1) and DB layer (Milestone 2) are done. The WebApp stories
(Milestone 3) are next; nothing in `web/` or `worker/` has been created yet.

---

## 2. Complete API Route Inventory

Every route implied by the five stories, consolidated and annotated.

### 2.1 Auth — `PD-WEB-002`

| Method | Path | Auth required | Purpose |
|--------|------|:---:|---------|
| `POST` | `/api/auth/login` | No | Issue session / token |
| `POST` | `/api/auth/logout` | Yes | Revoke session / clear cookie |
| `GET`  | `/api/auth/me` | Yes | Return current user or `401` |

> **Not in any story but referenced:** `GET /api/health` — the auth story says
> "except login/health" but no health endpoint is specified. Should be added
> explicitly (see §4 Gaps).

### 2.2 Runs & jobs — `PD-WEB-001`

| Method | Path | Auth required | Purpose |
|--------|------|:---:|---------|
| `POST` | `/api/runs` | Yes | Multipart upload: `month`, `posting_base` (`.xlsx`), `late_submission` (`.xlsx`); returns `{ run_id }` |
| `GET`  | `/api/runs` | Yes | Recent run history |
| `GET`  | `/api/runs/{id}` | Yes | Status, stage, counts, timestamps |

**Multipart body for `POST /api/runs`:**
```
Content-Type: multipart/form-data
Fields:
  month           string   "FEBRUARY 2026"
  posting_base    file     .xlsx
  late_submission file     .xlsx
```

**Response shape for `GET /api/runs/{id}`:**
```json
{
  "id": "uuid",
  "cycle_month": "FEBRUARY 2026",
  "status": "queued|parsing|downloading|ocr|validating|aggregating|done|error",
  "stage": "downloading",
  "counts": { "processed": 12, "valid": 10, "review": 1, "reject": 1 },
  "started_at": "2026-05-24T09:01:00+07:00",
  "finished_at": null
}
```

> **Note:** The DB model uses `PENDING | RUNNING | DONE | FAILED` as status values,
> but the story lists `queued → parsing → downloading → ocr → validating →
> aggregating → done | error`. The API schema should map/extend the DB status
> to include the fine-grained stage values (see Gap G-03).

### 2.3 Results & exception review — `PD-WEB-003`

| Method | Path | Auth required | Purpose |
|--------|------|:---:|---------|
| `GET`  | `/api/runs/{id}/results` | Yes | `CrewResult[]` — per-crew validated summary |
| `GET`  | `/api/runs/{id}/exceptions` | Yes | Flagged claims with rule, reason, confidence, roster ref |
| `GET`  | `/api/rosters/{file_id}` | Yes | Roster image bytes — **PII, auth-gated** |
| `POST` | `/api/claims/{id}/decision` | Yes | Approve / reject / correct; triggers re-aggregation |

**`POST /api/claims/{id}/decision` body:**
```json
{
  "decision": "APPROVE|REJECT",
  "note": "optional free text",
  "corrected_days": [3, 4]
}
```

**`GET /api/runs/{id}/results` response shape:**
```json
[
  {
    "staff_id": "1043862",
    "name": "Kanatsanan Wichitthararak",
    "email": "...",
    "period": "1 February 2026 - 2 February 2026",
    "days": 2,
    "total_thb": 800,
    "remark": null
  }
]
```

**`GET /api/runs/{id}/exceptions` response shape:**
```json
[
  {
    "claim_id": "uuid",
    "staff_id": "1043862",
    "name": "...",
    "claimed_date": "2026-02-03",
    "verdict": "NEEDS_REVIEW",
    "rule": "R5a",
    "reason": "Name mismatch — form: 'Lucksnara S.', roster: 'Lucksnara Sothiratviroj'",
    "confidence": 0.72,
    "roster_file_id": "abc123",
    "extracted": { ... }
  }
]
```

### 2.4 Config & audit — `PD-WEB-004`

| Method | Path | Auth required | Purpose |
|--------|------|:---:|---------|
| `GET`  | `/api/config` | Yes | Current config values |
| `PUT`  | `/api/config` | Yes | Update config (audited); validated before save |
| `GET`  | `/api/audit`  | Yes | Audit entries; filterable via query params `?run_id=&claim_id=&rule=` |

**`GET /api/config` response shape:**
```json
{
  "outbound_flights": ["FD3013", "FD3015"],
  "return_flights": ["FD3026", "FD3006", "FD3038", "FD3084"],
  "rate_thb_per_day": 400,
  "name_match_threshold": 0.8,
  "ocr_confidence_threshold": 0.7
}
```

### 2.5 Reports & downloads — `PD-WEB-005`

| Method | Path | Auth required | Purpose |
|--------|------|:---:|---------|
| `GET`  | `/api/runs/{id}/report` | Yes | Stream master `.xlsx` as `Content-Disposition: attachment` |
| `GET`  | `/api/runs/{id}/exceptions/export` | Yes | Stream exception report as `Content-Disposition: attachment` |

---

## 3. Swagger UI & OpenAPI Spec Configuration

### 3.1 Required URL behaviour

| URL | Expected behaviour |
|-----|--------------------|
| `/api/docs` | Interactive Swagger UI |
| `/api/docs-json` | Raw OpenAPI JSON spec (importable into Postman) |

### 3.2 FastAPI defaults vs required paths

FastAPI by default mounts its docs at `/docs` and `/openapi.json`.
Because the API is served on the **same origin** as the SPA under a `/api` prefix,
the docs must be explicitly relocated. Configure the `FastAPI()` app as:

```python
app = FastAPI(
    title="Per Diem Validation API",
    version="1.0.0",
    docs_url="/api/docs",         # Swagger UI
    redoc_url="/api/redoc",       # ReDoc (optional)
    openapi_url="/api/docs-json", # raw spec for Postman import
)
```

This is a **one-line change** from the default — but it must be done at app
creation, not added as a route. The worker does **not** run a FastAPI instance;
only the `api` container needs this.

### 3.3 Postman import

After setting `openapi_url="/api/docs-json"`, Postman can import the collection via:

1. **Postman → Import → Link:** paste `http://<pi-host>:8000/api/docs-json`
2. **Or: download the JSON** from that URL and import as a file.

All FastAPI routes decorated with `@router.<method>` are automatically included.
Add `tags=["runs"]`, `summary=`, and `response_model=` to every route for clean
Postman collection grouping.

### 3.4 Auth in Swagger UI

Because all protected routes require a session/token, add a security scheme so
the Swagger UI can send credentials. The recommended approach (httpOnly cookie)
is transparent to Swagger UI — add a Bearer token fallback for tooling:

```python
from fastapi.security import HTTPBearer

security = HTTPBearer(auto_error=False)
```

Then inject the `current_user` dependency on all protected routes.
In Swagger UI, use **Authorize → Bearer token** for testing.

### 3.5 Required FastAPI app structure

```
backend/perdiem/web/
├── main.py          # FastAPI() with docs_url="/api/docs", openapi_url="/api/docs-json"
├── deps.py          # get_current_user dependency (raises 401 if unauthenticated)
├── auth.py          # login/logout/me + session logic
├── schemas.py       # Pydantic request/response models (shared)
└── routes/
    ├── runs.py      # POST /api/runs, GET /api/runs, GET /api/runs/{id}
    ├── claims.py    # POST /api/claims/{id}/decision
    ├── results.py   # GET /api/runs/{id}/results
    ├── exceptions.py# GET /api/runs/{id}/exceptions, GET /api/runs/{id}/exceptions/export
    ├── rosters.py   # GET /api/rosters/{file_id}
    ├── reports.py   # GET /api/runs/{id}/report
    ├── config.py    # GET/PUT /api/config
    └── audit.py     # GET /api/audit
```

---

## 4. Gaps & Issues Found in the Stories

These must be resolved before or during implementation.

### G-01 — Health endpoint is referenced but not specified

**Story:** PD-WEB-002 says "all API routes except login/health" must require auth.
**Gap:** No story defines `GET /api/health`.
**Impact:** Monitoring, Docker `healthcheck:`, and Cloudflare health probes need this.
**Resolution:** Add `GET /api/health → { status: "ok" }` to PD-WEB-001 or create
a minimal infrastructure story. No auth required on this endpoint.

---

### G-02 — Roster image `file_id` is ambiguous

**Story:** PD-WEB-003 specifies `GET /api/rosters/{file_id}`.
**Gap:** It is unclear whether `file_id` is:
  - The Google Drive file ID (from the roster URL), or
  - An internal UUID/identifier stored in the `claims.roster_refs` JSONB field.

Using the Drive ID directly in the API URL exposes an internal identifier and
creates coupling to Google Drive URLs in the frontend.
**Resolution:** Store rosters in the **local cache volume** by Drive file ID;
the API serves from cache. The `file_id` in the URL should be the Drive file ID
(already stored in `claims.roster_refs`), which is safe to expose since it
requires auth to retrieve. Document this decision in PD-WEB-003.

---

### G-03 — DB status values don't match story stage values

**Story:** PD-WEB-001 specifies stages: `queued → parsing → downloading → ocr →
validating → aggregating → done | error`.
**DB model:** `runs.status` is `PENDING | RUNNING | DONE | FAILED`.
**Gap:** The DB only stores a coarse `status`; fine-grained stages require either
a separate `stage` column or encoding the stage inside the `progress` JSONB/integer.
**Resolution (recommended):** Add a `stage VARCHAR(20)` column to `runs` in a new
Alembic migration (`002_add_stage_to_runs.py`). The worker writes both `status`
and `stage`. The API response includes both. This is a **schema change** — do it
before the web layer is written.

---

### G-04 — Re-aggregation after decision: no explicit trigger

**Story:** PD-WEB-003 says `POST /api/claims/{id}/decision` "triggers
re-aggregation". It is not specified whether re-aggregation is:
  - **Synchronous** in the request handler (simple, but could be slow for large runs), or
  - **Asynchronous** via a worker task (better for Pi, but adds complexity).

**Resolution:** Given this is a batch tool on a Pi with one validator at a time,
synchronous re-aggregation within the request is acceptable for the MVP.
Specify this in PD-WEB-003's technical docs. The decision endpoint should return
the updated `CrewResult` for the affected crew member so the UI can update immediately.

---

### G-05 — Pagination not specified on any list endpoint

**Story:** No story mentions pagination on:
  - `GET /api/runs` (run history)
  - `GET /api/runs/{id}/results` (crew results)
  - `GET /api/runs/{id}/exceptions` (exception queue)
  - `GET /api/audit` (audit log)

**Gap:** Without pagination, a large month (e.g. 200 crew) sends a huge payload.
**Resolution (recommended for MVP):** Add optional `?limit=&offset=` query params
with a sensible default (e.g. `limit=100`) on all list endpoints. FastAPI makes
this trivial. Document in each story.

---

### G-06 — Auth mechanism ✅ RESOLVED

**Decision:** Password-only authentication. A single shared admin password is read
from the `ADMIN_PASSWORD` environment variable at startup. There is no username
field — the login form accepts only a password.

**Implementation spec for PD-WEB-002:**

```
POST /api/auth/login   body: { "password": "..." }
```

- At startup, `web/auth.py` reads `ADMIN_PASSWORD` from env (via `perdiem/config.py`
  → `Settings`). The value is **never hard-coded**.
- The submitted password is compared using **`bcrypt.checkpw`** (constant-time).
  The env var holds the **plaintext** strong password; bcrypt hashing happens at
  compare-time (no pre-hash stored — suitable for a single-admin system where the
  env var is already a secret).
- On success: issue a **signed JWT** (or a server-side session) stored as an
  `httpOnly` cookie. Token lifetime: configurable, default 8 hours.
- On failure: `401 Incorrect password` with a 1-second artificial delay
  (brute-force mitigation).
- Logout: `POST /api/auth/logout` clears the cookie / invalidates the token.

**Configuration (`perdiem/config.py` `Settings` class):**
```python
admin_password: str = Field(..., env="ADMIN_PASSWORD")
```

**`.env.example` (committed — no secret value):**
```
ADMIN_PASSWORD=   # set to a strong random string; never commit the actual value
```

**`.env` (gitignored — holds the real value):**
```
ADMIN_PASSWORD=<strong-password-here>
```

The password value itself is never committed to source control, never logged, and
never appears in any config table or audit row.

---

### G-07 — `corrected_days` in decision endpoint not validated against rules

**Story:** `POST /api/claims/{id}/decision` accepts `corrected_days` to adjust
claimed days. It is unspecified whether the corrected days are re-validated
through the rules engine or simply accepted as-is.
**Impact:** Accepting unchecked days could create inconsistent verdicts (e.g.
approving a day that fails R1).
**Resolution:** Specify in PD-WEB-003 that corrected days are **re-validated
through R1–R8** before being stored. The decision endpoint re-runs `validate_claim`
with the corrected day list. The override stores the admin's final decision but
the verdict row is updated to reflect the corrected-and-re-validated outcome.

---

### G-08 — SPA static file serving not in any WebApp story

**Objective:** FastAPI serves the built React SPA `dist/` at the root (`/`) in
addition to the REST API under `/api/`.
**Gap:** No story specifies how `main.py` mounts the SPA static files (the pattern
is `app.mount("/", StaticFiles(directory="dist", html=True))`). This must be
correct or `/api/docs` will be unreachable.
**Caution:** The `StaticFiles` mount **must be added last**, after all `/api/`
routes are registered. If it is added first, the `html=True` catchall will
intercept `/api/docs` requests in some FastAPI versions.
**Resolution:** Document the mount order in `main.py`. Add an integration test
that verifies `GET /api/docs` returns `200` with `text/html` content type.

---

### G-09 — No spec for the worker process interface

**Story:** PD-WEB-001 describes the worker conceptually but does not specify:
  - How the worker is started (Docker `command:` in compose)
  - How the API and worker share state (only via DB — this is correct per standards)
  - What happens if the worker dies mid-run (mark `FAILED` on startup if `RUNNING` runs exist)

**Resolution:** Add a startup handler in `runner.py` that on boot queries for any
`RUNNING` runs and marks them `FAILED` with `reason="worker restarted"`. Document
this in PD-WEB-001 implementation plan step 6.

---

### G-10 — `/api/runs/{id}/exceptions/export` conflicts with PD-WEB-003's route

**Story PD-WEB-003:** `GET /api/runs/{id}/exceptions` returns the JSON exception list.
**Story PD-WEB-005:** `GET /api/runs/{id}/exceptions/export` streams the `.xlsx`.

These two routes are consistent — the first returns JSON for the UI, the second
streams a file for download. No conflict exists, but they **must be registered in
the correct order** in FastAPI (the more specific `/exceptions/export` first, or
using an explicit path rather than relying on route order). Verify during implementation.

---

## 5. Frontend ↔ API Alignment

| Frontend component | API calls | Story alignment |
|--------------------|-----------|:---------:|
| `LoginPage.tsx` | `POST /api/auth/login`, `GET /api/auth/me` | PD-WEB-002 ✅ |
| `RunPage.tsx` | `POST /api/runs` (multipart), `GET /api/runs/{id}` polling | PD-WEB-001 ✅ |
| `ResultsPage.tsx` | `GET /api/runs/{id}/results`, `GET /api/runs/{id}/report` | PD-WEB-003/005 ✅ |
| `ExceptionsPage.tsx` | `GET /api/runs/{id}/exceptions`, `GET /api/rosters/{file_id}`, `POST /api/claims/{id}/decision`, `GET /api/runs/{id}/exceptions/export` | PD-WEB-003/005 ✅ |
| `ConfigPage.tsx` | `GET /api/config`, `PUT /api/config` | PD-WEB-004 ✅ |
| `AuditPage.tsx` | `GET /api/audit?run_id=&claim_id=&rule=` | PD-WEB-004 ✅ |
| `usePolling` hook | `GET /api/runs/{id}` on interval | PD-WEB-001 ✅ |
| `RosterPreview` | `GET /api/rosters/{file_id}` | PD-WEB-003 ✅ |

All frontend components have matching API endpoints. No frontend component calls
an endpoint that is not in the stories. **The mapping is complete.**

---

## 6. Pre-Implementation Checklist

Resolve these before writing any `web/` or `worker/` code.

| # | Item | Priority | Owner |
|---|------|:--------:|-------|
| 1 | **Auth mechanism** (G-06): password-only, `ADMIN_PASSWORD` env var ✅ | ~~🔴 Blocker~~ **Done** | — |
| 2 | **Add `stage` column migration** (G-03): `002_add_stage_to_runs.py` | 🔴 Blocker | Dev |
| 3 | **Define `GET /api/health`** (G-01): add to PD-WEB-001 scope | 🟠 High | Dev |
| 4 | **Document re-aggregation semantics** (G-04): sync vs async | 🟠 High | Dev |
| 5 | **Add pagination spec** (G-05): `?limit=&offset=` on list endpoints | 🟡 Medium | Dev |
| 6 | **Clarify `corrected_days` validation** (G-07): re-run rules or accept as-is | 🟡 Medium | Dev |
| 7 | **Document SPA static mount order** (G-08): add to `main.py` design note | 🟡 Medium | Dev |
| 8 | **Worker startup handler** (G-09): mark stale `RUNNING` runs as `FAILED` | 🟡 Medium | Dev |
| 9 | **Confirm `file_id` identity for roster endpoint** (G-02): Drive ID vs internal | 🟢 Low | Dev |

---

## 7. Summary

The EP-WEB stories are well-specified for business behaviour and frontend
components. The API route inventory is **complete and consistent** — every
frontend screen has a matching backend endpoint, and the Swagger UI configuration
is straightforward (two lines in `FastAPI()` constructor).

The main items missing from the stories are:

1. ~~Auth mechanism (G-06)~~ **✅ Resolved** — password-only via `ADMIN_PASSWORD` env var
2. Fine-grained `stage` column in the DB (G-03, requires one more Alembic migration) — **still a blocker**
3. A health endpoint (G-01)
4. Pagination on list endpoints (G-05, can be added during implementation)

Everything else is design/specification detail that can be resolved inline during
the PD-WEB-001/002 implementation without changing story scope.

**Recommended first step:** write Alembic migration `002_add_stage_to_runs.py` (G-03),
then begin PD-WEB-002 → PD-WEB-001 → PD-WEB-003 → PD-WEB-005 → PD-WEB-004
in the order specified by `implementation-order.md`.
