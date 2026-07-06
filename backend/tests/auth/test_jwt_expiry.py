from __future__ import annotations

import time
import uuid

import pytest

from app.security.tokens import (
    TokenError,
    create_access_token,
    create_refresh_token,
    create_totp_setup_token,
    decode_token,
)


def test_geldig_access_token_decodeert() -> None:
    gebruiker_id = uuid.uuid4()
    token = create_access_token(gebruiker_id, rol="boekhouding")
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == str(gebruiker_id)
    assert payload["rol"] == "boekhouding"
    assert payload["type"] == "access"


def test_verlopen_access_token_wordt_geweigerd() -> None:
    gebruiker_id = uuid.uuid4()
    now = time.time()
    token = create_access_token(gebruiker_id, rol="boekhouding", ttl_seconds=1, now=now - 10)
    with pytest.raises(TokenError):
        decode_token(token, expected_type="access")


def test_verlopen_refresh_token_wordt_geweigerd() -> None:
    gebruiker_id = uuid.uuid4()
    now = time.time()
    token = create_refresh_token(gebruiker_id, ttl_seconds=1, now=now - 10)
    with pytest.raises(TokenError):
        decode_token(token, expected_type="refresh")


def test_verlopen_totp_setup_token_wordt_geweigerd() -> None:
    gebruiker_id = uuid.uuid4()
    now = time.time()
    token = create_totp_setup_token(gebruiker_id, ttl_seconds=1, now=now - 10)
    with pytest.raises(TokenError):
        decode_token(token, expected_type="totp_setup")


def test_verkeerd_tokentype_wordt_geweigerd() -> None:
    """Een refresh-token mag nooit als access-token gebruikt kunnen worden, ook al is het
    geldig ondertekend en niet verlopen."""
    gebruiker_id = uuid.uuid4()
    token = create_refresh_token(gebruiker_id)
    with pytest.raises(TokenError, match="type"):
        decode_token(token, expected_type="access")


def test_ongeldige_signature_wordt_geweigerd() -> None:
    gebruiker_id = uuid.uuid4()
    token = create_access_token(gebruiker_id, rol="boekhouding")
    geknoeid = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(TokenError):
        decode_token(geknoeid, expected_type="access")
