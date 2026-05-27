"""GET /api/rosters/{file_id} — serve cached roster image (auth-gated, PII)."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from perdiem.config import settings
from perdiem.web.deps import CurrentUser

router = APIRouter(prefix="/api/rosters", tags=["rosters"])

_EXTS = (".jpg", ".jpeg", ".png", ".pdf")


@router.get("/{file_id}")
def get_roster(file_id: str, _user: str = CurrentUser) -> FileResponse:
    # Guard against path traversal
    if "/" in file_id or "\\" in file_id or ".." in file_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file_id")

    cache_dir = Path(settings.roster_cache_dir)
    for ext in _EXTS:
        candidate = cache_dir / f"{file_id}{ext}"
        if candidate.exists():
            mt = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
            return FileResponse(str(candidate), media_type=mt)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Roster not in cache")
