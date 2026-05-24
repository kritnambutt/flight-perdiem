| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-PLAT-001                                        |
| Title        | PostgreSQL schema & persistence                    |
| Epic         | EP-PLAT — Persistence & Deployment                 |
| Dependencies | PostgreSQL 16, SQLAlchemy, Alembic                 |
| Story Type   | Feature                                            |
| Source       | architecture.md → "PostgreSQL schema"; REQUIREMENTS §7 (N1, N2)|

## 🗂 Epic Overview — EP-PLAT

See [overview.md](./overview.md). This story defines the relational model that
every other epic reads/writes — runs, claims, verdicts, overrides, audit, config.

## 📝 Feature Overview — PD-PLAT-001

### User Story

```gherkin
As the system
I want a durable schema for runs, verdicts, overrides, audit and config
So that review state and decisions persist between runs and survive restarts

As an admin
I want every decision linked to its source and rule
So that the system is fully auditable
```

### Pre-conditions

- PostgreSQL container available; SQLAlchemy + Alembic configured.

### Scope

#### Included

- Tables: `runs`, `claims`, `verdicts`, `overrides`, `audit`, `config`.
- JSONB for flexible fields (counts, extracted fields, day lists); `timestamptz`
  for times; foreign keys + indexes.
- Alembic migrations (create + evolve).
- Repository/data-access layer used by the API and worker.
- Indexes supporting dedup/aggregation (`verdicts(staff_id, claimed_date)`).

#### Excluded

- Business logic (engine epics) — this is persistence only.
- Deployment/containers (PD-PLAT-002).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Schema** — all six tables created via migration, matching the architecture sketch.
2. **Relationships** — `claims.run_id → runs`, `verdicts.claim_id → claims`,
   `overrides.claim_id → claims`; cascade/restrict chosen deliberately.
3. **Auditability (N1)** — `verdicts` store `rule`, `reason`, `confidence`,
   `extracted`; `audit` rows link `run_id`/`claim_id` to actions; overrides
   capture `decided_by/at/note`.
4. **Idempotency support (N2)** — keys/constraints let a re-run replace a run's
   verdicts without duplicates; unique `(staff_id, claimed_date)` dedup is
   queryable.
5. **Migrations** — `alembic upgrade head` builds the schema from empty;
   downgrade defined where practical.

### Error Scenarios

- Migration conflict → fail fast with a clear message; never silently diverge.
- Concurrent api + worker writes (run progress + verdicts) → Postgres handles via
  transactions; no lost updates.

## 🧩 Technical Documentation

### Schema (from architecture.md)

```sql
runs(id, cycle_month, status, progress, counts jsonb,
     started_at timestamptz, finished_at timestamptz)
claims(id, run_id -> runs, source, source_row_ref, staff_id, name, email,
       claim_month, claimed_days jsonb, roster_refs jsonb)
verdicts(id, claim_id -> claims, claimed_date date, verdict, rule, reason,
         confidence, extracted jsonb)
overrides(id, claim_id -> claims, decision, decided_by, decided_at timestamptz, note)
audit(id, run_id, claim_id, action, detail jsonb, at timestamptz)
config(key primary key, value jsonb)
```

Indexes: `claims(run_id)`, `verdicts(claim_id)`, `verdicts(staff_id, claimed_date)`.

### Access

- SQLAlchemy models in `perdiem/db/models.py`; session factory in `session.py`.
- `DATABASE_URL=postgresql+psycopg://perdiem:***@db:5432/perdiem`.

## 🔨 Implementation Plan

1. 📝 **TODO** SQLAlchemy models for the six tables + relationships.
2. 📝 **TODO** Alembic init + first migration; `upgrade head` from empty.
3. 📝 **TODO** Indexes (esp. dedup support).
4. 📝 **TODO** Repository helpers (create run, write verdicts, record override/audit, read config).
5. 📝 **TODO** Tests on a disposable Postgres (db container / testcontainers).

## 🏗 Structure

```
backend/perdiem/db/
├── models.py
├── session.py
└── migrations/        # alembic
```

## 📌 Notes / Open Questions

- **Migration tool:** plan currently uses **Alembic**. (User raised Prisma —
  unresolved: Prisma-only via prisma-client-py vs Prisma migrations + SQLAlchemy.
  Settle before building this story.)
- Keep a versioned config history table for run-time reconstruction (see PD-WEB-004).
