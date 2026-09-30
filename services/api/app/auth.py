"""Two auth mechanisms, matching the two kinds of caller this API has:

  - Service API keys — the six simulated systems calling POST /v1/calls.
    Each system's key maps to exactly its own system name, so a system
    cannot tag calls as belonging to another system (that would reopen
    the exact spoofing gap the shared wrapper's own tagging is meant to
    close from the client side).
  - JWT bearer tokens — the human dashboard user reading/configuring the
    Ledger. A single admin account (see docs/architecture.md — no user
    management system exists yet; a documented, deliberate scope limit).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from api.app.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def create_access_token(subject: str, settings: Settings) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        payload = jwt.decode(
            credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    return payload["sub"]


async def require_service_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> str:
    """Returns the calling system's name, resolved from its API key.
    Wired as a header dependency in each router that needs it — see
    routers/calls.py."""
    if x_api_key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header")
    system = settings.service_api_key_map.get(x_api_key)
    if system is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return system
