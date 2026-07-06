from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Any, Literal

import jwt

from app.config import settings

_DEV_ENVIRONMENTS = ("dev", "local")
TokenType = Literal["access", "refresh", "totp_setup"]


class TokenError(Exception):
    """Ongeldige, verlopen, of verkeerd-type token."""


def _resolve_jwt_secret(env: Mapping[str, str]) -> str:
    """Analoog aan migraties/0001._resolve_app_role_password: geen stil fallback buiten dev."""
    secret = env.get("JWT_SECRET")
    if secret:
        return secret
    environment = env.get("ENVIRONMENT", "dev")
    if environment not in _DEV_ENVIRONMENTS:
        raise RuntimeError(
            f"JWT_SECRET ontbreekt en ENVIRONMENT={environment!r} is geen dev-omgeving "
            f"({', '.join(_DEV_ENVIRONMENTS)}). Zet JWT_SECRET (Cloud Run: via Secret Manager) "
            "vóórdat sessies in productie draaien."
        )
    return "dev-only-insecure-jwt-secret-32-bytes-min"


def _secret() -> str:
    if settings.jwt_secret:
        return settings.jwt_secret
    return _resolve_jwt_secret({"ENVIRONMENT": settings.environment})


def _issue(
    *,
    gebruiker_id: uuid.UUID,
    token_type: TokenType,
    ttl_seconds: int,
    extra: dict[str, Any] | None = None,
    now: float | None = None,
) -> str:
    issued_at = now if now is not None else time.time()
    payload = {
        "sub": str(gebruiker_id),
        "type": token_type,
        "jti": str(uuid.uuid4()),
        "iat": int(issued_at),
        "exp": int(issued_at) + ttl_seconds,
        **(extra or {}),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def create_access_token(
    gebruiker_id: uuid.UUID, *, rol: str, ttl_seconds: int | None = None, now: float | None = None
) -> str:
    return _issue(
        gebruiker_id=gebruiker_id,
        token_type="access",
        ttl_seconds=ttl_seconds if ttl_seconds is not None else settings.jwt_access_ttl_seconds,
        extra={"rol": rol},
        now=now,
    )


def create_refresh_token(
    gebruiker_id: uuid.UUID, *, ttl_seconds: int | None = None, now: float | None = None
) -> str:
    return _issue(
        gebruiker_id=gebruiker_id,
        token_type="refresh",
        ttl_seconds=ttl_seconds if ttl_seconds is not None else settings.jwt_refresh_ttl_seconds,
        now=now,
    )


def create_totp_setup_token(
    gebruiker_id: uuid.UUID, *, ttl_seconds: int | None = None, now: float | None = None
) -> str:
    return _issue(
        gebruiker_id=gebruiker_id,
        token_type="totp_setup",
        ttl_seconds=ttl_seconds if ttl_seconds is not None else settings.jwt_totp_setup_ttl_seconds,
        now=now,
    )


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise TokenError(f"Verwachtte token-type {expected_type!r}, kreeg {payload.get('type')!r}")
    return payload
