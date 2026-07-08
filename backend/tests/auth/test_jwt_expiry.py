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
    """Was flaky: het allerlaatste base64url-teken van een 32-byte HMAC-SHA256-signature bevat 2
    betekenisloze opvulbits (256 bits / 6 = geen geheel getal, dus het laatste teken van de
    signature draagt maar 4 echte databits + 2 nul-opvulbits). `base64.urlsafe_b64decode` negeert
    die opvulbits bij het decoderen — een vervanging van precies dát teken kan toevallig naar
    exact dezelfde bytes decoderen, waardoor de manipulatie soms geen effect had. Het
    voorlaatste teken zit niet op die randgrens en draagt altijd de volle 6 databits, dus een
    afwijkende waarde daar verandert de gedecodeerde bytes gegarandeerd."""
    gebruiker_id = uuid.uuid4()
    token = create_access_token(gebruiker_id, rol="boekhouding")
    header, payload, signature = token.rsplit(".", 2)
    tamper_index = -2
    vervanger = "A" if signature[tamper_index] != "A" else "B"
    geknoeide_signature = signature[:tamper_index] + vervanger + signature[tamper_index + 1 :]
    geknoeid = f"{header}.{payload}.{geknoeide_signature}"
    with pytest.raises(TokenError):
        decode_token(geknoeid, expected_type="access")
