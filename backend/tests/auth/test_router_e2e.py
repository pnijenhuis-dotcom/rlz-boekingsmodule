from __future__ import annotations

import time
import uuid

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import app
from app.security.tokens import create_access_token
from app.security.totp import STEP_SECONDS

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def test_volledige_http_flow_uitnodigen_tot_login_en_refresh(beheerder_id: uuid.UUID) -> None:
    """Geen freeze_time hier: FastAPI's TestClient draait synchrone handlers in een threadpool
    (Starlette/anyio), en freezegun's patch bleek daar niet betrouwbaar door te werken (directe
    aanroepen van app.auth.service werken wél onder freeze_time — zie de andere testbestanden).
    In plaats daarvan: voor de login-stap een code voor de VOLGENDE TOTP-stap genereren (het
    ±1-clock-skew-venster van verify_code vangt dat op), zodat replay van de net-bevestigde stap
    vermeden wordt zonder aan de klok te moeten sleutelen."""
    e_mail = f"{uuid.uuid4()}@test.local"

    headers = _bearer(beheerder_id, rol="beheerder")
    resp = client.post(
        "/auth/uitnodigingen",
        json={"naam": "HTTP Test", "e_mail": e_mail, "rol": "boekhouding", "administratie_ids": []},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]

    resp = client.post(
        "/auth/uitnodigingen/accepteren", json={"token": token, "wachtwoord": "een-heel-lang-wachtwoord"}
    )
    assert resp.status_code == 200, resp.text
    accept_data = resp.json()

    code = pyotp.TOTP(accept_data["secret"]).at(time.time())
    resp = client.post(
        "/auth/totp/bevestigen",
        json={"code": code},
        headers={"Authorization": f"Bearer {accept_data['totp_setup_token']}"},
    )
    assert resp.status_code == 200, resp.text

    login_code = pyotp.TOTP(accept_data["secret"]).at(time.time() + STEP_SECONDS)
    resp = client.post(
        "/auth/login", json={"e_mail": e_mail, "wachtwoord": "een-heel-lang-wachtwoord", "totp_code": login_code}
    )
    assert resp.status_code == 200, resp.text
    tokens = resp.json()

    resp = client.post("/auth/token/vernieuwen", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200, resp.text


def test_niet_beheerder_krijgt_403_op_uitnodiging_aanmaken(admin_engine: Engine) -> None:
    niet_beheerder_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Geen Beheerder', :mail, 'boekhouding', 'actief')"
            ),
            {"id": niet_beheerder_id, "mail": f"{niet_beheerder_id}@test.local"},
        )
    headers = _bearer(niet_beheerder_id, rol="boekhouding")
    resp = client.post(
        "/auth/uitnodigingen",
        json={"naam": "X", "e_mail": f"{uuid.uuid4()}@test.local", "rol": "boekhouding", "administratie_ids": []},
        headers=headers,
    )
    assert resp.status_code == 403


def test_eigen_rol_wijzigen_geeft_403_via_http(beheerder_id: uuid.UUID) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    resp = client.patch(f"/auth/gebruikers/{beheerder_id}/rol", json={"rol": "boekhouding"}, headers=headers)
    assert resp.status_code == 403


def test_login_zonder_activatie_faalt(beheerder_id: uuid.UUID) -> None:
    from app.auth import service
    from app.db.models import GebruikerRol

    e_mail = f"{uuid.uuid4()}@test.local"
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id, naam="Niet actief", e_mail=e_mail, rol=GebruikerRol.BOEKHOUDING, administratie_ids=[]
    )
    service.accepteer_uitnodiging(token=resultaat.token, wachtwoord="een-heel-lang-wachtwoord")
    # Wachtwoord staat, maar TOTP nog niet bevestigd -> status wacht_op_totp, geen login.
    resp = client.post(
        "/auth/login",
        json={"e_mail": e_mail, "wachtwoord": "een-heel-lang-wachtwoord", "totp_code": "000000"},
    )
    assert resp.status_code == 401
