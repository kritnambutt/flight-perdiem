"""Report download endpoints: master xlsx and exception xlsx."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from perdiem.db import repository as repo
from perdiem.engine import report as report_engine
from perdiem.web.deps import CurrentUser, DBSession
from perdiem.web.routes.results import compute_results

router = APIRouter(tags=["reports"])


@router.get("/api/runs/{run_id}/report")
def download_master(
    run_id: uuid.UUID,
    session: Session = DBSession,
    _user: str = CurrentUser,
) -> Response:
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status != "DONE":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run not finished yet")

    results = compute_results(session, run_id)
    xlsx_bytes = report_engine.write_master(results, run.cycle_month)
    filename = f"perdiem_{run.cycle_month.replace(' ', '_')}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
