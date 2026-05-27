"""Auth routes: login, logout, me."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Response, status

from perdiem.web.auth import create_token, verify_password
from perdiem.web.deps import CurrentUser
from perdiem.web.schemas import LoginIn, MeOut, TokenOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COOKIE = "session_token"
_COOKIE_MAX_AGE = 8 * 3600  # matches JWT_EXPIRE_HOURS default


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, response: Response) -> TokenOut:
    # Artificial delay to slow brute-force attempts
    await asyncio.sleep(1)
    if not verify_password(body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")
    token = create_token()
    response.set_cookie(
        key=_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
    )
    return TokenOut(access_token=token)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(_COOKIE)
    return {}


@router.get("/me", response_model=MeOut)
def me(user: str = CurrentUser) -> MeOut:
    return MeOut(user=user)
