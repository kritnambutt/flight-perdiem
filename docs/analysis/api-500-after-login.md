# API 500 Errors After Login

**Date:** 2026-05-24  
**Status:** Fixed  
**Symptom:** After successful login, all DB-backed endpoints (`/api/config`, `/api/runs`, `/api/audit`) return 500 Internal Server Error. The `/api/auth/me` endpoint returns 200.

---

## Observed Behaviour

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /api/auth/me` | 200 | No DB access — reads JWT cookie only |
| `GET /api/config` | 500 | Uses DB |
| `GET /api/runs` | 500 | Uses DB |
| `GET /api/audit` | 500 | Uses DB |

Response body for all 500s: `"Internal Server Error"` (FastAPI default for unhandled exceptions).

---

## Root Cause

The `.env` `DATABASE_URL` was set to:

```
DATABASE_URL=postgresql+psycopg://perdiem:perdiem@host.docker.internal:5432/perdiem
```

`host.docker.internal` is a hostname that Docker Desktop injects into `/etc/hosts` **inside containers** and on the macOS host. However, this entry was **not present** in `/etc/hosts` on this machine:

```
$ grep host.docker.internal /etc/hosts
(no output)
```

When running `make backend-dev` (local dev, outside Docker), the Python process tries to resolve `host.docker.internal` and fails:

```
psycopg.OperationalError: [Errno 8] nodename nor servname provided, or not known
```

FastAPI catches the uncaught SQLAlchemy exception and returns 500.

`/api/auth/me` returns 200 because its dependency chain only reads the `session_token` cookie and validates the JWT — **it never opens a DB connection**.

---

## Why Docker Was Not Affected

The Docker compose file overrides `DATABASE_URL` in its own `environment:` block:

```yaml
api:
  environment:
    DATABASE_URL: postgresql+psycopg://perdiem:${POSTGRES_PASSWORD}@host.docker.internal:5432/perdiem
```

This override takes precedence over the `.env` value inside containers, where `host.docker.internal` resolves correctly to the Docker host gateway. The `.env` file's `DATABASE_URL` is **only used for local dev**.

---

## Database State

Migrations had already been run (Alembic). All required tables were present:

```
alembic_version, audit, claims, config, overrides, runs, verdicts
```

No schema issue — the only problem was the hostname resolution failure.

---

## Fix

Changed `DATABASE_URL` in `.env` and `.env.example` to use `localhost` for local dev:

```
DATABASE_URL=postgresql+psycopg://perdiem:perdiem@localhost:5432/perdiem
```

`localhost:5432` works because `wedding-yokyo-db-1` (the shared Postgres container) binds port 5432 to `0.0.0.0` on the host.

Docker compose is unaffected — its `environment:` block still uses `host.docker.internal` and overrides the `.env` value.

---

## Key Takeaway

The `.env` `DATABASE_URL` serves **two different purposes** depending on context:

| Context | URL to use | Why |
|---------|-----------|-----|
| Local dev (`make backend-dev`) | `localhost:5432` | Direct host connection |
| Docker containers (`make up`) | `host.docker.internal:5432` | Set by compose `environment:`, not from `.env` |

Never put `host.docker.internal` in the `.env` `DATABASE_URL` — it only works inside Docker containers.
