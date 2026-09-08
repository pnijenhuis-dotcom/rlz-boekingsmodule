"""App-auth zonder passkey en TOTP (besluit Peter 08-09-2026, migratie 0125; app/auth/app_activatie.py).

Het enige toegangspad van de app: uitnodiging → activatie op dít toestel (link óf 8-tekens activatiecode) →
5-cijferige toegangscode (lokaal anker, komt hier nooit voor). Deze suite dekt de serverkant: code-primitieven,
`POST /auth/app/activeren` (link, code, normalisatie, eenmalig, 72 u, tweede toestel 409, 429 per uitnodiging en
per IP, kantoor-rol/geblokkeerd 400, demo_herbruikbaar, audit zonder code, toestel-rij, body-levering alleen mét
aankondiging), de sessie op de toestel-rij (rotatie, kill-switch, 5×-fout-melding, ontkoppelen,
toegangscode-gewijzigd), de sunset van de legacy-app-routes, het herstel-link-pad, mail mét code en
`uitnodiging_info.flow == "app"`. De kantoor-webapp blijft byte-identiek (aparte asserts)."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import app_activatie, service
from app.config import settings
from app.db.models import GebruikerRol
from app.main import app as fastapi_app
from app.security.tokens import create_access_token
from tests.auth.test_activatie_atomair import _audit, _gebruiker
from tests.auth.test_webauthn_cadans import _bearer, _beheerder_bearer

# Eigen client (patroon test_native_refresh): de gedeelde cadans-client draagt refresh-cookies van web-logins
# uit andere modules en `_lees_refresh_token` leest de cookie vóór de X-Refresh-Token-header.
client = TestClient(fastapi_app)

APP = {"X-Native-Client": "1"}
SLOT = {"X-App-Slot": "1"}


def _nodig_uit(
    beheerder_id: uuid.UUID,
    *,
    rol: str = "klant_accordeur",
    administratie_id: uuid.UUID | None = None,
    e_mail: str | None = None,
    naam: str = "App Gebruiker",
) -> dict:
    resp = client.post(
        "/auth/uitnodigingen",
        json={
            "naam": naam,
            "e_mail": e_mail or f"{uuid.uuid4()}@test.local",
            "rol": rol,
            "administratie_ids": [str(administratie_id)] if administratie_id else [],
        },
        headers=_beheerder_bearer(beheerder_id),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _activeer(body: dict, *, headers: dict | None = None, ip: str | None = None):
    h = dict(APP if headers is None else headers)
    if ip:
        h["X-Forwarded-For"] = f"{ip}, 10.0.0.1"
    return client.post("/auth/app/activeren", json=body, headers=h)


def _toestel(admin_engine: Engine, gebruiker_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT id, soort, platform, apparaat_naam, public_key, credential_id, ingetrokken_op, "
                "laatst_gebruikt_op, niet_meer_gebruikt_op FROM platform.webauthn_credential "
                "WHERE gebruiker_id = :g AND soort = 'toestel' ORDER BY aangemaakt_op DESC LIMIT 1"
            ),
            {"g": gebruiker_id},
        ).one()
    return dict(rij._mapping)


def _audit_op(admin_engine: Engine, record_id: uuid.UUID, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            r[0] or {}
            for r in conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event "
                    "WHERE record_id = :id AND actie = :a ORDER BY tijdstip"
                ),
                {"id": record_id, "a": actie},
            ).all()
        ]


def _uitnodiging_rij(admin_engine: Engine, uitnodiging_id: str) -> dict:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT gebruikt_op, verloopt_op, activatiecode_hash, activatiecode_pogingen, demo_herbruikbaar "
                "FROM platform.uitnodiging WHERE id = :id"
            ),
            {"id": uitnodiging_id},
        ).one()
    return dict(rij._mapping)


# --- code-primitieven -------------------------------------------------------------------------------------


class TestActivatiecodePrimitieven:
    def test_alfabet_32_tekens_zonder_verwarrende(self) -> None:
        a = app_activatie.ACTIVATIECODE_ALFABET
        assert len(a) == 32 and len(set(a)) == 32
        assert not set("0O1I") & set(a)
        assert a == "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def test_genereer_en_formatteer(self) -> None:
        code = app_activatie.genereer_activatiecode()
        assert len(code) == 8 and set(code) <= set(app_activatie.ACTIVATIECODE_ALFABET)
        weergave = app_activatie.formatteer_activatiecode(code)
        assert weergave == f"{code[:4]}-{code[4:]}"
        assert len({app_activatie.genereer_activatiecode() for _ in range(50)}) > 45

    def test_normalisatie_en_hash(self) -> None:
        assert app_activatie.normaliseer_activatiecode(" ab cd-EF gh ") == "ABCDEFGH"
        assert app_activatie.normaliseer_activatiecode("abcd–efgh") == "ABCDEFGH"  # en-dash
        assert app_activatie.hash_activatiecode("abcd-efgh") == app_activatie.hash_activatiecode("ABCDEFGH")
        assert len(app_activatie.hash_activatiecode("ABCDEFGH")) == 64

    def test_formaat_validatie(self) -> None:
        assert app_activatie.is_geldig_activatiecode_formaat("ABCD-EFGH")
        assert not app_activatie.is_geldig_activatiecode_formaat("ABCD-EFG")  # 7
        assert not app_activatie.is_geldig_activatiecode_formaat("ABCD-EFG0")  # 0 niet in alfabet
        assert not app_activatie.is_geldig_activatiecode_formaat("ABCD-EFGI")  # I niet in alfabet
        assert not app_activatie.is_geldig_activatiecode_formaat("")


# --- uitnodiging draagt de code -------------------------------------------------------------------------


class TestUitnodigingMetCode:
    def test_app_rol_krijgt_code_kantoor_niet(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        app = _nodig_uit(beheerder_id)
        assert app["activatiecode"] and len(app["activatiecode"]) == 9 and app["activatiecode"][4] == "-"
        rij = _uitnodiging_rij(admin_engine, app["uitnodiging_id"])
        assert rij["activatiecode_hash"] == app_activatie.hash_activatiecode(app["activatiecode"])
        assert app["activatiecode"].replace("-", "") not in json.dumps(
            _audit_op(admin_engine, uuid.UUID(app["uitnodiging_id"]), "gebruiker_uitgenodigd")
        )
        kantoor = _nodig_uit(beheerder_id, rol="boekhouding")
        assert kantoor["activatiecode"] is None
        assert _uitnodiging_rij(admin_engine, kantoor["uitnodiging_id"])["activatiecode_hash"] is None

    def test_veldrol_krijgt_ook_code(self, beheerder_id: uuid.UUID) -> None:
        assert _nodig_uit(beheerder_id, rol="zzper")["activatiecode"]

    def test_uitnodiging_info_flow_is_app(self, beheerder_id: uuid.UUID) -> None:
        app = _nodig_uit(beheerder_id)
        resp = client.get("/auth/uitnodigingen/info", params={"token": app["token"]})
        assert resp.status_code == 200
        assert resp.json()["flow"] == "app"
        kantoor = _nodig_uit(beheerder_id, rol="boekhouding")
        assert client.get("/auth/uitnodigingen/info", params={"token": kantoor["token"]}).json()["flow"] == "totp"

    def test_mail_draagt_code_alleen_voor_app_rol(
        self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.berichten import mail

        verzonden: list[dict] = []
        monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))
        app = _nodig_uit(beheerder_id)
        assert app["mail_verzonden"] is True
        tekst = verzonden[-1]["tekst"]
        assert "activatiecode" in tekst and app["activatiecode"] in tekst
        assert "op een ander toestel" in tekst and "zelfde geldigheid" in tekst
        _nodig_uit(beheerder_id, rol="boekhouding")
        assert "activatiecode" not in verzonden[-1]["tekst"]


# --- activeren --------------------------------------------------------------------------------------------


class TestActiveren:
    def test_via_link_maakt_toestel_en_sessie(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        app = _nodig_uit(beheerder_id, naam="Jan")
        resp = _activeer({"token": app["token"], "toestel_naam": "iPhone van Jan", "platform": "ios"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["access_token"] and body["refresh_token"] and body["token_type"] == "bearer"
        assert body["naam"] == "Jan" and body["herstel"] is False
        assert "refresh_token=" not in resp.headers.get("set-cookie", "")  # geen cookie, alleen body
        assert resp.headers["cache-control"] == "no-store"
        gid = uuid.UUID(app["gebruiker_id"])
        assert _gebruiker(admin_engine, [r for r in [None]][0] or _e_mail_van(admin_engine, gid))["status"] == "actief"
        toestel = _toestel(admin_engine, gid)
        assert toestel["soort"] == "toestel" and toestel["platform"] == "ios"
        assert toestel["apparaat_naam"] == "iPhone van Jan"
        assert bytes(toestel["public_key"]) == b"toestel" and toestel["laatst_gebruikt_op"] is not None
        assert body["apparaat_credential_id"] == base64.urlsafe_b64encode(
            bytes(toestel["credential_id"])
        ).decode().rstrip("=")
        assert _uitnodiging_rij(admin_engine, app["uitnodiging_id"])["gebruikt_op"] is not None
        # Audit: toestel_geactiveerd op de toestel-rij, activatie_afgerond via toestel — nooit de code.
        events = _audit_op(admin_engine, toestel["id"], "toestel_geactiveerd")
        assert len(events) == 1 and events[0]["via"] == "link" and events[0]["platform"] == "ios"
        assert app["activatiecode"].replace("-", "") not in json.dumps(events)
        afgerond = _audit_op(admin_engine, gid, "activatie_afgerond")
        assert afgerond and afgerond[0]["via"] == "toestel" and afgerond[0]["zonder_wachtwoord"] is True
        assert _gebruiker(admin_engine, _e_mail_van(admin_engine, gid))["wachtwoord_hash"] is None

    def test_via_code_met_normalisatie(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        app = _nodig_uit(beheerder_id)
        rommelig = f"  {app['activatiecode'].lower().replace('-', ' - ')} "
        resp = _activeer({"activatiecode": rommelig, "platform": "android"}, headers=SLOT)
        assert resp.status_code == 200, resp.text
        toestel = _toestel(admin_engine, uuid.UUID(app["gebruiker_id"]))
        assert toestel["platform"] == "android"
        events = _audit_op(admin_engine, toestel["id"], "toestel_geactiveerd")
        assert events[0]["via"] == "code"
        assert app["activatiecode"].replace("-", "") not in json.dumps(events)

    def test_zonder_aankondiging_400_met_slot_of_native_ok(self, beheerder_id: uuid.UUID) -> None:
        app = _nodig_uit(beheerder_id)
        resp = client.post("/auth/app/activeren", json={"activatiecode": app["activatiecode"]})
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Deze activatie is alleen voor de app"
        assert _activeer({"activatiecode": app["activatiecode"]}, headers=SLOT).status_code == 200

    def test_precies_een_ingang_anders_422(self, beheerder_id: uuid.UUID) -> None:
        app = _nodig_uit(beheerder_id)
        assert _activeer({}).status_code == 422
        assert _activeer({"token": app["token"], "activatiecode": app["activatiecode"]}).status_code == 422
        assert _activeer({"activatiecode": app["activatiecode"], "onbekend": 1}).status_code == 422
        assert _activeer({"activatiecode": app["activatiecode"], "platform": "windows"}).status_code == 422

    def test_eenmalig_tweede_toestel_409(self, beheerder_id: uuid.UUID) -> None:
        app = _nodig_uit(beheerder_id)
        assert _activeer({"activatiecode": app["activatiecode"]}).status_code == 200
        resp = _activeer({"activatiecode": app["activatiecode"]}, ip="203.0.113.9")
        assert resp.status_code == 409
        assert "al op een ander toestel gebruikt" in resp.json()["detail"]
        # Ook via de link: verbruikt is verbruikt.
        assert _activeer({"token": app["token"]}, ip="203.0.113.10").status_code == 409

    def test_onbekend_ongeldig_en_verlopen_geven_dezelfde_400(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        onbekend = _activeer({"activatiecode": "ABCD-EFGH"}, ip="198.51.100.1")
        assert onbekend.status_code == 400
        generiek = onbekend.json()["detail"]
        assert generiek == "Deze activatiecode of link is niet (meer) geldig"
        kapot = _activeer({"activatiecode": "0000-1111"}, ip="198.51.100.2")  # buiten alfabet
        assert kapot.status_code == 400 and kapot.json()["detail"] == generiek
        link = _activeer({"token": "geen-echte-link"}, ip="198.51.100.3")
        assert link.status_code == 400 and link.json()["detail"] == generiek
        app = _nodig_uit(beheerder_id)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.uitnodiging SET verloopt_op = now() - interval '1 minute' WHERE id = :id"),
                {"id": app["uitnodiging_id"]},
            )
        verlopen = _activeer({"activatiecode": app["activatiecode"]}, ip="198.51.100.4")
        assert verlopen.status_code == 400 and verlopen.json()["detail"] == generiek

    def test_kantoorrol_400(self, beheerder_id: uuid.UUID) -> None:
        kantoor = _nodig_uit(beheerder_id, rol="boekhouding")
        resp = _activeer({"token": kantoor["token"]})
        assert resp.status_code == 400
        assert "alleen voor app-gebruikers" in resp.json()["detail"]

    def test_geblokkeerd_400(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        app = _nodig_uit(beheerder_id)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.gebruiker SET status = 'geblokkeerd' WHERE id = :id"), {"id": app["gebruiker_id"]}
            )
        resp = _activeer({"activatiecode": app["activatiecode"]})
        assert resp.status_code == 400
        assert "geblokkeerd" in resp.json()["detail"]
        assert "toestel_activatie_geweigerd" in _audit(admin_engine, uuid.UUID(app["gebruiker_id"]))

    def test_429_per_uitnodiging(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        """Vijf pogingen op dezelfde uitnodiging (steeds een ander IP, zodat de IP-rem niet eerst bijt), de
        zesde is 429 — óók met een correcte code."""
        kantoor = _nodig_uit(beheerder_id, rol="boekhouding")  # elke poging faalt op de rolpoort
        for i in range(5):
            assert _activeer({"token": kantoor["token"]}, ip=f"192.0.2.{i + 1}").status_code == 400
        resp = _activeer({"token": kantoor["token"]}, ip="192.0.2.99")
        assert resp.status_code == 429
        assert "Te veel pogingen" in resp.json()["detail"]
        assert _uitnodiging_rij(admin_engine, kantoor["uitnodiging_id"])["activatiecode_pogingen"] == 5
        # Venster verlopen → teller reset, weer een gewone 400.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE platform.uitnodiging SET activatiecode_pogingen_vanaf = now() - interval '61 minutes' "
                    "WHERE id = :id"
                ),
                {"id": kantoor["uitnodiging_id"]},
            )
        assert _activeer({"token": kantoor["token"]}, ip="192.0.2.100").status_code == 400

    def test_429_per_ip_en_ander_ip_werkt_nog(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        for _ in range(5):
            assert (
                _activeer({"activatiecode": app_activatie.genereer_activatiecode()}, ip="203.0.113.50").status_code
                == 400
            )
        app = _nodig_uit(beheerder_id)
        resp = _activeer({"activatiecode": app["activatiecode"]}, ip="203.0.113.50")
        assert resp.status_code == 429  # zelfs de juiste code komt er niet meer door
        with admin_engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM platform.activatiecode_poging WHERE ip = '203.0.113.50'")
            ).scalar_one()
        assert n == 5  # de 429 zelf voegt geen misser toe
        assert _activeer({"activatiecode": app["activatiecode"]}, ip="203.0.113.51").status_code == 200

    def test_ip_uit_x_forwarded_for_eerste_hop(self, admin_engine: Engine) -> None:
        resp = client.post(
            "/auth/app/activeren",
            json={"activatiecode": "ABCD-EFGH"},
            headers={**APP, "X-Forwarded-For": "  93.184.216.34 , 10.1.2.3"},
        )
        assert resp.status_code == 400
        with admin_engine.connect() as conn:
            ips = conn.execute(text("SELECT ip FROM platform.activatiecode_poging")).scalars().all()
        assert ips == ["93.184.216.34"]


def _e_mail_van(admin_engine: Engine, gebruiker_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT e_mail FROM platform.gebruiker WHERE id = :id"), {"id": gebruiker_id}
        ).scalar_one()


# --- demo_herbruikbaar (alleen het review-demo-account) -----------------------------------------------------


def _maak_demo_code(
    admin_engine: Engine, gebruiker_id: uuid.UUID, beheerder_id: uuid.UUID, *, demo: bool = True
) -> str:
    code = app_activatie.genereer_activatiecode()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.uitnodiging (id, gebruiker_id, token_hash, aangemaakt_door, verloopt_op, soort, "
                "activatiecode_hash, demo_herbruikbaar) "
                "VALUES (:id, :g, :th, :b, '2099-01-01', 'wachtwoord_herstel', :h, :d)"
            ),
            {
                "id": uuid.uuid4(),
                "g": gebruiker_id,
                "th": uuid.uuid4().hex,
                "b": beheerder_id,
                "h": app_activatie.hash_activatiecode(code),
                "d": demo,
            },
        )
    return code


class TestDemoHerbruikbaar:
    def test_review_account_code_werkt_op_meerdere_toestellen(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        app = _nodig_uit(beheerder_id, e_mail=app_activatie.REVIEW_DEMO_EMAIL, naam="App-review")
        eerste = _activeer({"token": app["token"], "platform": "ios"})
        assert eerste.status_code == 200, eerste.text
        gid = uuid.UUID(app["gebruiker_id"])
        code = _maak_demo_code(admin_engine, gid, beheerder_id)
        toestel_a = _activeer(
            {"activatiecode": code, "toestel_naam": "iPhone reviewer", "platform": "ios"}, ip="203.0.113.70"
        )
        toestel_b = _activeer(
            {"activatiecode": code, "toestel_naam": "Pixel reviewer", "platform": "android"}, ip="203.0.113.71"
        )
        assert toestel_a.status_code == 200 and toestel_b.status_code == 200
        assert toestel_a.json()["herstel"] is True
        # Code niet verbruikt, eerdere sessies NIET ingetrokken.
        with admin_engine.connect() as conn:
            gebruikt = conn.execute(
                text("SELECT gebruikt_op FROM platform.uitnodiging WHERE demo_herbruikbaar AND gebruiker_id = :g"),
                {"g": gid},
            ).scalar_one()
            open_sessies = conn.execute(
                text("SELECT count(*) FROM platform.refresh_token WHERE gebruiker_id = :g AND ingetrokken_op IS NULL"),
                {"g": gid},
            ).scalar_one()
        assert gebruikt is None and open_sessies == 3
        # Alle drie de sessies roteren nog.
        for r in (eerste, toestel_a, toestel_b):
            assert (
                client.post(
                    "/auth/token/vernieuwen", headers={"X-Refresh-Token": r.json()["refresh_token"]}
                ).status_code
                == 200
            )

    def test_vlag_op_ander_account_wordt_genegeerd(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        app = _nodig_uit(beheerder_id)
        assert _activeer({"token": app["token"]}).status_code == 200
        code = _maak_demo_code(admin_engine, uuid.UUID(app["gebruiker_id"]), beheerder_id, demo=True)
        assert _activeer({"activatiecode": code}, ip="203.0.113.80").status_code == 200
        tweede = _activeer({"activatiecode": code}, ip="203.0.113.81")
        assert tweede.status_code == 409  # gewoon verbruikt: geen review-adres, dus geen hergebruik


# --- sessie op de toestel-rij -----------------------------------------------------------------------------------


def _geactiveerd(beheerder_id: uuid.UUID, administratie_id: uuid.UUID | None = None) -> tuple[dict, dict]:
    app = _nodig_uit(beheerder_id, administratie_id=administratie_id)
    resp = _activeer({"activatiecode": app["activatiecode"], "toestel_naam": "Telefoon", "platform": "ios"})
    assert resp.status_code == 200, resp.text
    return app, resp.json()


class TestToestelSessie:
    def test_rotatie_zet_laatst_gebruikt_en_geen_ontgrendeling(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        app, sessie = _geactiveerd(beheerder_id)
        gid = uuid.UUID(app["gebruiker_id"])
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE platform.webauthn_credential SET laatst_gebruikt_op = now() - interval '3 days' "
                    "WHERE gebruiker_id = :g"
                ),
                {"g": gid},
            )
        resp = client.post("/auth/token/vernieuwen", headers={"X-Refresh-Token": sessie["refresh_token"]})
        assert resp.status_code == 200, resp.text
        assert "ontgrendeling_nodig" not in resp.json()  # toestel-rij: geen 24-uurs-cadans meer
        assert resp.json()["refresh_token"] != sessie["refresh_token"]
        toestel = _toestel(admin_engine, gid)
        assert datetime.now(UTC) - toestel["laatst_gebruikt_op"] < timedelta(minutes=1)
        # Ook via X-App-Slot komt het paar in de body.
        resp2 = client.post("/auth/token/vernieuwen", headers={**SLOT, "X-Refresh-Token": resp.json()["refresh_token"]})
        assert resp2.status_code == 200 and resp2.json()["refresh_token"]

    def test_x_app_slot_op_gewone_requests_is_onschadelijk(self, beheerder_id: uuid.UUID) -> None:
        """De PWA stuurt in slotmodus `X-App-Slot: 1` op ÁLLE requests (zoals native X-Native-Client). Alleen de
        token-levering (body i.p.v. cookie) mag daarvan afhangen — geen enkel geauthenticeerd endpoint geeft een
        fout."""
        _, sessie = _geactiveerd(beheerder_id)
        headers = {**SLOT, **_bearer(sessie["access_token"])}
        assert client.get("/auth/administraties", headers=headers).status_code == 200
        assert client.get("/auth/accordeur/voorwaarden", headers=headers).status_code == 200
        assert client.get("/auth/mijn/apparaten", headers=headers).status_code == 200
        assert client.get("/auth/mijn/apparaten", headers=headers).json()["apparaten"][0]["soort"] == "toestel"
        # Kantoor-sessie mét de header: ook gewoon 200 (de header is geen poort).
        kantoor = {**SLOT, **_beheerder_bearer(beheerder_id)}
        assert client.get("/auth/administraties", headers=kantoor).status_code == 200
        assert client.get("/auth/gebruikers", headers=kantoor).status_code == 200

    def test_kill_switch_bijt_per_request(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        app, sessie = _geactiveerd(beheerder_id)
        headers = _bearer(sessie["access_token"])
        assert client.get("/auth/accordeur/voorwaarden", headers=headers).status_code == 200
        toestel = _toestel(admin_engine, uuid.UUID(app["gebruiker_id"]))
        resp = client.post(f"/auth/apparaten/{toestel['id']}/intrekken", headers=_beheerder_bearer(beheerder_id))
        assert resp.status_code == 204
        assert client.get("/auth/accordeur/voorwaarden", headers=headers).status_code == 401
        assert (
            client.post("/auth/token/vernieuwen", headers={"X-Refresh-Token": sessie["refresh_token"]}).status_code
            == 401
        )

    def test_vijf_keer_fout_melding_trekt_in_met_audit(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        app, sessie = _geactiveerd(beheerder_id)
        resp = client.post("/auth/app-lock/uitgesloten", json={"credential_id": sessie["apparaat_credential_id"]})
        assert resp.status_code == 204
        toestel = _toestel(admin_engine, uuid.UUID(app["gebruiker_id"]))
        assert toestel["ingetrokken_op"] is not None
        assert _audit_op(admin_engine, toestel["id"], "app_lock_uitgesloten") == [{"aanleiding": "5_foute_codes"}]
        assert client.get("/auth/accordeur/voorwaarden", headers=_bearer(sessie["access_token"])).status_code == 401
        # Hulpvraag werkt óók na de uitsluiting (204, geen bestaans-lek).
        assert (
            client.post("/auth/app-lock/hulp", json={"credential_id": sessie["apparaat_credential_id"]}).status_code
            == 204
        )

    def test_toegangscode_gewijzigd_event(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        app, sessie = _geactiveerd(beheerder_id)
        resp = client.post("/auth/app/toegangscode-gewijzigd", headers=_bearer(sessie["access_token"]))
        assert resp.status_code == 204
        toestel = _toestel(admin_engine, uuid.UUID(app["gebruiker_id"]))
        events = _audit_op(admin_engine, toestel["id"], "toegangscode_gewijzigd")
        assert events == [{"soort": "toestel"}]
        # Sessie zonder apparaatbinding (kantoor) → 400.
        kantoor = create_access_token(beheerder_id, rol="beheerder")
        assert client.post("/auth/app/toegangscode-gewijzigd", headers=_bearer(kantoor)).status_code == 400

    def test_ontkoppelen(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        app, sessie = _geactiveerd(beheerder_id)
        headers = _bearer(sessie["access_token"])
        assert client.post("/auth/app-lock/ontkoppelen", headers=headers).status_code == 204
        assert _toestel(admin_engine, uuid.UUID(app["gebruiker_id"]))["ingetrokken_op"] is not None
        assert client.post("/auth/app-lock/ontkoppelen", headers=headers).status_code == 401

    def test_apparaten_dto_toont_toestel_en_kantooroverzicht_lekt_niet(self, beheerder_id: uuid.UUID) -> None:
        app, _ = _geactiveerd(beheerder_id)
        resp = client.get(f"/auth/gebruikers/{app['gebruiker_id']}/apparaten", headers=_beheerder_bearer(beheerder_id))
        assert resp.status_code == 200
        [apparaat] = resp.json()["apparaten"]
        assert apparaat["soort"] == "toestel" and apparaat["platform"] == "ios"
        assert apparaat["niet_meer_gebruikt_op"] is None and apparaat["apparaat_naam"] == "Telefoon"
        kantoor = client.get("/auth/apparaten/kantoor", headers=_beheerder_bearer(beheerder_id))
        assert kantoor.status_code == 200
        assert all(a["soort"] == "passkey" for a in kantoor.json()["apparaten"])
        assert apparaat["id"] not in {a["id"] for a in kantoor.json()["apparaten"]}


# --- herstel-link-pad ------------------------------------------------------------------------------------------


class TestHerstelLink:
    def test_herstel_koppelt_nieuw_toestel_en_trekt_oude_sessies_in(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        app, oud = _geactiveerd(beheerder_id)
        gid = uuid.UUID(app["gebruiker_id"])
        resp = client.post(f"/auth/gebruikers/{gid}/herstel-link", headers=_beheerder_bearer(beheerder_id))
        assert resp.status_code == 200, resp.text
        herstel = resp.json()
        assert herstel["activatiecode"] and herstel["activatiecode"] != app["activatiecode"]
        # De oude code is dood (vervallen door de herstel-link) — generieke 400.
        assert _activeer({"activatiecode": app["activatiecode"]}, ip="203.0.113.90").status_code in (400, 409)
        nieuw = _activeer({"activatiecode": herstel["activatiecode"], "platform": "android"}, ip="203.0.113.91")
        assert nieuw.status_code == 200, nieuw.text
        assert nieuw.json()["herstel"] is True
        # Oude sessie én oud toestel ingetrokken (kill-switch-pad: het oude toestel valt op de apparaat-poort en
        # triggert géén revoke-all van de nieuwe sessie); de nieuwe sessie werkt en blijft werken.
        oud_refresh = client.post("/auth/token/vernieuwen", headers={"X-Refresh-Token": oud["refresh_token"]})
        assert oud_refresh.status_code == 401
        assert "apparaat is ingetrokken" in oud_refresh.json()["detail"]
        assert client.get("/auth/accordeur/voorwaarden", headers=_bearer(oud["access_token"])).status_code == 401
        nieuw_refresh = client.post(
            "/auth/token/vernieuwen", headers={"X-Refresh-Token": nieuw.json()["refresh_token"]}
        )
        assert nieuw_refresh.status_code == 200, nieuw_refresh.text
        hersteld = _audit_op(admin_engine, gid, "wachtwoord_hersteld")
        assert hersteld and hersteld[-1]["via"] == "toestel"
        with admin_engine.connect() as conn:
            toestellen = conn.execute(
                text(
                    "SELECT platform, ingetrokken_op IS NOT NULL FROM platform.webauthn_credential "
                    "WHERE gebruiker_id = :g ORDER BY aangemaakt_op"
                ),
                {"g": gid},
            ).all()
            aanleidingen = (
                conn.execute(
                    text(
                        "SELECT nieuwe_waarde->>'aanleiding' FROM platform.audit_event "
                        "WHERE actie = 'apparaat_ingetrokken' AND actor_id = :g"
                    ),
                    {"g": gid},
                )
                .scalars()
                .all()
            )
        assert [tuple(r) for r in toestellen] == [("ios", True), ("android", False)]
        assert aanleidingen == ["herstel_nieuw_toestel"]

    def test_herstelmail_draagt_code(self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.berichten import mail

        verzonden: list[dict] = []
        monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))
        app, _ = _geactiveerd(beheerder_id)
        resp = client.post(
            f"/auth/gebruikers/{app['gebruiker_id']}/herstel-link", headers=_beheerder_bearer(beheerder_id)
        )
        assert resp.status_code == 200
        assert resp.json()["activatiecode"] in verzonden[-1]["tekst"]
        assert "wachtwoord" not in verzonden[-1]["tekst"].lower()
        assert "herstel=1" in verzonden[-1]["tekst"]

    def test_opnieuw_mailen_geeft_verse_code(self, beheerder_id: uuid.UUID) -> None:
        app = _nodig_uit(beheerder_id)
        resp = client.post(
            f"/auth/gebruikers/{app['gebruiker_id']}/uitnodiging-opnieuw", headers=_beheerder_bearer(beheerder_id)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["activatiecode"] and resp.json()["activatiecode"] != app["activatiecode"]
        assert (
            _activeer({"activatiecode": app["activatiecode"]}, ip="203.0.113.95").status_code == 400
        )  # oude vervallen
        assert _activeer({"activatiecode": resp.json()["activatiecode"]}, ip="203.0.113.96").status_code == 200


# --- sunset legacy-app-routes ------------------------------------------------------------------------------------

LEGACY_ROUTES = [
    ("/auth/accordeur/login", {"e_mail": "x@test.local", "wachtwoord": "een-heel-lang-wachtwoord"}),
    ("/auth/accordeur/passkey-login/opties", {"e_mail": "x@test.local"}),
    ("/auth/accordeur/passkey-login/voltooien", {"e_mail": "x@test.local", "dev_stub": True}),
    ("/auth/uitnodigingen/activatie-zonder-wachtwoord", {"token": "nep"}),
    ("/auth/token/vernieuwen/ontgrendelen", {"dev_stub": True}),
]
LEGACY_ROUTES_ZONDER_BODY = [
    "/auth/webauthn/registratie/opties",
    "/auth/webauthn/registratie/voltooien",
    "/auth/webauthn/login/opties",
    "/auth/webauthn/login/voltooien",
    "/auth/token/vernieuwen/ontgrendel-opties",
]


class TestSunset:
    def test_headers_voor_de_datum(self) -> None:
        for pad, body in LEGACY_ROUTES:
            resp = client.post(pad, json=body)
            assert resp.status_code != 410, pad
            assert resp.headers.get("deprecation") == "true", pad
            assert "08 Oct 2026" in resp.headers.get("sunset", ""), (pad, resp.headers.get("sunset"))
        for pad in LEGACY_ROUTES_ZONDER_BODY:
            resp = client.post(pad, json={}, headers=_bearer("geen-token"))
            assert resp.status_code != 410, pad
            assert resp.headers.get("deprecation") == "true", pad

    def test_410_na_de_datum(self, monkeypatch: pytest.MonkeyPatch, beheerder_id: uuid.UUID) -> None:
        monkeypatch.setattr(settings, "app_legacy_auth_sunset_op", date(2026, 1, 1))
        for pad, body in LEGACY_ROUTES:
            resp = client.post(pad, json=body)
            assert resp.status_code == 410, (pad, resp.status_code)
            assert "activatiecode uit je uitnodiging" in resp.json()["detail"]
            assert resp.headers.get("deprecation") == "true"
        for pad in LEGACY_ROUTES_ZONDER_BODY:
            assert client.post(pad, json={}, headers=_bearer("geen-token")).status_code == 410, pad
        # /uitnodigingen/accepteren: 410 alleen voor app-rollen — kantoor accepteert gewoon.
        app = _nodig_uit(beheerder_id)
        resp = client.post(
            "/auth/uitnodigingen/accepteren", json={"token": app["token"], "wachtwoord": "een-heel-lang-wachtwoord"}
        )
        assert resp.status_code == 410
        kantoor = _nodig_uit(beheerder_id, rol="boekhouding")
        resp = client.post(
            "/auth/uitnodigingen/accepteren", json={"token": kantoor["token"], "wachtwoord": "een-heel-lang-wachtwoord"}
        )
        assert resp.status_code == 200 and resp.json()["soort"] == "totp"
        assert "deprecation" not in resp.headers
        # De nieuwe app-route zelf kent geen sunset.
        resp = _activeer({"activatiecode": app["activatiecode"]})
        assert resp.status_code == 200 and "deprecation" not in resp.headers

    def test_kantoor_login_byte_identiek(self, beheerder_id: uuid.UUID) -> None:
        import time

        import pyotp

        from app.security.totp import STEP_SECONDS
        from tests.auth.test_refresh_cookie import _activeer_gebruiker

        e_mail, wachtwoord, secret = _activeer_gebruiker(beheerder_id)
        code = pyotp.TOTP(secret).at(time.time() + STEP_SECONDS)
        web = TestClient(fastapi_app)  # eigen cookie-jar: de web-login mag onze app-client niet vervuilen
        resp = web.post("/auth/login", json={"e_mail": e_mail, "wachtwoord": wachtwoord, "totp_code": code})
        assert resp.status_code == 200
        assert set(resp.json()) == {"access_token", "token_type"}
        assert "deprecation" not in resp.headers and "sunset" not in resp.headers
        assert "refresh_token=" in resp.headers.get("set-cookie", "")
        # Kantoor-passkey-opties: geen sunset-header (0020 blijft daar gelden).
        resp = web.post("/auth/webauthn/kantoor/login/opties", json={"e_mail": e_mail})
        assert "deprecation" not in resp.headers


# --- CLI: legacy app-passkeys markeren ---------------------------------------------------------------------------


def _maak_passkey_rij(admin_engine: Engine, gebruiker_id: uuid.UUID) -> uuid.UUID:
    rij_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.webauthn_credential "
                "(id, gebruiker_id, credential_id, public_key, sign_count, apparaat_naam) "
                "VALUES (:id, :g, :cred, :pub, 0, 'Oude iPhone')"
            ),
            {"id": rij_id, "g": gebruiker_id, "cred": rij_id.bytes, "pub": b"pub"},
        )
    return rij_id


class TestAppPasskeysMarkeren:
    def test_markeert_alleen_app_passkeys_niets_ingetrokken(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        app, _ = _geactiveerd(beheerder_id)  # toestel-rij: mag NIET gemarkeerd worden
        gid = uuid.UUID(app["gebruiker_id"])
        passkey_app = _maak_passkey_rij(admin_engine, gid)
        passkey_kantoor = _maak_passkey_rij(admin_engine, beheerder_id)
        veld = service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam="Z",
            e_mail=f"{uuid.uuid4()}@test.local",
            rol=GebruikerRol.ZZPER,
            administratie_ids=[],
        )
        passkey_veld = _maak_passkey_rij(admin_engine, veld.gebruiker_id)

        assert app_activatie.markeer_app_passkeys(dry_run=True) == {"klant_accordeur": 1, "zzper": 1}
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM platform.webauthn_credential WHERE niet_meer_gebruikt_op IS NOT NULL")
                ).scalar_one()
                == 0
            )
        assert app_activatie.markeer_app_passkeys() == {"klant_accordeur": 1, "zzper": 1}
        assert app_activatie.markeer_app_passkeys() == {}  # idempotent
        with admin_engine.connect() as conn:
            rijen = {
                r[0]: (r[1], r[2])
                for r in conn.execute(
                    text(
                        "SELECT id, niet_meer_gebruikt_op IS NOT NULL, ingetrokken_op FROM platform.webauthn_credential"
                    )
                ).all()
            }
        assert rijen[passkey_app] == (True, None) and rijen[passkey_veld] == (True, None)
        assert rijen[passkey_kantoor] == (False, None)
        toestel = _toestel(admin_engine, gid)
        assert toestel["niet_meer_gebruikt_op"] is None
        events = _audit_op(admin_engine, passkey_app, "passkey_niet_meer_gebruikt")
        assert len(events) == 1 and events[0]["ingetrokken_op_ongemoeid"] is True
        # Zichtbaar in de apparaten-DTO.
        resp = client.get(f"/auth/gebruikers/{gid}/apparaten", headers=_beheerder_bearer(beheerder_id))
        per_id = {a["id"]: a for a in resp.json()["apparaten"]}
        assert (
            per_id[str(passkey_app)]["niet_meer_gebruikt_op"] is not None
            and per_id[str(passkey_app)]["soort"] == "passkey"
        )

    def test_cli_commando(
        self, beheerder_id: uuid.UUID, admin_engine: Engine, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from app import cli

        app = _nodig_uit(beheerder_id)
        _maak_passkey_rij(admin_engine, uuid.UUID(app["gebruiker_id"]))
        assert cli.main(["app-passkeys-markeren", "--dry-run"]) == 0
        assert "[dry-run]: 1 passkey-rij" in capsys.readouterr().out
        assert cli.main(["app-passkeys-markeren"]) == 0
        uit = capsys.readouterr().out
        assert "1 passkey-rij(en)" in uit and "klant_accordeur: 1" in uit


# --- seed-script review-demo: herbruikbare activatiecode --------------------------------------------------------


def _laad_seed_script():
    import importlib.util
    from pathlib import Path as _Path

    pad = _Path(__file__).resolve().parents[2] / "scripts" / "cloud_seed_review_demo.py"
    spec = importlib.util.spec_from_file_location("cloud_seed_review_demo", pad)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSeedReviewDemoActivatiecode:
    def test_zet_demo_activatiecode_herbruikbaar_en_een_geldige_code(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        seed = _laad_seed_script()
        assert seed.REVIEW_EMAIL == app_activatie.REVIEW_DEMO_EMAIL
        app = _nodig_uit(beheerder_id, e_mail=app_activatie.REVIEW_DEMO_EMAIL, naam="App-review (demo)")
        assert _activeer({"token": app["token"]}).status_code == 200
        gid = uuid.UUID(app["gebruiker_id"])

        eerste = seed.zet_demo_activatiecode(review_id=gid, beheerder_id=beheerder_id, code="abcd efgh")
        assert eerste == "ABCD-EFGH"
        assert _activeer({"activatiecode": eerste, "platform": "ios"}, ip="203.0.113.130").status_code == 200
        assert _activeer({"activatiecode": eerste, "platform": "android"}, ip="203.0.113.131").status_code == 200
        # Tweede run: nieuwe code, oude vervalt — precies één geldige code.
        tweede = seed.zet_demo_activatiecode(review_id=gid, beheerder_id=beheerder_id, code="JKLM-NPQR")
        assert _activeer({"activatiecode": eerste}, ip="203.0.113.132").status_code == 400
        assert _activeer({"activatiecode": tweede}, ip="203.0.113.133").status_code == 200
        # zet_account_definitief laat de demo-code staan (alleen gewone links vervallen).
        seed.zet_account_definitief(review_id=gid, beheerder_id=beheerder_id, wachtwoord=None)
        assert _activeer({"activatiecode": tweede}, ip="203.0.113.134").status_code == 200
        with admin_engine.connect() as conn:
            events = (
                conn.execute(
                    text(
                        "SELECT nieuwe_waarde FROM platform.audit_event "
                        "WHERE actie = 'review_demo_activatiecode_gezet' ORDER BY tijdstip"
                    )
                )
                .scalars()
                .all()
            )
        assert len(events) == 2 and events[1]["eerdere_demo_codes_vervallen"] == 1
        assert "JKLMNPQR" not in json.dumps(events) and "ABCDEFGH" not in json.dumps(events)

    def test_failsafes(self, beheerder_id: uuid.UUID) -> None:
        seed = _laad_seed_script()
        ander = _nodig_uit(beheerder_id)
        with pytest.raises(SystemExit, match="FAILSAFE"):
            seed.zet_demo_activatiecode(
                review_id=uuid.UUID(ander["gebruiker_id"]), beheerder_id=beheerder_id, code="ABCD-EFGH"
            )
        demo = _nodig_uit(beheerder_id, e_mail=app_activatie.REVIEW_DEMO_EMAIL)
        with pytest.raises(SystemExit, match="8 tekens"):
            seed.zet_demo_activatiecode(
                review_id=uuid.UUID(demo["gebruiker_id"]), beheerder_id=beheerder_id, code="ABC0"
            )
