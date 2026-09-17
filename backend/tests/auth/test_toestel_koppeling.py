"""Accordeur-uitnodiging web vs app (Peter 16-09) — blok A/B/C serverkant: tonen ≠ verbruiken (info-route), zelfservice
tweede toestel (`POST /auth/app/toestel-koppeling`: alleen vanuit een toestel-sessie, 15 min, eenmalig, bestaande
toestellen blijven, N-limiet bij aanmaken én bij koppelen), 409-tekst mét handeling, legacy wachtwoord-login mét
hint."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from app.auth import app_activatie
from app.auth.router import LEGACY_LOGIN_APP_HINT
from app.config import settings
from app.security.tokens import create_access_token
from tests.auth.test_app_activatie import (
    APP,
    SLOT,
    _activeer,
    _audit_op,
    _geactiveerd,
    _nodig_uit,
    _uitnodiging_rij,
    client,
)
from tests.auth.test_webauthn_cadans import _bearer


def _toestellen(admin_engine: Engine, gebruiker_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT id, platform, ingetrokken_op FROM platform.webauthn_credential "
                    "WHERE gebruiker_id = :g AND soort = 'toestel' ORDER BY aangemaakt_op"
                ),
                {"g": gebruiker_id},
            ).all()
        ]


def _koppeling(sessie: dict, *, headers: dict | None = None):
    h = {**_bearer(sessie["access_token"]), **(SLOT if headers is None else headers)}
    return client.post("/auth/app/toestel-koppeling", headers=h)


class TestTonenIsNietVerbruiken:
    def test_info_route_verbruikt_niets(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        app = _nodig_uit(beheerder_id)
        for _ in range(3):
            resp = client.get(f"/auth/uitnodigingen/info?token={app['token']}")
            assert resp.status_code == 200 and resp.json()["flow"] == "app"
        rij = _uitnodiging_rij(admin_engine, app["uitnodiging_id"])
        assert rij["gebruikt_op"] is None and rij["activatiecode_pogingen"] == 0
        # daarna activeert de code nog gewoon
        assert _activeer({"activatiecode": app["activatiecode"], "platform": "ios"}).status_code == 200

    def test_409_tekst_draagt_de_handeling(self, beheerder_id: uuid.UUID) -> None:
        app = _nodig_uit(beheerder_id)
        assert _activeer({"token": app["token"], "platform": "web"}).status_code == 200
        resp = _activeer({"token": app["token"], "platform": "ios"})
        assert resp.status_code == 409
        assert "Telefoon/app koppelen" in resp.json()["detail"] and "nieuwe uitnodiging" in resp.json()["detail"]


class TestZelfserviceKoppeling:
    def test_vanuit_toestel_sessie_link_en_code_15_min_en_tweede_toestel_zonder_intrekken(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        app, sessie = _geactiveerd(beheerder_id)  # eerste toestel: "Telefoon" (ios)
        gid = uuid.UUID(app["gebruiker_id"])
        resp = _koppeling(sessie)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["link"].endswith(f"/activeren?token={body['token']}")
        assert len(body["activatiecode"].replace("-", "")) == 8
        assert body["actieve_toestellen"] == 1 and body["max_toestellen"] == settings.app_max_toestellen
        verloopt = datetime.fromisoformat(body["verloopt_op"])
        assert timedelta(minutes=14) < verloopt - datetime.now(UTC) <= timedelta(minutes=15)
        assert resp.headers["cache-control"] == "no-store"
        # audit op de uitnodiging-rij zonder code
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT id, aangemaakt_door, gebruiker_id, soort FROM platform.uitnodiging WHERE token_hash = :h"),
                {"h": app_activatie._hash_token(body["token"])},
            ).one()
        assert rij.aangemaakt_door == rij.gebruiker_id == gid and rij.soort == "uitnodiging"
        events = _audit_op(admin_engine, rij.id, "toestel_koppeling_aangemaakt")
        assert len(events) == 1 and events[0]["max_toestellen"] == settings.app_max_toestellen
        assert body["activatiecode"].replace("-", "") not in str(events)
        # tweede toestel activeert mét de code; het eerste toestel blijft
        tweede = _activeer(
            {"activatiecode": body["activatiecode"], "toestel_naam": "Laptop", "platform": "web"}, headers=SLOT
        )
        assert tweede.status_code == 200, tweede.text
        assert tweede.json()["herstel"] is False and tweede.json()["naam"] == "App Gebruiker"
        toestellen = _toestellen(admin_engine, gid)
        assert len(toestellen) == 2 and all(t["ingetrokken_op"] is None for t in toestellen)
        assert {t["platform"] for t in toestellen} == {"ios", "web"}
        # de eerste sessie werkt nog (geen herstel-semantiek)
        assert client.get("/auth/mijn/apparaten", headers=_bearer(sessie["access_token"])).status_code == 200
        assert _audit_op(admin_engine, gid, "toestel_gekoppeld_zelfservice")
        assert not _audit_op(admin_engine, gid, "wachtwoord_hersteld")
        geactiveerd = _audit_op(admin_engine, toestellen[1]["id"], "toestel_geactiveerd")
        assert geactiveerd and geactiveerd[0]["zelfservice"] is True
        # eenmalig
        assert _activeer({"activatiecode": body["activatiecode"], "platform": "android"}).status_code == 409

    def test_nieuwe_koppeling_laat_de_vorige_verlopen(self, beheerder_id: uuid.UUID) -> None:
        _app, sessie = _geactiveerd(beheerder_id)
        eerste = _koppeling(sessie).json()
        tweede = _koppeling(sessie).json()
        assert _activeer({"token": eerste["token"], "platform": "web"}).status_code == 400
        assert _activeer({"token": tweede["token"], "platform": "web"}).status_code == 200

    def test_verlopen_na_15_min_is_400(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        _app, sessie = _geactiveerd(beheerder_id)
        body = _koppeling(sessie).json()
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.uitnodiging SET verloopt_op = now() - interval '1 minute' WHERE token_hash = :h"),
                {"h": app_activatie._hash_token(body["token"])},
            )
        resp = _activeer({"activatiecode": body["activatiecode"], "platform": "web"})
        assert resp.status_code == 400 and resp.json()["detail"] == app_activatie.FOUT_ONGELDIG

    def test_limiet_bij_aanmaken_en_bij_koppelen(
        self, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "app_max_toestellen", 2)
        app, sessie = _geactiveerd(beheerder_id)
        gid = uuid.UUID(app["gebruiker_id"])
        # eerste koppeling → tweede toestel; daarna zit de gebruiker aan het maximum
        k1 = _koppeling(sessie).json()
        assert _activeer({"activatiecode": k1["activatiecode"], "platform": "web"}).status_code == 200
        resp = _koppeling(sessie)
        assert resp.status_code == 409 and "maximum aantal toestellen" in resp.json()["detail"], resp.text
        # limiet óók op het koppelmoment: koppeling aangemaakt terwijl er ruimte was, toestel erbij, dan pas activeren
        monkeypatch.setattr(settings, "app_max_toestellen", 3)
        k2 = _koppeling(sessie).json()
        monkeypatch.setattr(settings, "app_max_toestellen", 2)
        resp = _activeer({"activatiecode": k2["activatiecode"], "platform": "android"})
        assert resp.status_code == 409 and "maximum aantal toestellen" in resp.json()["detail"]
        assert len([t for t in _toestellen(admin_engine, gid) if t["ingetrokken_op"] is None]) == 2
        # een toestel loskoppelen maakt ruimte
        assert client.post("/auth/app-lock/ontkoppelen", headers=_bearer(sessie["access_token"])).status_code == 204
        # (de sessie van het losgekoppelde toestel is nu dood; de koppeling zelf blijft geldig)
        assert _activeer({"activatiecode": k2["activatiecode"], "platform": "android"}).status_code == 200

    def test_zonder_toestel_sessie_400_en_kantoorrol_403(self, beheerder_id: uuid.UUID) -> None:
        app, _sessie = _geactiveerd(beheerder_id)
        los = create_access_token(uuid.UUID(app["gebruiker_id"]), rol="klant_accordeur")  # geen apparaat-claim
        resp = client.post("/auth/app/toestel-koppeling", headers={**_bearer(los), **APP})
        assert resp.status_code == 400 and resp.json()["detail"] == app_activatie.FOUT_KOPPELING_ALLEEN_APP
        kantoor = client.post(
            "/auth/app/toestel-koppeling",
            headers={**_bearer(create_access_token(beheerder_id, rol="beheerder")), **APP},
        )
        assert kantoor.status_code == 403

    def test_ingetrokken_toestel_kan_niet_koppelen(self, beheerder_id: uuid.UUID) -> None:
        _app, sessie = _geactiveerd(beheerder_id)
        assert client.post("/auth/app-lock/ontkoppelen", headers=_bearer(sessie["access_token"])).status_code == 204
        assert _koppeling(sessie).status_code == 401  # apparaat-poort in get_current_gebruiker


class TestLegacyLoginHint:
    def test_accordeur_login_401_draagt_de_hint_voor_iedereen(self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        app, _sessie = _geactiveerd(beheerder_id)
        # account zonder wachtwoord (app-auth) én een onbekend adres: identieke tekst (0022)
        with_account = client.post(
            "/auth/accordeur/login", json={"e_mail": app["gebruiker_id"] + "@x", "wachtwoord": "x" * 12}
        )
        onbekend = client.post("/auth/accordeur/login", json={"e_mail": f"{uuid.uuid4()}@x.nl", "wachtwoord": "x" * 12})
        assert with_account.status_code == onbekend.status_code == 401
        assert with_account.json()["detail"] == onbekend.json()["detail"]
        assert LEGACY_LOGIN_APP_HINT in onbekend.json()["detail"] and "versie 1.1" in onbekend.json()["detail"]
        # Casus Romy 17-09: mét store-link in de 401 zodra die geconfigureerd is ("Update de app via de App Store").
        monkeypatch.setattr(settings, "store_link_ios", "https://apps.apple.com/nl/app/id123")
        weer = client.post("/auth/accordeur/login", json={"e_mail": "onbekend@x.nl", "wachtwoord": "x"})
        assert weer.status_code == 401 and "update via de App Store: https://apps.apple.com/nl/app/id123" in weer.json()["detail"]
