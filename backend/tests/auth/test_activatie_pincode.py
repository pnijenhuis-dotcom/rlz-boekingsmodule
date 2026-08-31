"""Pincode-activatie + app-lock serverkant (besluit Peter 31-08, mockup app-lock-pincode.html,
ING-patroon). De 5-cijferige code is een puur lokaal toestel-anker en bestaat server-side niet;
deze suite dekt wat de server WÉL doet: (1) de wachtwoordloze activatie — link → passkey_setup-
token zonder iets te parkeren, passkey-registratie maakt alles atomair definitief mét
wachtwoord_hash = None; (2) her-login zonder wachtwoord (e-mail → passkey-assertion, externe
app-rollen); (3) de app-lock-meldingen (5× fout = uitsluiting + audit, hulpmail, toestel
ontkoppelen). De wachtwoordflow van vóór 31-08 blijft ongewijzigd — zie test_activatie_atomair."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from app.auth import service
from app.db.models import GebruikerRol
from tests.auth.soft_webauthn import SoftWebauthnApparaat
from tests.auth.test_activatie_atomair import _audit, _gebruiker, _link, _passkeys
from tests.auth.test_webauthn_cadans import _bearer, _nodig_accordeur_uit, client


def _start(token: str) -> dict:
    resp = client.post("/auth/uitnodigingen/activatie-zonder-wachtwoord", json={"token": token})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _registreer_pincode_flow(setup_token: str, apparaat: SoftWebauthnApparaat | None = None, *, kapot: bool = False):
    apparaat = apparaat or SoftWebauthnApparaat()
    setup = _bearer(setup_token)
    resp = client.post("/auth/webauthn/registratie/opties", headers=setup)
    assert resp.status_code == 200, resp.text
    credential = apparaat.registreer(resp.json()["opties"])
    if kapot:
        credential["response"]["clientDataJSON"] = credential["response"]["clientDataJSON"][:-8] + "AAAAAAAA"
    return client.post(
        "/auth/webauthn/registratie/voltooien",
        json={"credential": credential, "apparaat_naam": "Telefoon"},
        headers={**setup, "X-Native-Client": "1"},
    )


def _credential_id_b64(admin_engine: Engine, gebruiker_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        raw = conn.execute(
            text("SELECT credential_id FROM platform.webauthn_credential WHERE gebruiker_id = :g"),
            {"g": gebruiker_id},
        ).scalar_one()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class TestActivatieZonderWachtwoord:
    def test_start_legt_niets_vast(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        start = _start(token)
        assert start["passkey_setup_token"]
        g = _gebruiker(admin_engine, e_mail)
        assert g["status"] == "uitgenodigd"
        assert g["wachtwoord_hash"] is None
        link = _link(admin_engine, g["id"])
        assert link["gebruikt_op"] is None
        assert link["in_wacht"] is None  # niets geparkeerd — de code leeft alleen op het toestel

    def test_geslaagde_registratie_activeert_atomair_zonder_wachtwoord(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        resp = _registreer_pincode_flow(_start(token)["passkey_setup_token"])
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]
        assert resp.json()["refresh_token"]  # native vorm
        g = _gebruiker(admin_engine, e_mail)
        assert g["status"] == "actief"
        assert g["wachtwoord_hash"] is None  # wachtwoordloos account — de passkey ís de credential
        assert _link(admin_engine, g["id"])["gebruikt_op"] is not None
        assert "activatie_afgerond" in _audit(admin_engine, g["id"])
        # De link is verbruikt — ook voor de wachtwoordflow.
        resp = client.post("/auth/uitnodigingen/activatie-zonder-wachtwoord", json={"token": token})
        assert resp.status_code == 400
        assert "al gebruikt" in resp.json()["detail"]

    def test_mislukte_passkey_laat_niets_half_achter(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        resp = _registreer_pincode_flow(_start(token)["passkey_setup_token"], kapot=True)
        assert resp.status_code == 400
        g = _gebruiker(admin_engine, e_mail)
        assert g["status"] == "uitgenodigd"
        assert _passkeys(admin_engine, g["id"]) == 0
        assert _link(admin_engine, g["id"])["gebruikt_op"] is None
        # Zelfde link, tweede poging slaagt.
        resp = _registreer_pincode_flow(_start(token)["passkey_setup_token"])
        assert resp.status_code == 200, resp.text
        assert _gebruiker(admin_engine, e_mail)["status"] == "actief"

    def test_kantoorrol_wordt_geweigerd(self, beheerder_id: uuid.UUID) -> None:
        resultaat = service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam="Kantoor",
            e_mail=f"kantoor-{uuid.uuid4()}@test.local",
            rol=GebruikerRol.BOEKHOUDING,
            administratie_ids=[],
        )
        resp = client.post("/auth/uitnodigingen/activatie-zonder-wachtwoord", json={"token": resultaat.token})
        assert resp.status_code == 400
        assert "wachtwoord + TOTP" in resp.json()["detail"]

    def test_verlopen_link_tussen_start_en_registratie_rolt_terug(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        setup_token = _start(token)["passkey_setup_token"]
        g = _gebruiker(admin_engine, e_mail)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.uitnodiging SET verloopt_op = :t WHERE gebruiker_id = :g"),
                {"t": datetime.now(UTC) - timedelta(minutes=1), "g": g["id"]},
            )
        resp = _registreer_pincode_flow(setup_token)
        assert resp.status_code == 400
        assert _passkeys(admin_engine, g["id"]) == 0
        assert _gebruiker(admin_engine, e_mail)["status"] == "uitgenodigd"

    def test_herstel_link_via_pincode_flow_trekt_sessies_in_en_laat_wachtwoord_staan(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Herstel ná bv. een kill-switch: verse kantoor-link → code + nieuwe passkey. Het
        (eventueel nog bestaande) wachtwoord blijft onaangeroerd; oude sessies vervallen."""
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        eerste = _registreer_pincode_flow(_start(token)["passkey_setup_token"])
        assert eerste.status_code == 200
        oud_refresh = eerste.json()["refresh_token"]
        g = _gebruiker(admin_engine, e_mail)
        herstel = service.maak_herstel_link(actor_id=beheerder_id, gebruiker_id=g["id"])
        resp = _registreer_pincode_flow(_start(herstel.resultaat.token)["passkey_setup_token"])
        assert resp.status_code == 200, resp.text
        assert _gebruiker(admin_engine, e_mail)["wachtwoord_hash"] is None
        assert "wachtwoord_hersteld" in _audit(admin_engine, g["id"])
        # De oude sessie is ingetrokken.
        resp = client.post(
            "/auth/token/vernieuwen", headers={"X-Native-Client": "1", "X-Refresh-Token": oud_refresh}
        )
        assert resp.status_code == 401


