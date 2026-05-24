# Backend Standards

Standards for the backend, built with **Python 3.12 + FastAPI** (venv for local
dev). Read this before working on any file under `backend/`.

## Layering (important)

```
perdiem/engine/   # PURE library: ingest, OCR, rules, pairing, identity, dedup, report
perdiem/web/      # FastAPI: routes, auth, schemas — a THIN layer over the engine
perdiem/worker/   # background job runner — also a thin caller of the engine
perdiem/db/       # SQLAlchemy models, session, migrations
```

- The **engine must not import** `web`, `worker`, or `db`. Rule functions are
  pure (no I/O), so they're unit-tested directly on fixtures.
- The API and the worker **share the engine** — never duplicate business logic.
- The worker communicates with the API only **through the database**, not via
  direct calls.

## Code Style

- Full **type hints** on public functions; `@dataclass` for engine models;
  **Pydantic** models for FastAPI request/response schemas.
- Format + lint with **ruff** (and black-compatible formatting). No unused imports.
- Small, single-purpose functions. Pure functions in the engine; side effects at
  the edges (web/worker/db).
- Raise explicit exceptions; convert to proper HTTP errors in the web layer.

## Validation engine rules

- Each rule (R1–R8, R5a) is a small predicate; `validate_claim` orchestrates them.
- Output one `Verdict` **per claimed day**, tagged with `rule` + `reason`
  (`VALID | VALID_BACKCLAIM | NEEDS_REVIEW | INVALID`).
- Flight-number sets, routes, rate, thresholds come from **config** (they rotate
  monthly) — never hard-code them.

## FastAPI

- Routes grouped by resource under `web/routes/` (`runs.py`, `claims.py`, …).
- Auth dependency enforced on all non-public routes; roster previews are auth-gated.
- OpenAPI docs auto-generated; give each route a clear `summary`/`tags`.
- Long work runs in the **worker**, not the request thread — endpoints enqueue and
  return quickly; the UI polls for progress.

## Database (PostgreSQL)

- Access via **SQLAlchemy**; migrations via **Alembic** (unless the Prisma
  decision changes this — see `docs/features/Platform/story-001-database-schema.md`).
- JSONB for flexible fields; `timestamptz` for times; foreign keys + the indexes
  needed for dedup (`verdicts(staff_id, claimed_date)`).
- `DATABASE_URL=postgresql+psycopg://perdiem:***@db:5432/perdiem`.

## OCR (Tesseract + OpenCV)

- Preprocess before OCR (deskew, threshold, denoise, upscale). Roster text is
  printed — Tesseract is sufficient; PaddleOCR/EasyOCR only as a local fallback.
- Red-box detection uses **OpenCV HSV masking**, not OCR.
- Emit a **confidence** per field; below threshold → `NEEDS_REVIEW`, never a guess.

## Testing

- Engine: `pytest` unit tests, no DB, fixtures from `docs/example-files`.
- API: integration tests against a disposable Postgres.

## Security

- Secrets via env / mounted files; never commit `.env*` or `secrets/`.
- Google access via the read-only service account; treat roster images as PII.
