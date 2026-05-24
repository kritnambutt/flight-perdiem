# Project Standards and Best Practices

## File Naming

### Backend (Python)
- Modules/files: `snake_case.py` — `ingest.py`, `admin_gallery.py`.
- Classes: PascalCase; functions/vars: snake_case; constants: UPPER_CASE.
- Tests: `test_<unit>.py` (e.g. `test_rules.py`), mirroring the module.

### Frontend (TypeScript/React)
- Components: PascalCase — `RosterPreview.tsx`, `RunPage.tsx`.
- Hooks: camelCase with `use` prefix — `useRun.ts`, `usePolling.ts`.
- Utilities: camelCase — `apiClient.ts`. Test files: `*.test.tsx`.

## Code Style

### Python
- Target **Python 3.12**; full **type hints** on public functions; `dataclass`es
  for engine models.
- Format with **ruff/black**; lint with **ruff**. Keep functions small and pure
  where possible (the engine is a pure library — no I/O in rule functions).
- Pydantic models for FastAPI request/response schemas; SQLAlchemy for persistence.
- Raise/return clear errors; never swallow exceptions silently.

### React / TypeScript
- TypeScript strict mode; explicit prop/return types; `interface` for object shapes.
- **Arrow functions + named exports** (avoid `export default`). Props interface
  named `ComponentNameProps`.
- Tailwind CSS, mobile-first; keep components focused.
- React Query (or fetch hooks) for server state; Context for global state.

## The engine is sacred

- `backend/perdiem/engine/` is a **pure library**: no FastAPI, no SQLAlchemy, no
  network in the rule functions. It is reused by the API, the worker, and tests.
- Per-day validation outputs a `Verdict` tagged with the **deciding rule** — every
  payable/rejected decision must be auditable (N1).
- Re-running a cycle must be **idempotent** (N2) — no double counting.

## Testing

- **Engine unit tests** run with no DB, against `docs/example-files` fixtures.
- **API/integration tests** use a disposable Postgres (the `db` container or
  testcontainers).
- AAA pattern (Arrange/Act/Assert); cover rule pass/fail, name-matching variants,
  month-boundary pairing, dedup correctness.

## Performance (Raspberry Pi 5)

- Batch workload, not latency-critical. **Bounded concurrency** for OCR/downloads.
- Cache downloaded rosters by file id (skip re-download on re-runs).
- One concurrent run at a time; keep Postgres tuned small.

## Security

- Validate inputs at boundaries (form data, uploads, API).
- Secrets via env / mounted files only — **never commit** `.env*` or `secrets/`.
- Roster images + names are **PII**: auth-gate previews; LAN/Cloudflare-only access.
- Google access uses the read-only service account.

## API Standards (REST)

- kebab-case URLs (`/api/runs`, `/api/claims/{id}/decision`); correct HTTP methods
  and status codes; consistent response shape; OpenAPI docs via FastAPI.