class TestAccordeurPasskeyLogin:
    def test_her_login_zonder_wachtwoord(self, beheerder_id: uuid.UUID) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        apparaat = SoftWebauthnApparaat()
        assert _registreer_pincode_flow(_start(token)["passkey_setup_token"], apparaat).status_code == 200
        resp = client.post("/auth/accordeur/passkey-login/opties", json={"e_mail": e_mail})
        assert resp.status_code == 200, resp.text
        credential = apparaat.onderteken(resp.json()["opties"])
        resp = client.post(
            "/auth/accordeur/passkey-login/voltooien",
            json={"e_mail": e_mail, "credential": credential},
            headers={"X-Native-Client": "1"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]
        assert resp.json()["refresh_token"]

    def test_geen_passkey_of_kantoorrol_geeft_zelfde_409(self, beheerder_id: uuid.UUID) -> None:
        resp = client.post("/auth/accordeur/passkey-login/opties", json={"e_mail": "bestaat-niet@test.local"})
        assert resp.status_code == 409
        generiek = resp.json()["detail"]
        # Uitgenodigd (nog geen passkey) — zelfde antwoord.
        e_mail, _ = _nodig_accordeur_uit(beheerder_id)
        resp = client.post("/auth/accordeur/passkey-login/opties", json={"e_mail": e_mail})
        assert resp.status_code == 409
        assert resp.json()["detail"] == generiek


class TestAppLock:
    def test_uitgesloten_trekt_apparaat_in_met_audit_en_is_idempotent(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        assert _registreer_pincode_flow(_start(token)["passkey_setup_token"]).status_code == 200
        g = _gebruiker(admin_engine, e_mail)
        cred_b64 = _credential_id_b64(admin_engine, g["id"])
        resp = client.post("/auth/app-lock/uitgesloten", json={"credential_id": cred_b64})
        assert resp.status_code == 204
        with admin_engine.connect() as conn:
            ingetrokken = conn.execute(
                text("SELECT ingetrokken_op FROM platform.webauthn_credential WHERE gebruiker_id = :g"),
                {"g": g["id"]},
            ).scalar_one()
            open_refresh = conn.execute(
                text(
                    "SELECT count(*) FROM platform.refresh_token "
                    "WHERE gebruiker_id = :g AND ingetrokken_op IS NULL"
                ),
                {"g": g["id"]},
            ).scalar_one()
        assert ingetrokken is not None
        assert open_refresh == 0
        # Idempotent: tweede melding = 204 zonder tweede audit-event.
        assert client.post("/auth/app-lock/uitgesloten", json={"credential_id": cred_b64}).status_code == 204
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = 'app_lock_uitgesloten' AND actor_id = :g"),
                {"g": g["id"]},
            ).scalar_one()
        assert aantal == 1

    def test_onbekend_credential_is_stil_204(self) -> None:
        resp = client.post("/auth/app-lock/uitgesloten", json={"credential_id": "AAAAAAAAAAAAAAAAAAAAAA"})
        assert resp.status_code == 204

    def test_hulp_mailt_kantoor_ook_na_uitsluiting(
        self, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.berichten import mail
        from app.config import settings

        verzonden: list[dict] = []
        monkeypatch.setattr(settings, "berichten_reply_to", "kantoor@test.local")
        monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        assert _registreer_pincode_flow(_start(token)["passkey_setup_token"]).status_code == 200
        g = _gebruiker(admin_engine, e_mail)
        cred_b64 = _credential_id_b64(admin_engine, g["id"])
        assert client.post("/auth/app-lock/uitgesloten", json={"credential_id": cred_b64}).status_code == 204
        resp = client.post("/auth/app-lock/hulp", json={"credential_id": cred_b64})
        assert resp.status_code == 204
        assert verzonden[-1]["naar"] == "kantoor@test.local"
        assert e_mail in verzonden[-1]["tekst"]
        assert "Nieuwe activatielink" in verzonden[-1]["onderwerp"]
        assert "app_lock_hulp_gevraagd" not in _audit(admin_engine, g["id"])  # audit op de credential-rij
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = 'app_lock_hulp_gevraagd' AND actor_id = :g"),
                {"g": g["id"]},
            ).scalar_one()
        assert aantal == 1

    def test_ontkoppelen_trekt_eigen_apparaat_in(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        registratie = _registreer_pincode_flow(_start(token)["passkey_setup_token"])
        assert registratie.status_code == 200
        access = registratie.json()["access_token"]
        resp = client.post("/auth/app-lock/ontkoppelen", headers=_bearer(access))
        assert resp.status_code == 204
        g = _gebruiker(admin_engine, e_mail)
        with admin_engine.connect() as conn:
            ingetrokken = conn.execute(
                text("SELECT ingetrokken_op FROM platform.webauthn_credential WHERE gebruiker_id = :g"),
                {"g": g["id"]},
            ).scalar_one()
        assert ingetrokken is not None
        # Kill-switch bijt per request: dezelfde access-token is direct waardeloos.
        assert client.post("/auth/app-lock/ontkoppelen", headers=_bearer(access)).status_code == 401
