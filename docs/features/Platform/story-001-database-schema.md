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

1. ✅ **DONE** SQLAlchemy 2.x `Mapped`-column ORM models for all 6 tables; JSONB, UUID, `timestamptz`; FK cascades.
2. ✅ **DONE** `alembic.ini` + `migrations/env.py`; migration `001_initial_schema.py` verified via `alembic upgrade head --sql`.
3. ✅ **DONE** Indexes: `ix_claims_run_id`, `ix_claims_staff_id`, `ix_verdicts_claim_id`, `ix_verdicts_staff_id_claimed_date` (dedup support), `ix_overrides_claim_id`, `ix_audit_run_id`.
4. ✅ **DONE** `repository.py`: `create_run`, `update_run_status`, `create_claim`, `write_verdicts` (idempotent replace), `create_override`, `write_audit`, `get_config`/`set_config`/`get_all_config`.
5. ✅ **DONE** 20 integration tests in `tests/db/test_repository.py` (testcontainers postgres:16-alpine); skipped automatically if Docker unavailable. All 263 tests pass.

## 🏗 Structure

```
backend/
├── alembic.ini
└── perdiem/db/
    ├── models.py      # ORM: Run, Claim, Verdict, Override, Audit, Config
    ├── session.py     # engine + SessionLocal + get_session() FastAPI dep
    ├── repository.py  # data-access helpers
    └── migrations/
        ├── env.py
        ├── script.py.mako
        └── versions/001_initial_schema.py
tests/db/
├── conftest.py        # testcontainers fixture + per-test rollback
└── test_repository.py # 20 integration tests
```

## 📌 Notes / Open Questions

- **Migration tool:** settled on **Alembic + SQLAlchemy**. Prisma option dropped — no practical advantage for a Python-only stack on Pi 5. ✅ Resolved.
- `staff_id` is denormalized onto the `verdicts` table to support the `(staff_id, claimed_date)` dedup index without a join.
- Config history (for PD-WEB-004 audit): the `config` table stores the current value; a versioned history can be added as a follow-up migration when PD-WEB-004 is built.
