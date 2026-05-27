"""Run orchestration: POST /api/runs, GET /api/runs, GET /api/runs/{id}."""
from __future__ import annotations

import io
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from perdiem.config import settings
from perdiem.db import repository as repo
from perdiem.engine import ingest
from perdiem.web.deps import CurrentUser, DBSession
from perdiem.web.schemas import RunOut, WorkbookSheetsOut

router = APIRouter(prefix="/api/runs", tags=["runs"])

_ALLOWED_CT = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
}


def _save_upload(file: UploadFile, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)


@router.post("/sheets", response_model=WorkbookSheetsOut)
def inspect_sheets(
    file: UploadFile,
    month: Annotated[str | None, Form()] = None,
    _user: str = CurrentUser,
) -> WorkbookSheetsOut:
    """List a workbook's worksheet names so the UI can offer a sheet picker.

    When `month` is supplied, `suggested` is the sheet auto-detection would pick —
    the UI uses it as the default selection.
    """
    if file.filename and not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{file.filename}: only .xlsx files accepted",
        )
    raw = file.file.read()
    try:
        sheets = ingest.list_sheet_names(io.BytesIO(raw))
    except Exception as exc:  # openpyxl raises various errors on bad input
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not read workbook: {exc}",
        ) from exc

    suggested = ingest.suggest_sheet(io.BytesIO(raw), month) if month else None
    return WorkbookSheetsOut(sheets=sheets, suggested=suggested)


@router.post("", status_code=status.HTTP_201_CREATED)
def start_run(
    month: Annotated[str, Form()],
    posting_base: UploadFile,
    late_submission: UploadFile,
    posting_sheet: Annotated[str | None, Form()] = None,
    late_sheet: Annotated[str | None, Form()] = None,
    session: Session = DBSession,
    _user: str = CurrentUser,
) -> dict:
    for upload in (posting_base, late_submission):
        if upload.filename and not upload.filename.lower().endswith(".xlsx"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{upload.filename}: only .xlsx files accepted",
            )

    run = repo.create_run(session, month, posting_sheet or None, late_sheet or None)
    session.commit()

    run_dir = Path(settings.uploads_dir) / str(run.id)
    _save_upload(posting_base, run_dir / "posting_base.xlsx")
    _save_upload(late_submission, run_dir / "late_submission.xlsx")

    return {"run_id": str(run.id)}


@router.get("", response_model=list[RunOut])
def list_runs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = DBSession,
    _user: str = CurrentUser,
) -> list[RunOut]:
    runs = repo.list_runs(session, limit=limit, offset=offset)
    return [RunOut.model_validate(r) for r in runs]


@router.get("/{run_id}", response_model=RunOut)
def get_run(
    run_id: uuid.UUID,
    session: Session = DBSession,
    _user: str = CurrentUser,
) -> RunOut:
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return RunOut.model_validate(run)


# The two source workbooks submitted to the pipeline, stored under uploads_dir/{run_id}.
_INPUT_FILES = {
    "posting-base": ("posting_base.xlsx", "Posting Base Perdiem (Responses)"),
    "late-submission": ("late_submission.xlsx", "Late Submission Perdiem (Responses)"),
}


@router.get("/{run_id}/inputs/{kind}")
def download_input(
    run_id: uuid.UUID,
    kind: str,
    session: Session = DBSession,
    _user: str = CurrentUser,
) -> FileResponse:
    """Download a source workbook submitted to this run (posting-base | late-submission)."""
    if kind not in _INPUT_FILES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown input file")

    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    stored_name, label = _INPUT_FILES[kind]
    path = Path(settings.uploads_dir) / str(run_id) / stored_name
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Input file not found")

    download_name = f"{label} - {run.cycle_month}.xlsx"
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=download_name,
    )
