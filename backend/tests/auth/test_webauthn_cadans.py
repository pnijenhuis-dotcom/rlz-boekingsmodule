"""Passkey-cadans accordeur (blok 1 accordeur-PWA, besluit 2026-08-11) — TestClient-laag.

De volledige echte-HTTP-cadans (registratie/assertion/7-dagen-verval/nieuw apparaat/
kill-switch/refresh-race) leeft in tests/e2e/test_accordeur_cadans_e2e.py; hier de
service-/routerlogica die geen echte socket nodig heeft: activeringsflow-vertakking,
voorwaarden-poort op de wachtrij, 7-dagen-TTL, challenge-replay en de dev-stub-vergrendeling.
Alle WebAuthn-verkeer met échte crypto (SoftWebauthnApparaat), geen mocks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import settings
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.soft_webauthn import SoftWebauthnApparaat

client = TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _beheerder_bearer(beheerder_id: uuid.UUID) -> dict[str, str]:
    return _bearer(create_access_token(beheerder_id, rol="beheerder"))


def _nodig_accordeur_uit(beheerder_id: uuid.UUID, administratie_id: uuid.UUID | None = None) -> tuple[str, str]:
    """(e_mail, uitnodigingstoken) voor een verse klant-accordeur."""
    e_mail = f"{uuid.uuid4()}@test.local"
    resp = client.post(
        "/auth/uitnodigingen",
        json={
            "naam": "Accordeur Test",
            "e_mail": e_mail,
            "rol": "klant_accordeur",
            "administratie_ids": [str(administratie_id)] if administratie_id else [],
        },
        headers=_beheerder_bearer(beheerder_id),
    )
    assert resp.status_code == 200, resp.text
    return e_mail, resp.json()["token"]


WACHTWOORD = "een-heel-lang-wachtwoord"


def _activeer_accordeur(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID | None = None
) -> tuple[str, SoftWebauthnApparaat, str]:
    """Volledige activatie t/m passkey-registratie: (e_mail, apparaat, access_token). De
    refresh-cookie staat daarna op de module-globale TestClient."""
    e_mail, token = _nodig_accordeur_uit(beheerder_id, administratie_id)
    resp = client.post("/auth/uitnodigingen/accepteren", json={"token": token, "wachtwoord": WACHTWOORD})
    assert resp.status_code == 200, resp.text
    accept = resp.json()
    assert accept["soort"] == "passkey"
    assert accept["passkey_setup_token"]
    assert accept["totp_setup_token"] is None

    apparaat = SoftWebauthnApparaat()
    setup = _bearer(accept["passkey_setup_token"])
    resp = client.post("/auth/webauthn/registratie/opties", headers=setup)
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/auth/webauthn/registratie/voltooien",
        json={"credential": apparaat.registreer(resp.json()["opties"]), "apparaat_naam": "Test-iPhone"},
        headers=setup,
    )
    assert resp.status_code == 200, resp.text
    return e_mail, apparaat, resp.json()["access_token"]


def test_activering_accordeur_via_passkey_en_kantoorrol_blijft_totp(beheerder_id: uuid.UUID) -> None:
    # Kantoor-rol: bestaand TOTP-pad, expliciet soort=totp.
    resp = client.post(
        "/auth/uitnodigingen",
        json={"naam": "Kantoor", "e_mail": f"{uuid.uuid4()}@test.local", "rol": "boekhouding", "administratie_ids": []},
        headers=_beheerder_bearer(beheerder_id),
    )
    resp = client.post(
        "/auth/uitnodigingen/accepteren", json={"token": resp.json()["token"], "wachtwoord": WACHTWOORD}
    )
    assert resp.status_code == 200
    assert resp.json()["soort"] == "totp"
    assert resp.json()["totp_setup_token"]

    # Accordeur: passkey-pad, na registratie een werkende apparaat-gebonden sessie.
    _, _, access_token = _activeer_accordeur(beheerder_id)
    resp = client.get("/auth/administraties", headers=_bearer(access_token))
    assert resp.status_code == 200, resp.text


def test_accordeur_refresh_ttl_is_7_dagen_sliding(beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
    e_mail, _, _ = _activeer_accordeur(beheerder_id)
    with admin_engine.begin() as conn:
        rij = conn.execute(
            text(
                "SELECT rt.verloopt_op, rt.aangemaakt_op, rt.apparaat_id FROM platform.refresh_token rt "
                "JOIN platform.gebruiker g ON g.id = rt.gebruiker_id WHERE g.e_mail = :mail "
                "ORDER BY rt.aangemaakt_op DESC LIMIT 1"
            ),
            {"mail": e_mail},
        ).one()
    ttl = rij.verloopt_op - rij.aangemaakt_op
    assert timedelta(days=6, hours=23) < ttl < timedelta(days=7, hours=1)
    assert rij.apparaat_id is not None  # sessie is apparaat-gebonden


def test_wachtrij_vereist_voorwaarden_akkoord(beheerder_id: uuid.UUID) -> None:
    """Blok 3: zonder vastgelegd akkoord geen wachtrij (server-side, fail-closed); het akkoord
    landt idempotent en daarna is de wachtrij open."""
    _, _, access_token = _activeer_accordeur(beheerder_id)
    headers = _bearer(access_token)

    resp = client.get("/accordering/wachtrij", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "voorwaarden_akkoord_vereist"

    resp = client.get("/auth/accordeur/voorwaarden", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["akkoord_gegeven"] is False
    assert "Gebruiksvoorwaarden" in resp.json()["tekst"]

    for _ in range(2):  # idempotent
        resp = client.post("/auth/accordeur/voorwaarden-akkoord", headers=headers)
        assert resp.status_code == 204, resp.text

    resp = client.get("/auth/accordeur/voorwaarden", headers=headers)
    assert resp.json()["akkoord_gegeven"] is True
    resp = client.get("/accordering/wachtrij", headers=headers)
    assert resp.status_code == 200, resp.text


def test_staande_regels_vereisen_voorwaarden_akkoord(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    """Nazorg 2026-08-11: het ✓✓-beheer (lijst + intrekken) zit achter dezelfde
    voorwaarden-poort als wachtrij/akkoord/afwijzen — een accordeur zonder vastgelegd akkoord
    kan er niet bij; kantoor-rollen raakt de poort niet."""
    _, _, access_token = _activeer_accordeur(beheerder_id, administratie_id)
    headers = _bearer(access_token)
    basis = f"/administraties/{administratie_id}/accordering/staande-regels"

    resp = client.get(basis, headers=headers)
    assert resp.status_code == 403 and resp.json()["detail"] == "voorwaarden_akkoord_vereist"
    resp = client.post(f"{basis}/{uuid.uuid4()}/intrekken", headers=headers)
    assert resp.status_code == 403 and resp.json()["detail"] == "voorwaarden_akkoord_vereist"

    # Kantoor (Beheerder) heeft de informatieplicht-laag niet: gewoon toegang.
    resp = client.get(basis, headers=_beheerder_bearer(beheerder_id))
    assert resp.status_code == 200, resp.text

    # Ná het akkoord is het ✓✓-beheer open voor de accordeur.
    assert client.post("/auth/accordeur/voorwaarden-akkoord", headers=headers).status_code == 204
    resp = client.get(basis, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["regels"] == []


def test_voorwaarden_akkoord_geweigerd_voor_kantoorrol(beheerder_id: uuid.UUID) -> None:
    resp = client.post("/auth/accordeur/voorwaarden-akkoord", headers=_beheerder_bearer(beheerder_id))
    assert resp.status_code == 403


def test_verlopen_challenges_worden_opgeruimd(beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
    """Challenge-huishouding (nazorg 2026-08-11): verlopen rijen worden bij elke nieuwe
    challenge-insert verwijderd (geen aparte job nodig); verse rijen blijven staan. Draait
    via de router zodat óók de DELETE-grant van de app-rol getoetst wordt (migratie 0041)."""
    e_mail, _, _ = _activeer_accordeur(beheerder_id)
    with admin_engine.begin() as conn:
        gebruiker_id = conn.execute(
            text("SELECT id FROM platform.gebruiker WHERE e_mail = :mail"), {"mail": e_mail}
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO platform.webauthn_challenge (id, gebruiker_id, soort, challenge, verloopt_op) "
                "VALUES (:id, :g, 'assertie', :ch, :verlopen)"
            ),
            {
                "id": uuid.uuid4(),
                "g": gebruiker_id,
                "ch": b"verlopen-testchallenge",
                "verlopen": datetime.now(UTC) - timedelta(hours=1),
            },
        )

    # Nieuwe assertion-options -> _maak_challenge -> huishouding draait mee.
    resp = client.post("/auth/accordeur/login", json={"e_mail": e_mail, "wachtwoord": WACHTWOORD})
    assert resp.status_code == 200, resp.text
    resp = client.post("/auth/webauthn/login/opties", headers=_bearer(resp.json()["passkey_setup_token"]))
    assert resp.status_code == 200, resp.text

    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text("SELECT verloopt_op FROM platform.webauthn_challenge WHERE gebruiker_id = :g"),
            {"g": gebruiker_id},
        ).all()
    assert rijen, "de verse challenge hoort te blijven staan"
    assert all(rij.verloopt_op > datetime.now(UTC) for rij in rijen), "verlopen rij niet opgeruimd"


def test_assertie_challenge_is_eenmalig(beheerder_id: uuid.UUID) -> None:
    """Replay-bescherming: dezelfde ondertekende assertion een tweede keer aanbieden faalt (de
    server-side challenge is verbrand)."""
    e_mail, apparaat, _ = _activeer_accordeur(beheerder_id)
    resp = client.post("/auth/accordeur/login", json={"e_mail": e_mail, "wachtwoord": WACHTWOORD})
    assert resp.status_code == 200, resp.text
    assert resp.json()["heeft_passkeys"] is True
    setup = _bearer(resp.json()["passkey_setup_token"])

    resp = client.post("/auth/webauthn/login/opties", headers=setup)
    assert resp.status_code == 200, resp.text
    assertion = apparaat.onderteken(resp.json()["opties"])

    resp = client.post("/auth/webauthn/login/voltooien", json={"credential": assertion}, headers=setup)
    assert resp.status_code == 200, resp.text

    replay = client.post("/auth/webauthn/login/voltooien", json={"credential": assertion}, headers=setup)
    assert replay.status_code == 401


def test_registratie_challenge_verlopen_faalt(beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
    e_mail, token = _nodig_accordeur_uit(beheerder_id)
    resp = client.post("/auth/uitnodigingen/accepteren", json={"token": token, "wachtwoord": WACHTWOORD})
    setup = _bearer(resp.json()["passkey_setup_token"])
    resp = client.post("/auth/webauthn/registratie/opties", headers=setup)
    opties = resp.json()["opties"]
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE platform.webauthn_challenge SET verloopt_op = :verleden WHERE gebruiker_id = "
                "(SELECT id FROM platform.gebruiker WHERE e_mail = :mail)"
            ),
            {"verleden": datetime.now(UTC) - timedelta(minutes=1), "mail": e_mail},
        )
    apparaat = SoftWebauthnApparaat()
    resp = client.post(
        "/auth/webauthn/registratie/voltooien",
        json={"credential": apparaat.registreer(opties), "apparaat_naam": None},
        headers=setup,
    )
    assert resp.status_code == 400
    assert "challenge" in resp.json()["detail"].lower()


def test_dev_stub_hard_vergrendeld_zonder_setting(
    beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """De stub is dubbel vergrendeld: zonder auth_biometrie_dev_stub=True wordt een
    stub-registratie geweigerd, ongeacht de omgeving."""
    # Expliciet pinnen: de suite draait tegen de echte dev-.env, waar de stub voor
    # LAN-kliktests aan kán staan — de test toetst het uit-pad, niet de lokale config.
    monkeypatch.setattr(settings, "auth_biometrie_dev_stub", False)
    _, token = _nodig_accordeur_uit(beheerder_id)
    resp = client.post("/auth/uitnodigingen/accepteren", json={"token": token, "wachtwoord": WACHTWOORD})
    setup = _bearer(resp.json()["passkey_setup_token"])
    resp = client.post(
        "/auth/webauthn/registratie/voltooien",
        json={"dev_stub": True, "apparaat_naam": "LAN-telefoon"},
        headers=setup,
    )
    assert resp.status_code == 400
    assert "stub" in resp.json()["detail"].lower()

    resp = client.get("/auth/webauthn/config")
    assert resp.status_code == 200
    assert resp.json()["dev_stub"] is False


def test_dev_stub_werkt_alleen_buiten_productie(
    beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    # jwt_secret vooraf pinnen: buiten dev bestaat er terecht geen fallback-secret, en de
    # tokens van vóór en ná de environment-wissel moeten hetzelfde secret delen.
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-productie-gate-32-bytes!!")
    monkeypatch.setattr(settings, "auth_biometrie_dev_stub", True)

    _, token = _nodig_accordeur_uit(beheerder_id)
    resp = client.post("/auth/uitnodigingen/accepteren", json={"token": token, "wachtwoord": WACHTWOORD})
    setup = _bearer(resp.json()["passkey_setup_token"])

    # Setting aan maar productie-omgeving: geweigerd (environment-gate wint).
    monkeypatch.setattr(settings, "environment", "production")
    resp = client.post(
        "/auth/webauthn/registratie/voltooien", json={"dev_stub": True, "apparaat_naam": "x"}, headers=setup
    )
    assert resp.status_code == 400

    # Dev-omgeving: stub registreert en de credential is zichtbaar gemarkeerd.
    monkeypatch.setattr(settings, "environment", "dev")
    resp = client.post(
        "/auth/webauthn/registratie/voltooien",
        json={"dev_stub": True, "apparaat_naam": "LAN-telefoon"},
        headers=setup,
    )
    assert resp.status_code == 200, resp.text

    # Apparatenlijst (kantoor) toont de stub-markering.
    with_admin = _beheerder_bearer(beheerder_id)
    gebruiker_id = None
    resp_wie = client.get("/auth/webauthn/config")  # config blijft bereikbaar
    assert resp_wie.status_code == 200
    # gebruiker-id via de wachtrij-loze route: zoek 'm op via apparaten van alle gebruikers is
    # omslachtig — decodeer de sub-claim uit het access-token dat de stub-registratie teruggaf.
    import base64
    import json as jsonlib

    access = resp.json()["access_token"]
    payload = jsonlib.loads(base64.urlsafe_b64decode(access.split(".")[1] + "=="))
    gebruiker_id = payload["sub"]
    resp = client.get(f"/auth/gebruikers/{gebruiker_id}/apparaten", headers=with_admin)
    assert resp.status_code == 200
    apparaten = resp.json()["apparaten"]
    assert len(apparaten) == 1
    assert apparaten[0]["is_dev_stub"] is True
    assert apparaten[0]["apparaat_naam"] == "LAN-telefoon"


def test_kill_switch_blokkeert_access_token_direct(beheerder_id: uuid.UUID) -> None:
    """Apparaat intrekken = de lopende access-token valt per request uit (deps-toets), niet pas
    bij de volgende refresh."""
    _, _, access_token = _activeer_accordeur(beheerder_id)
    headers = _bearer(access_token)
    import base64
    import json as jsonlib

    payload = jsonlib.loads(base64.urlsafe_b64decode(access_token.split(".")[1] + "=="))
    gebruiker_id = payload["sub"]

    admin = _beheerder_bearer(beheerder_id)
    resp = client.get(f"/auth/gebruikers/{gebruiker_id}/apparaten", headers=admin)
    apparaat_id = resp.json()["apparaten"][0]["id"]

    assert client.get("/auth/administraties", headers=headers).status_code == 200
    resp = client.post(f"/auth/apparaten/{apparaat_id}/intrekken", headers=admin)
    assert resp.status_code == 204
    resp = client.get("/auth/administraties", headers=headers)
    assert resp.status_code == 401
    assert "apparaat" in resp.json()["detail"].lower()
    # Idempotent intrekken.
    assert client.post(f"/auth/apparaten/{apparaat_id}/intrekken", headers=admin).status_code == 204


def test_accordeur_login_weigert_kantoorrol_generiek(beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
    """Kantoor-rollen horen op /auth/login (TOTP) — de accordeur-route geeft dezelfde generieke
    401 als bij verkeerde inloggegevens (geen rol-enumeratie)."""
    from app.security.passwords import hash_password

    gid = uuid.uuid4()
    e_mail = f"{gid}@test.local"
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status, wachtwoord_hash) "
                "VALUES (:id, 'Kantoor', :mail, 'boekhouding', 'actief', :hash)"
            ),
            {"id": gid, "mail": e_mail, "hash": hash_password(WACHTWOORD)},
        )
    resp = client.post("/auth/accordeur/login", json={"e_mail": e_mail, "wachtwoord": WACHTWOORD})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Ongeldige inloggegevens"
