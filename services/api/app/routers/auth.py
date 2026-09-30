from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from api.app.auth import create_access_token
from api.app.config import Settings, get_settings
from api.app.schemas import TokenResponse

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    valid = hmac.compare_digest(form.username, settings.admin_username) and hmac.compare_digest(
        form.password, settings.admin_password
    )
    if not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = create_access_token(subject=form.username, settings=settings)
    return TokenResponse(access_token=token)
