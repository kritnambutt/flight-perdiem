"""FastAPI dependency functions (auth guard, DB session)."""
from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from perdiem.db.session import get_session
from perdiem.web.auth import decode_token


def get_current_user(session_token: str | None = Cookie(default=None)) -> str:
    """Raise 401 if the request has no valid session cookie."""
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    subject = decode_token(session_token)
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return subject


CurrentUser = Depends(get_current_user)
DBSession = Depends(get_session)
