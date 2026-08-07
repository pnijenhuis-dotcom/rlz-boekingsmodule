"""Parallelle refresh-race over ECHTE HTTP (browserreview 2026-08-07): één pageload bleek twee
gelijktijdige POST /auth/token/vernieuwen te sturen met dezelfde cookie. Vóór de fix trok de
hergebruik-detectie daarop alle sessies in (spontane uitlog) en konden vervolg-calls eindeloos
pending blijven. Deze tests pinnen het gewenste gedrag op de draad vast: (a) beide racende calls
krijgen binnen de timeout een antwoord, (b) er volgt géén revoke-all — beide uitgegeven tokens
blijven bruikbaar, en (c) hergebruik ná de grace-periode blijft wél hard 401 + revoke-all."""

from __future__ import annotations

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import Engine, text

from app.config import settings
from app.security.tokens import create_refresh_token

# Ruim boven de backend-lock-timeout (5 s default) maar eindig: een request dat hier overheen
# gaat is precies de "eeuwig pending"-hang die deze test moet vangen.
_CLIENT_TIMEOUT = 15.0


def _maak_refresh_sessie(admin_engine: Engine, gebruiker_id: uuid.UUID) -> str:
    """Geeft een geldig refresh-token uit zoals _issue_token_paar dat doet: JWT + hash-rij.
    Rechtstreeks als schema-owner, zodat de e2e-test geen volledige TOTP-loginflow hoeft te
    doorlopen (zelfde patroon als de _bearer()-shortcut in test_http_e2e.py)."""
    token = create_refresh_token(gebruiker_id)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.refresh_token (id, gebruiker_id, token_hash, verloopt_op) "
                "VALUES (:id, :g, :h, :v)"
            ),
            {
                "id": uuid.uuid4(),
                "g": gebruiker_id,
                "h": hashlib.sha256(token.encode()).hexdigest(),
                "v": datetime.now(UTC) + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
            },
        )
    return token


def _vernieuw(server: str, refresh_token: str) -> httpx.Response:
    return httpx.post(
        f"{server}/auth/token/vernieuwen",
        cookies={"refresh_token": refresh_token},
        timeout=_CLIENT_TIMEOUT,
    )


class TestParallelleRefreshRace:
    def test_race_geeft_beide_callers_een_werkende_sessie_en_geen_revoke_all(
        self, server: str, admin_engine: Engine, actieve_medewerker: uuid.UUID
    ) -> None:
        token = _maak_refresh_sessie(admin_engine, actieve_medewerker)

        # Twee gelijktijdige rotaties van hetzelfde token — de browser-race van 2026-08-07.
        # De client-timeout op elk request is meteen de hang-guard: een eeuwig pending antwoord
        # laat httpx hier een ReadTimeout gooien.
        with ThreadPoolExecutor(max_workers=2) as pool:
            antwoorden = list(pool.map(lambda _: _vernieuw(server, token), range(2)))

        assert [a.status_code for a in antwoorden] == [200, 200], [
            (a.status_code, a.text) for a in antwoorden
        ]

        # Geen revoke-all: élk uitgegeven token (winnaar én grace-sibling) roteert gewoon door.
        for antwoord in antwoorden:
            vervolg = _vernieuw(server, antwoord.cookies["refresh_token"])
            assert vervolg.status_code == 200, vervolg.text

    def test_hergebruik_na_grace_blijft_401_met_revoke_all(
        self, server: str, admin_engine: Engine, actieve_medewerker: uuid.UUID
    ) -> None:
        token = _maak_refresh_sessie(admin_engine, actieve_medewerker)
        eerste = _vernieuw(server, token)
        assert eerste.status_code == 200

        # gebruikt_op voorbij de grace-periode terugzetten = echte replay simuleren.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE platform.refresh_token "
                    "SET gebruikt_op = gebruikt_op - make_interval(secs => :s) "
                    "WHERE token_hash = :h"
                ),
                {
                    "s": settings.refresh_hergebruik_grace_seconds + 5,
                    "h": hashlib.sha256(token.encode()).hexdigest(),
                },
            )

        replay = _vernieuw(server, token)
        assert replay.status_code == 401

        # Revoke-all: ook het net-uitgegeven opvolger-token is ingetrokken.
        opvolger = _vernieuw(server, eerste.cookies["refresh_token"])
        assert opvolger.status_code == 401
