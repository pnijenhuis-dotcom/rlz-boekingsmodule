"""Atomaire activatie externe app-rollen (besluit Peter 28-08, mockup activatie-mobiel.html,
casus Haci; migratie 0083): het wachtwoord wordt pas definitief in dezelfde transactie als de
geslaagde passkey-registratie. Mislukt de passkey, dan is er niets half geregistreerd en blijft de
link bruikbaar. Kantoor-rollen (wachtwoord + TOTP) ongewijzigd — zie test_uitnodiging_statusmachine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from app.auth import service
from app.db.models import GebruikerRol
from tests.auth.soft_webauthn import SoftWebauthnApparaat
from tests.auth.test_webauthn_cadans import (
    WACHTWOORD,
    _bearer,
    _beheerder_bearer,
    _nodig_accordeur_uit,
    client,
)


def _gebruiker(admin_engine: Engine, e_mail: str) -> dict:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text("SELECT id, status, wachtwoord_hash FROM platform.gebruiker WHERE e_mail = :m"), {"m": e_mail}
        ).one()
    return {"id": rij[0], "status": rij[1], "wachtwoord_hash": rij[2]}


def _link(admin_engine: Engine, gebruiker_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT gebruikt_op, wachtwoord_hash_in_wacht FROM platform.uitnodiging "
                "WHERE gebruiker_id = :g ORDER BY aangemaakt_op DESC LIMIT 1"
            ),
            {"g": gebruiker_id},
        ).one()
    return {"gebruikt_op": rij[0], "in_wacht": rij[1]}


def _passkeys(admin_engine: Engine, gebruiker_id: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM platform.webauthn_credential WHERE gebruiker_id = :g"), {"g": gebruiker_id}
        ).scalar_one()


def _audit(admin_engine: Engine, gebruiker_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return list(
            conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"),
                {"id": gebruiker_id},
            ).scalars()
        )


def _accepteer(token: str, wachtwoord: str = WACHTWOORD) -> dict:
    resp = client.post("/auth/uitnodigingen/accepteren", json={"token": token, "wachtwoord": wachtwoord})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _registreer(setup_token: str, *, kapot: bool = False) -> object:
    setup = _bearer(setup_token)
    resp = client.post("/auth/webauthn/registratie/opties", headers=setup)
    assert resp.status_code == 200, resp.text
    credential = SoftWebauthnApparaat().registreer(resp.json()["opties"])
    if kapot:
        credential["response"]["clientDataJSON"] = credential["response"]["clientDataJSON"][:-8] + "AAAAAAAA"
    return client.post(
        "/auth/webauthn/registratie/voltooien",
        json={"credential": credential, "apparaat_naam": "Telefoon"},
        headers=setup,
    )


class TestAtomaireActivatie:
    def test_wachtwoordstap_legt_niets_vast(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        accept = _accepteer(token)
        assert accept["soort"] == "passkey"
        g = _gebruiker(admin_engine, e_mail)
        assert g["status"] == "uitgenodigd"
        assert g["wachtwoord_hash"] is None
        link = _link(admin_engine, g["id"])
        assert link["gebruikt_op"] is None
        assert link["in_wacht"]  # geparkeerd, niet definitief
        # Inloggen met het 'gezette' wachtwoord kan nog niet — er ís geen wachtwoord.
        resp = client.post("/auth/accordeur/login", json={"e_mail": e_mail, "wachtwoord": WACHTWOORD})
        assert resp.status_code == 401
        # Her-openen van de link = flow opnieuw, ook met een ander wachtwoord (laatste wint).
        _accepteer(token, "een-ander-lang-wachtwoord")
        assert _link(admin_engine, g["id"])["in_wacht"] != link["in_wacht"]

    def test_passkey_geslaagd_maakt_alles_in_een_keer_definitief(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        accept = _accepteer(token)
        resp = _registreer(accept["passkey_setup_token"])
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]
        g = _gebruiker(admin_engine, e_mail)
        assert g["status"] == "actief"
        assert g["wachtwoord_hash"]
        link = _link(admin_engine, g["id"])
        assert link["gebruikt_op"] is not None
        assert link["in_wacht"] is None  # hash niet achterlaten op de link
        assert "activatie_afgerond" in _audit(admin_engine, g["id"])
        # Wachtwoordstap werkt nu; de link is verbruikt.
        resp = client.post("/auth/accordeur/login", json={"e_mail": e_mail, "wachtwoord": WACHTWOORD})
        assert resp.status_code == 200, resp.text
        resp = client.post("/auth/uitnodigingen/accepteren", json={"token": token, "wachtwoord": WACHTWOORD})
        assert resp.status_code == 400
        assert "al gebruikt" in resp.json()["detail"]

    def test_passkey_mislukt_laat_niets_half_achter_en_link_blijft(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Het Haci-scenario: de attestation faalt → géén credential, géén wachtwoord, status
        uitgenodigd, link nog verzilverbaar; daarna lukt het alsnog met dezelfde link."""
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        accept = _accepteer(token)
        resp = _registreer(accept["passkey_setup_token"], kapot=True)
        assert resp.status_code == 400, resp.text
        g = _gebruiker(admin_engine, e_mail)
        assert g["status"] == "uitgenodigd"
        assert g["wachtwoord_hash"] is None
        assert _passkeys(admin_engine, g["id"]) == 0
        assert _link(admin_engine, g["id"])["gebruikt_op"] is None
        # Opnieuw proberen — zelfde link, geen nieuwe uitnodiging nodig.
        accept = _accepteer(token)
        resp = _registreer(accept["passkey_setup_token"])
        assert resp.status_code == 200, resp.text
        assert _gebruiker(admin_engine, e_mail)["status"] == "actief"

    def test_link_verlopen_tussen_wachtwoord_en_passkey_rolt_terug(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        accept = _accepteer(token)
        g = _gebruiker(admin_engine, e_mail)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.uitnodiging SET verloopt_op = :t WHERE gebruiker_id = :g"),
                {"t": datetime.now(UTC) - timedelta(minutes=1), "g": g["id"]},
            )
        resp = _registreer(accept["passkey_setup_token"])
        assert resp.status_code == 400
        assert "verlopen" in resp.json()["detail"]
        # De credential-rij is mét de fout teruggerold — niets half.
        assert _passkeys(admin_engine, g["id"]) == 0
        assert _gebruiker(admin_engine, e_mail)["status"] == "uitgenodigd"

    def test_setup_token_zonder_link_mag_geen_uitgenodigd_account_activeren(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Een passkey_setup-token zónder uitnodiging-id (de login-variant) hoort bij een al
        geactiveerd account; op 'uitgenodigd' faalt het fail-closed."""
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        _accepteer(token)
        g = _gebruiker(admin_engine, e_mail)
        from app.security.tokens import create_passkey_setup_token

        resp = _registreer(create_passkey_setup_token(g["id"]))
        assert resp.status_code == 400
        assert _passkeys(admin_engine, g["id"]) == 0

    def test_kantoorrol_blijft_direct_wachtwoord_plus_totp(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        e_mail = f"kantoor-{uuid.uuid4()}@test.local"
        resultaat = service.maak_uitnodiging(
            actor_id=beheerder_id, naam="Kantoor", e_mail=e_mail, rol=GebruikerRol.BOEKHOUDING, administratie_ids=[]
        )
        accept = _accepteer(resultaat.token)
        assert accept["soort"] == "totp"
        g = _gebruiker(admin_engine, e_mail)
        assert g["status"] == "wacht_op_totp"
        assert g["wachtwoord_hash"]
        assert _link(admin_engine, g["id"])["gebruikt_op"] is not None


class TestUitnodigingInfo:
    def test_flow_per_rol_zonder_verzilveren(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        resp = client.get("/auth/uitnodigingen/info", params={"token": token})
        assert resp.status_code == 200, resp.text
        assert resp.json()["flow"] == "passkey"
        assert resp.json()["herstel"] is False
        assert resp.json()["naam"]
        assert "e_mail" not in resp.json()
        assert _link(admin_engine, _gebruiker(admin_engine, e_mail)["id"])["gebruikt_op"] is None

        kantoor = service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam="K",
            e_mail=f"k-{uuid.uuid4()}@test.local",
            rol=GebruikerRol.BOEKHOUDING,
            administratie_ids=[],
        )
        resp = client.get("/auth/uitnodigingen/info", params={"token": kantoor.token})
        assert resp.json()["flow"] == "totp"

    def test_ongeldig_of_verbruikt_token_is_400(self, beheerder_id: uuid.UUID) -> None:
        resp = client.get("/auth/uitnodigingen/info", params={"token": "bestaat-niet"})
        assert resp.status_code == 400
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        accept = _accepteer(token)
        assert _registreer(accept["passkey_setup_token"]).status_code == 200
        resp = client.get("/auth/uitnodigingen/info", params={"token": token})
        assert resp.status_code == 400
        assert "al gebruikt" in resp.json()["detail"]


class TestActivatieProbleem:
    def test_melding_wordt_geauditeerd_zonder_mailconfig(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        _accepteer(token)
        resp = client.post("/auth/uitnodigingen/activatie-probleem", json={"token": token})
        assert resp.status_code == 204, resp.text
        g = _gebruiker(admin_engine, e_mail)
        assert "activatie_probleem_gemeld" in _audit(admin_engine, g["id"])
        # Niets aan het account gewijzigd.
        assert g["status"] == "uitgenodigd"

    def test_melding_mailt_kantoor_als_adres_bekend(
        self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.berichten import mail, uitnodigingsmail
        from app.config import settings

        verzonden: list[dict] = []
        monkeypatch.setattr(settings, "berichten_reply_to", "kantoor@test.local")
        monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))
        assert uitnodigingsmail.mail is mail
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        resp = client.post("/auth/uitnodigingen/activatie-probleem", json={"token": token})
        assert resp.status_code == 204
        # verzonden[0] is de uitnodigingsmail aan de gebruiker; de melding gaat naar het kantoor.
        assert verzonden[-1]["naar"] == "kantoor@test.local"
        assert e_mail in verzonden[-1]["tekst"]
        assert "Activatie lukt niet" in verzonden[-1]["onderwerp"]

    def test_onbekend_token_is_400(self) -> None:
        resp = client.post("/auth/uitnodigingen/activatie-probleem", json={"token": "nee"})
        assert resp.status_code == 400


class TestHalfGeactiveerdInLijst:
    def test_nieuw_uitgenodigd_account_is_niet_half(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        _accepteer(token)
        g = _gebruiker(admin_engine, e_mail)
        resp = client.get("/auth/gebruikers", headers=_beheerder_bearer(beheerder_id))
        rij = next(r for r in resp.json()["gebruikers"] if r["id"] == str(g["id"]))
        assert rij["half_geactiveerd"] is False
        assert rij["status"] == "uitgenodigd"

    def test_legacy_actief_zonder_passkey_is_half(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        e_mail, token = _nodig_accordeur_uit(beheerder_id)
        g = _gebruiker(admin_engine, e_mail)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.gebruiker SET status = 'actief', wachtwoord_hash = 'x' WHERE id = :id"),
                {"id": g["id"]},
            )
        resp = client.get("/auth/gebruikers", headers=_beheerder_bearer(beheerder_id))
        rij = next(r for r in resp.json()["gebruikers"] if r["id"] == str(g["id"]))
        assert rij["half_geactiveerd"] is True
