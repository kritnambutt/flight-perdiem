| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-PLAT-003                                        |
| Title        | Pre-WebApp infrastructure (gap closure)            |
| Epic         | EP-PLAT — Persistence & Deployment                 |
| Dependencies | PD-PLAT-001 (schema done), FastAPI, python-jose    |
| Story Type   | Feature                                            |
| Source       | docs/analysis/webapp-api-readiness.md — G-01, G-03, G-05, G-08, G-09 |

## 📝 Feature Overview — PD-PLAT-003

Closes the gaps identified in the WebApp API readiness analysis that must be
resolved **before** any EP-WEB story can be implemented.  All items here are
cross-cutting infrastructure; none belong to a single WebApp story.

### Gaps addressed

| Gap | Description | Status before this story |
|-----|-------------|:------------------------:|
| G-01 | `GET /api/health` not defined anywhere | Missing |
| G-03 | `runs.stage` column absent — fine-grained pipeline stages cannot be tracked | Missing |
| G-05 | Pagination (`?limit=&offset=`) not specified on list endpoints | Missing |
| G-08 | SPA static-file mount order in `main.py` not documented | Missing |
| G-09 | Worker crash-safety: stale `RUNNING` runs not cleaned up on restart | Missing |

## 🎯 Acceptance Criteria

1. **`GET /api/health`** returns `{ "status": "ok" }` with HTTP 200, no auth
   required.  Docker `healthcheck:` uses this endpoint.
2. **`runs.stage`** VARCHAR(30) column added via Alembic migration `002`; ORM
   `Run` model includes the field; `update_run_status` accepts an optional
   `stage` parameter.
3. **Pagination** — all list endpoints (`GET /api/runs`, `/results`,
   `/exceptions`, `/audit`) accept `?limit=` (default 100, max 500) and
   `?offset=` (default 0).
4. **SPA mount order** — `main.py` registers all `/api/` routers **before**
   mounting `StaticFiles`; an integration test asserts `GET /api/docs` → 200.
5. **Worker crash-safety** — on `runner.py` startup, any `Run` with
   `status="RUNNING"` is set to `status="FAILED"`, `stage="crashed"`,
   with an audit row `action="worker_restarted"`.

## 🧩 Technical Documentation

### Migration 002

```python
# versions/002_add_stage_to_runs.py
def upgrade():
    op.add_column("runs", sa.Column("stage", sa.VARCHAR(30), nullable=True))

def downgrade():
    op.drop_column("runs", "stage")
```

### Updated `Run` ORM field

```python
stage: Mapped[str | None] = mapped_column(VARCHAR(30), nullable=True)
```

### `update_run_status` signature (extended)

```python
def update_run_status(
    session, run_id, status, *,
    stage=None, progress=None, counts=None,
    started_at=None, finished_at=None
) -> None: ...
```

### `GET /api/health` (no auth, no DB)

```python
@router.get("/api/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}
```

### SPA mount order in `main.py`

```python
app = FastAPI(docs_url="/api/docs", openapi_url="/api/docs-json")
app.include_router(auth_router)
app.include_router(runs_router)
# ... all /api/ routers ...
# LAST — catchall must come after all API routes
app.mount("/", StaticFiles(directory="dist", html=True), name="spa")
```

### Worker crash-safety snippet

```python
def _recover_stale_runs(session: Session) -> None:
    stale = session.scalars(
        select(Run).where(Run.status == "RUNNING")
    ).all()
    for run in stale:
        run.status = "FAILED"
        run.stage = "crashed"
        write_audit(session, "worker_restarted", run_id=run.id,
                    detail={"reason": "worker process restarted mid-run"})
    session.commit()
```

## 🔨 Implementation Plan

1. ✅ **DONE** Write `002_add_stage_to_runs.py` migration; update `Run` ORM model.
2. ✅ **DONE** Extend `update_run_status` with `stage` kwarg; add `list_runs`,
   `get_verdicts_for_claim`, `get_audit_entries` to `repository.py`.
3. ✅ **DONE** Add `admin_password`, `jwt_secret`, `jwt_expire_hours`,
   `uploads_dir`, `reports_dir` to `config.py` and `.env.example`.
4. ✅ **DONE** Add `fastapi[standard]`, `uvicorn[standard]`,
   `python-jose[cryptography]`, `python-multipart` to `requirements.txt`.
5. ✅ **DONE** Health endpoint in `web/main.py`; SPA mount order documented.
6. ✅ **DONE** Worker startup crash-safety in `worker/runner.py`.

## 🏗 Structure

```
backend/perdiem/db/migrations/versions/002_add_stage_to_runs.py
backend/perdiem/db/models.py          # Run.stage added
backend/perdiem/db/repository.py      # list_runs, get_verdicts_for_claim, get_audit_entries
backend/perdiem/config.py             # admin_password, jwt_secret, uploads_dir, reports_dir
backend/requirements.txt              # fastapi, uvicorn, python-jose, python-multipart
backend/perdiem/web/main.py           # GET /api/health; SPA mount last
backend/perdiem/worker/runner.py      # _recover_stale_runs on startup
```
