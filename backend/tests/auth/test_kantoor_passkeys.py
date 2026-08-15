"""Kantoor-passkeys (platformbesluit 0020): passkey als eerste authenticatielijn voor de
kantoor-rollen, wachtwoord + TOTP als volwaardig terugvalpad.

Tweede afnemer van de accordeur-bouwstenen (migratie 0040) — deze suite toetst precies de
verschillen: registratie ín een bestaande sessie (geen nieuw token-paar), éénstaps-login op
e-mailadres (usernameless mag niet), ongewijzigde kantoor-JWT-semantiek (30 dagen, geen
7-dagen-cadans), zelf-beheer van apparaten (alleen eigen, tenzij Beheerder) en de
nooit-buitensluiten-garantie (laatste passkey weg = TOTP werkt onverkort). Alle
WebAuthn-verkeer met échte crypto (SoftWebauthnApparaat), geen mocks."""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import settings
from app.main import app
from app.security.passwords import hash_password
from app.security.tokens import create_access_token
from tests.auth.soft_webauthn import SoftWebauthnApparaat

client = TestClient(app)

WACHTWOORD = "een-heel-lang-wachtwoord"
GENERIEKE_OPTIES_FOUT = "Geen passkey voor dit adres — log in met wachtwoord + TOTP"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _maak_kantoor_gebruiker(admin_engine: Engine, *, rol: str = "boekhouding") -> tuple[uuid.UUID, str]:
    """Directe insert (actief, mét wachtwoord): voor tests die geen TOTP-enrollment nodig
    hebben — de passkey-paden zelf. (e_mail, id)."""
    gid = uuid.uuid4()
    e_mail = f"{gid}@test.local"
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status, wachtwoord_hash) "
                "VALUES (:id, 'Kantoor Test', :mail, :rol, 'actief', :hash)"
            ),
            {"id": gid, "mail": e_mail, "rol": rol, "hash": hash_password(WACHTWOORD)},
        )
    return gid, e_mail


def _registreer_kantoor_passkey(
    access_token: str, *, apparaat_naam: str = "Werk-Mac"
) -> tuple[SoftWebauthnApparaat, dict]:
    """Registratie via de kantoor-endpoints (ingelogde sessie als machtiging). Geeft het
    virtuele apparaat + de ApparaatResponse-body terug."""
    apparaat = SoftWebauthnApparaat()
    resp = client.post("/auth/webauthn/kantoor/registratie/opties", headers=_bearer(access_token))
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/auth/webauthn/kantoor/registratie/voltooien",
        json={"credential": apparaat.registreer(resp.json()["opties"]), "apparaat_naam": apparaat_naam},
        headers=_bearer(access_token),
    )
    assert resp.status_code == 200, resp.text
    return apparaat, resp.json()


