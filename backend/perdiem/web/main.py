"""FastAPI application entry point.

URL layout:
  /api/docs       Swagger UI
  /api/docs-json  OpenAPI spec (Postman import)
  /api/health     Health probe (no auth)
  /api/auth/...   Authentication
  /api/runs/...   Run orchestration
  /api/claims/... Decisions
  /api/rosters/.. Roster image proxy
  /api/config     Rules config
  /api/audit      Audit trail
  /               React SPA (static, mounted LAST so /api/* routes take priority)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from perdiem.web.routes import (
    audit,
    auth,
    claims,
    config,
    exceptions,
    reports,
    results,
    rosters,
    runs,
)

app = FastAPI(
    title="Per Diem Validation API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/docs-json",
)


# ---------------------------------------------------------------------------
# Health (no auth, used by Docker healthcheck)
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# API routers (all /api/* must be registered before the SPA mount)
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(runs.router)
app.include_router(claims.router)
app.include_router(results.router)
app.include_router(exceptions.router)
app.include_router(reports.router)
app.include_router(rosters.router)
app.include_router(config.router)
app.include_router(audit.router)


# ---------------------------------------------------------------------------
# SPA static files — MUST be mounted last (html=True catchall intercepts /)
# ---------------------------------------------------------------------------

import os as _os

_SPA_DIR = Path(
    _os.getenv(
        "SPA_DIR",
        str(Path(__file__).parent.parent.parent.parent / "frontend" / "dist"),
    )
)

if _SPA_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_SPA_DIR), html=True), name="spa")
