"""JWT-based authentication helpers.

Single shared admin password read from ADMIN_PASSWORD env var.
No username — the login form accepts only a password.
"""
from __future__ import annotations

import hmac
import time

from jose import JWTError, jwt

from perdiem.config import settings

_ALGORITHM = "HS256"
_SUBJECT = "admin"


def _secret() -> str:
    return settings.jwt_secret


def verify_password(submitted: str) -> bool:
    """Constant-time comparison against the env-configured admin password."""
    expected = settings.admin_password
    if not expected:
        return False
    return hmac.compare_digest(submitted.encode(), expected.encode())


def create_token() -> str:
    exp = int(time.time()) + settings.jwt_expire_hours * 3600
    return jwt.encode({"sub": _SUBJECT, "exp": exp}, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> str | None:
    """Return subject string on valid token, None on any failure."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
        sub: str = payload.get("sub", "")
        return sub if sub else None
    except JWTError:
        return None