def _passkey_login(e_mail: str, apparaat: SoftWebauthnApparaat) -> str:
    """Volledige kantoor-passkey-login (opties → assertion → voltooien); geeft het access-token."""
    resp = client.post("/auth/webauthn/kantoor/login/opties", json={"e_mail": e_mail})
    assert resp.status_code == 200, resp.text
    assert resp.json()["opties"] is not None
    assertion = apparaat.onderteken(resp.json()["opties"])
    resp = client.post(
        "/auth/webauthn/kantoor/login/voltooien", json={"e_mail": e_mail, "credential": assertion}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _activeer_kantoor_met_totp(beheerder_id: uuid.UUID) -> tuple[str, str, str]:
    """Volledige kantoor-activatie via de bestaande flow: uitnodiging → wachtwoord → TOTP
    bevestigen. (e_mail, totp_secret, access_token) — het access-token komt uit de activatie
    zelf (bevestig_totp geeft al een sessie uit), zodat de tests met één échte TOTP-login
    toekunnen: verify_code accepteert maar ±1 stap skew, dus twee opeenvolgende TOTP-logins
    passen niet in één testmoment (zelfde reden als in test_router_e2e — geen freeze_time
    door de TestClient-threadpool)."""
    e_mail = f"{uuid.uuid4()}@test.local"
    resp = client.post(
        "/auth/uitnodigingen",
        json={"naam": "Kantoor TOTP", "e_mail": e_mail, "rol": "boekhouding", "administratie_ids": []},
        headers=_bearer(create_access_token(beheerder_id, rol="beheerder")),
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/auth/uitnodigingen/accepteren", json={"token": resp.json()["token"], "wachtwoord": WACHTWOORD}
    )
    assert resp.status_code == 200, resp.text
    accept = resp.json()
    assert accept["soort"] == "totp"
    secret = accept["secret"]
    resp = client.post(
        "/auth/totp/bevestigen",
        json={"code": pyotp.TOTP(secret).now()},
        headers=_bearer(accept["totp_setup_token"]),
    )
    assert resp.status_code == 200, resp.text
    return e_mail, secret, resp.json()["access_token"]


def _totp_login(e_mail: str, secret: str) -> str:
    """TOTP-terugval-login; gebruikt de code van de vólgende stap (±30s skew is toegestaan)
    zodat de anti-replay op de bij activatie verbruikte stap niet in de weg zit. Max één keer
    per test aanroepen — een tweede stap-vooruit valt buiten het skew-venster."""
    resp = client.post(
        "/auth/login",
        json={"e_mail": e_mail, "wachtwoord": WACHTWOORD, "totp_code": pyotp.TOTP(secret).at(time.time() + 30)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_registratie_en_passkey_login_met_bestaande_jwt_semantiek(admin_engine: Engine) -> None:
    """Happy path: registratie ná login raakt de lopende sessie niet; de passkey-login geeft een
    apparaat-gebonden sessie met de STANDAARD kantoor-refresh-TTL (geen 7-dagen-accordeurcadans)."""
    gid, e_mail = _maak_kantoor_gebruiker(admin_engine)
    access = create_access_token(gid, rol="boekhouding")

    apparaat, apparaat_body = _registreer_kantoor_passkey(access)
    assert apparaat_body["apparaat_naam"] == "Werk-Mac"
    assert apparaat_body["is_dev_stub"] is False
    assert apparaat_body["ingetrokken_op"] is None
    # Geen nieuw token-paar bij registratie: er is nog geen enkele refresh-token-rij.
    with admin_engine.connect() as conn:
        aantal = conn.execute(
            text("SELECT count(*) FROM platform.refresh_token WHERE gebruiker_id = :g"), {"g": gid}
        ).scalar_one()
    assert aantal == 0

    nieuw_access = _passkey_login(e_mail, apparaat)
    resp = client.get("/auth/administraties", headers=_bearer(nieuw_access))
    assert resp.status_code == 200, resp.text

    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT verloopt_op, aangemaakt_op, apparaat_id FROM platform.refresh_token "
                "WHERE gebruiker_id = :g ORDER BY aangemaakt_op DESC LIMIT 1"
            ),
            {"g": gid},
        ).one()
    ttl = rij.verloopt_op - rij.aangemaakt_op
    verwacht = timedelta(seconds=settings.jwt_refresh_ttl_seconds)
    assert verwacht - timedelta(minutes=1) < ttl < verwacht + timedelta(minutes=1)
    assert ttl > timedelta(days=8), "kantoor-TTL mag niet de 7-dagen-accordeurcadans zijn"
    assert rij.apparaat_id is not None  # wél apparaat-gebonden: kill-switch bijt


def test_login_opties_antwoordt_generiek_zonder_bruikbare_passkey(
    beheerder_id: uuid.UUID, admin_engine: Engine
) -> None:
    """Geen account-enumeratie: onbekend adres, passkey-loze kantoorgebruiker én accordeur
    (mét passkey) krijgen exact hetzelfde 409-antwoord."""
    _, kaal_e_mail = _maak_kantoor_gebruiker(admin_engine)

    # Accordeur mét passkey via de eigen activeringsflow (bestaande helperflow inline).
    accordeur_e_mail = f"{uuid.uuid4()}@test.local"
    resp = client.post(
        "/auth/uitnodigingen",
        json={"naam": "Acc", "e_mail": accordeur_e_mail, "rol": "klant_accordeur", "administratie_ids": []},
        headers=_bearer(create_access_token(beheerder_id, rol="beheerder")),
    )
    token = resp.json()["token"]
    resp = client.post("/auth/uitnodigingen/accepteren", json={"token": token, "wachtwoord": WACHTWOORD})
    setup = _bearer(resp.json()["passkey_setup_token"])
    apparaat = SoftWebauthnApparaat()
    resp = client.post("/auth/webauthn/registratie/opties", headers=setup)
    resp = client.post(
        "/auth/webauthn/registratie/voltooien",
        json={"credential": apparaat.registreer(resp.json()["opties"]), "apparaat_naam": "iPhone"},
        headers=setup,
    )
    assert resp.status_code == 200, resp.text

    for e_mail in (f"{uuid.uuid4()}@test.local", kaal_e_mail, accordeur_e_mail):
        resp = client.post("/auth/webauthn/kantoor/login/opties", json={"e_mail": e_mail})
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == GENERIEKE_OPTIES_FOUT


def test_totp_terugval_blijft_onverkort_werken_met_passkey(beheerder_id: uuid.UUID) -> None:
    """Failsafe 0020: wachtwoord + TOTP blijft volledig werken naast een geregistreerde passkey —
    passkey-loze gebruikers merken sowieso niets (het /auth/login-pad is ongewijzigd)."""
    e_mail, secret, activatie_access = _activeer_kantoor_met_totp(beheerder_id)
    apparaat, _ = _registreer_kantoor_passkey(activatie_access)

    # Mét passkey: passkey-login werkt...
    _passkey_login(e_mail, apparaat)
    # ...én de TOTP-terugval blijft het onverkort doen.
    _totp_login(e_mail, secret)


def test_intrekken_alleen_eigen_apparaten_tenzij_beheerder(
    beheerder_id: uuid.UUID, admin_engine: Engine
) -> None:
    gid_a, _ = _maak_kantoor_gebruiker(admin_engine)
    gid_b, _ = _maak_kantoor_gebruiker(admin_engine)
    access_a = create_access_token(gid_a, rol="boekhouding")
    access_b = create_access_token(gid_b, rol="boekhouding")
    _, apparaat_a = _registreer_kantoor_passkey(access_a, apparaat_naam="Mac van A")
    _, apparaat_b = _registreer_kantoor_passkey(access_b, apparaat_naam="Mac van B")

    # Niet-Beheerder mag andermans apparaat niet intrekken — 404, geen bestaans-lek (geen 403).
    resp = client.post(f"/auth/apparaten/{apparaat_a['id']}/intrekken", headers=_bearer(access_b))
    assert resp.status_code == 404
    resp = client.get("/auth/mijn/apparaten", headers=_bearer(access_a))
    assert resp.json()["apparaten"][0]["ingetrokken_op"] is None

    # Eigen apparaat intrekken mag wél (en is idempotent).
    resp = client.post(f"/auth/apparaten/{apparaat_a['id']}/intrekken", headers=_bearer(access_a))
    assert resp.status_code == 204
    assert client.post(f"/auth/apparaten/{apparaat_a['id']}/intrekken", headers=_bearer(access_a)).status_code == 204

    # Beheerder mag óók andermans apparaat intrekken (kill-switch).
    beheerder = _bearer(create_access_token(beheerder_id, rol="beheerder"))
    resp = client.post(f"/auth/apparaten/{apparaat_b['id']}/intrekken", headers=beheerder)
    assert resp.status_code == 204

    # mijn/apparaten toont uitsluitend eigen apparaten, inclusief de ingetrokken status.
    resp = client.get("/auth/mijn/apparaten", headers=_bearer(access_a))
    assert resp.status_code == 200
    lijst = resp.json()["apparaten"]
    assert [a["id"] for a in lijst] == [apparaat_a["id"]]
    assert lijst[0]["ingetrokken_op"] is not None


def test_laatste_passkey_intrekken_sluit_nooit_buiten(beheerder_id: uuid.UUID) -> None:
    """Laatste passkey weg = passkey-login antwoordt weer generiek 409 (client → TOTP-formulier)
    en wachtwoord + TOTP werkt onverkort — nooit buitensluiten."""
    e_mail, secret, access = _activeer_kantoor_met_totp(beheerder_id)
    _, apparaat_body = _registreer_kantoor_passkey(access)

    resp = client.post(f"/auth/apparaten/{apparaat_body['id']}/intrekken", headers=_bearer(access))
    assert resp.status_code == 204

    resp = client.post("/auth/webauthn/kantoor/login/opties", json={"e_mail": e_mail})
    assert resp.status_code == 409
    assert resp.json()["detail"] == GENERIEKE_OPTIES_FOUT
    _totp_login(e_mail, secret)  # terugval werkt


def test_passkey_sessie_valt_per_direct_uit_na_intrekking(
    beheerder_id: uuid.UUID, admin_engine: Engine
) -> None:
    """Zelfde kill-switch-laag als de accordeur: de apparaat-claim in het access-token wordt per
    request hertoetst; een TOTP-sessie (zonder apparaat-claim) blijft ongemoeid."""
    gid, e_mail = _maak_kantoor_gebruiker(admin_engine)
    setup_access = create_access_token(gid, rol="boekhouding")
    apparaat, apparaat_body = _registreer_kantoor_passkey(setup_access)
    passkey_access = _passkey_login(e_mail, apparaat)

    assert client.get("/auth/administraties", headers=_bearer(passkey_access)).status_code == 200
    beheerder = _bearer(create_access_token(beheerder_id, rol="beheerder"))
    assert client.post(f"/auth/apparaten/{apparaat_body['id']}/intrekken", headers=beheerder).status_code == 204

    resp = client.get("/auth/administraties", headers=_bearer(passkey_access))
    assert resp.status_code == 401
    assert "apparaat" in resp.json()["detail"].lower()
    # De apparaat-loze (TOTP-stijl) sessie van dezelfde gebruiker blijft gewoon werken.
    assert client.get("/auth/administraties", headers=_bearer(setup_access)).status_code == 200


def test_assertie_replay_faalt_op_kantoor_login(admin_engine: Engine) -> None:
    gid, e_mail = _maak_kantoor_gebruiker(admin_engine)
    apparaat, _ = _registreer_kantoor_passkey(create_access_token(gid, rol="boekhouding"))

    resp = client.post("/auth/webauthn/kantoor/login/opties", json={"e_mail": e_mail})
    assertion = apparaat.onderteken(resp.json()["opties"])
    resp = client.post("/auth/webauthn/kantoor/login/voltooien", json={"e_mail": e_mail, "credential": assertion})
    assert resp.status_code == 200, resp.text
    replay = client.post("/auth/webauthn/kantoor/login/voltooien", json={"e_mail": e_mail, "credential": assertion})
    assert replay.status_code == 401


def test_kantoor_registratie_geweigerd_voor_accordeur(admin_engine: Engine) -> None:
    """Accordeurs registreren via hun eigen flow (setup-token) — de kantoor-endpoints zouden hun
    wachtwoordstap omzeilen."""
    gid, _ = _maak_kantoor_gebruiker(admin_engine, rol="klant_accordeur")
    access = create_access_token(gid, rol="klant_accordeur")
    resp = client.post("/auth/webauthn/kantoor/registratie/opties", headers=_bearer(access))
    assert resp.status_code == 403
    resp = client.post(
        "/auth/webauthn/kantoor/registratie/voltooien",
        json={"dev_stub": True, "apparaat_naam": "x"},
        headers=_bearer(access),
    )
    assert resp.status_code == 403


def test_dev_stub_hard_vergrendeld_in_productie(
    admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identiek aan de accordeur-kant: setting én omgeving moeten allebei goed staan; in
    productie is de stub onwerkzaam ongeacht de setting."""
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-productie-gate-32-bytes!!")
    monkeypatch.setattr(settings, "auth_biometrie_dev_stub", True)
    monkeypatch.setattr(settings, "environment", "production")

    gid, e_mail = _maak_kantoor_gebruiker(admin_engine)
    access = create_access_token(gid, rol="boekhouding")
    resp = client.post(
        "/auth/webauthn/kantoor/registratie/voltooien",
        json={"dev_stub": True, "apparaat_naam": "LAN-pc"},
        headers=_bearer(access),
    )
    assert resp.status_code == 400
    assert "stub" in resp.json()["detail"].lower()

    # In dev werkt de stub wél, zichtbaar gemarkeerd, en draagt hij de stub-login.
    monkeypatch.setattr(settings, "environment", "dev")
    resp = client.post(
        "/auth/webauthn/kantoor/registratie/voltooien",
        json={"dev_stub": True, "apparaat_naam": "LAN-pc"},
        headers=_bearer(access),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_dev_stub"] is True

    resp = client.post("/auth/webauthn/kantoor/login/opties", json={"e_mail": e_mail})
    assert resp.status_code == 200
    assert resp.json() == {"opties": None, "dev_stub": True}
    resp = client.post("/auth/webauthn/kantoor/login/voltooien", json={"e_mail": e_mail, "dev_stub": True})
    assert resp.status_code == 200, resp.text

    # Terug naar productie: de stub-login valt weg én de opties-route wordt weer generiek 409
    # (stub-credentials tellen dan niet als bruikbare passkey).
    monkeypatch.setattr(settings, "environment", "production")
    resp = client.post("/auth/webauthn/kantoor/login/opties", json={"e_mail": e_mail})
    assert resp.status_code == 409
    resp = client.post("/auth/webauthn/kantoor/login/voltooien", json={"e_mail": e_mail, "dev_stub": True})
    assert resp.status_code == 401


def test_kantoor_apparaten_overzicht_is_beheerder_only(
    beheerder_id: uuid.UUID, admin_engine: Engine
) -> None:
    gid, _ = _maak_kantoor_gebruiker(admin_engine)
    access = create_access_token(gid, rol="boekhouding")
    _, apparaat_body = _registreer_kantoor_passkey(access, apparaat_naam="Overzicht-Mac")

    assert client.get("/auth/apparaten/kantoor", headers=_bearer(access)).status_code == 403

    beheerder = _bearer(create_access_token(beheerder_id, rol="beheerder"))
    resp = client.get("/auth/apparaten/kantoor", headers=beheerder)
    assert resp.status_code == 200, resp.text
    rijen = [a for a in resp.json()["apparaten"] if a["id"] == apparaat_body["id"]]
    assert len(rijen) == 1
    assert rijen[0]["gebruiker_naam"] == "Kantoor Test"
    assert rijen[0]["gebruiker_id"] == str(gid)
