"""FastAPI dependencies: settings, database, authentication and scopes.

Auth uses an ``Authorization: Bearer <token>`` header. ``?token=`` is accepted only for
image endpoints loaded by URLSession in contexts where headers are awkward, and only for
``read``-scoped access to screenshots; it is never accepted for mutations.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from .config import Settings, get_settings
from .db import Database, get_db
from .security import ADMIN, AGENT, ACTION, READ, RateLimiter, TokenInfo, verify_token

_rate_limiter = RateLimiter()


def settings_dep() -> Settings:
    return get_settings()


def db_dep(settings: Annotated[Settings, Depends(settings_dep)]) -> Database:
    return get_db(settings)


DbDep = Annotated[Database, Depends(db_dep)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]


def _extract_token(authorization: str | None, request: Request) -> str | None:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
        return None
    if request.method == "GET" and request.url.path.startswith("/api/v1/screenshots/"):
        return request.query_params.get("token")
    return None


def current_token(
    request: Request,
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> TokenInfo:
    raw = _extract_token(authorization, request)
    info = verify_token(db, raw)
    if info is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Missing or invalid bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return info


TokenDep = Annotated[TokenInfo, Depends(current_token)]


def require(*required: str):
    """Dependency factory requiring at least one of ``required`` scopes."""

    def dependency(token: TokenDep) -> TokenInfo:
        if not any(token.allows(scope) for scope in required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "insufficient_scope",
                    "message": f"This token needs one of: {', '.join(required)}",
                },
            )
        return token

    return dependency


ReadDep = Annotated[TokenInfo, Depends(require(READ))]
ActionDep = Annotated[TokenInfo, Depends(require(ACTION))]
AdminDep = Annotated[TokenInfo, Depends(require(ADMIN))]
AgentDep = Annotated[TokenInfo, Depends(require(AGENT, ADMIN))]
ElevatedDep = Annotated[TokenInfo, Depends(require(ADMIN, AGENT))]
# Only the agent runtime token may pull the queue / publish status: UI tokens can never
# silently consume a queued instruction.
RuntimeDep = Annotated[TokenInfo, Depends(require(AGENT))]

Confirmation = Annotated[str | None, Header(alias="X-Beacon-Confirm")]


def require_confirmation(value: str | None, expected: str, action_label: str) -> None:
    if value != expected:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": "confirmation_required",
                "message": f"Send header X-Beacon-Confirm: {expected} to confirm {action_label}",
            },
        )


def throttle(key: str, *, limit: int, window_seconds: float) -> None:
    allowed, retry_after = _rate_limiter.allow(key, limit=limit, window_seconds=window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "rate_limited", "message": "Too many requests, slow down"},
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


def client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host
