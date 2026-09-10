from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security.tokens import create_access_token
from tests.sync.conftest import FakeRlzClient

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def test_credential_upsert_vereist_beheerder(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
    resp = client.put(
        f"/administraties/{administratie_id}/rlz-credential",
        json={"webservice_username": "x", "wachtwoord": "y"},
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    assert resp.status_code == 403


def test_credential_upsert_en_metadata_via_beheerder(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    resp = client.put(
        f"/administraties/{administratie_id}/rlz-credential",
        json={"webservice_username": "AK_Nijenhuis", "wachtwoord": "geheim-wachtwoord"},
        headers=_bearer(beheerder_id, rol="beheerder"),
    )
    assert resp.status_code == 204, resp.text

    resp = client.get(
        f"/administraties/{administratie_id}/rlz-credential", headers=_bearer(beheerder_id, rol="beheerder")
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["webservice_username"] == "AK_Nijenhuis"
    assert "wachtwoord" not in body
    assert "geheim-wachtwoord" not in resp.text


def test_credential_metadata_zonder_credential_geeft_404(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    resp = client.get(
        f"/administraties/{administratie_id}/rlz-credential", headers=_bearer(beheerder_id, rol="beheerder")
    )
    assert resp.status_code == 404


def test_credential_upsert_onbekende_administratie_geeft_404(beheerder_id: uuid.UUID) -> None:
    resp = client.put(
        f"/administraties/{uuid.uuid4()}/rlz-credential",
        json={"webservice_username": "x", "wachtwoord": "y"},
        headers=_bearer(beheerder_id, rol="beheerder"),
    )
    assert resp.status_code == 404


def test_rlz_check_vereist_scope_niet_beheerder(
    monkeypatch: pytest.MonkeyPatch, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    """rlz-check is bewust GEEN Beheerder-only (i.t.t. rlz-credential) — administratie-scope
    volstaat, zelfde als document-upload en de sync-trigger."""
    monkeypatch.setattr(
        "app.credentialstore.service.open_root_client", lambda rlz_admin_id: FakeRlzClient({})
    )
    resp = client.post(
        f"/administraties/{administratie_id}/rlz-check", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rapport"]["Administrations"] == "ok"


def test_rlz_check_zonder_scope_faalt(gescoopte_gebruiker: uuid.UUID) -> None:
    andere_administratie_id = uuid.uuid4()
    resp = client.post(
        f"/administraties/{andere_administratie_id}/rlz-check",
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    assert resp.status_code == 403


def test_rlz_check_response_draagt_rechten_administraties_en_eigen_id(
    monkeypatch: pytest.MonkeyPatch, beheerder_id: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    """Knop "RLZ-check" (nachtrun 10/11-09 blok 1): naast rapport + meldingen ook het RLZ-recht per route, de
    administraties die de login ziet (uit dezelfde Administrations-call) en het eigen rlz_admin_id."""
    from app.rlz.client import RlzApiError

    rlz_body = '{"Message":"Actie niet toegestaan bij huidige gebruikersrechten"}'
    fake = FakeRlzClient(
        {"Administrations": [{"id": "rlz-a", "Name": "Baard beheer & management"}, {"id": "rlz-b", "Name": "Box"}]},
        fouten={"Ledgers": RlzApiError(403, "GET", "u", rlz_body)},
    )
    monkeypatch.setattr("app.credentialstore.service.open_root_client", lambda rlz_admin_id: fake)
    resp = client.post(f"/administraties/{administratie_id}/rlz-check", headers=_bearer(beheerder_id, rol="beheerder"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rapport"]["Ledgers"] == "403" and body["rapport"]["TaxRates"] == "ok"
    assert body["meldingen"]["Ledgers"] == f"HTTP 403 — {rlz_body}"
    assert body["rechten"]["Ledgers"].startswith("leesrecht Grootboek")
    assert body["rechten"]["TaxRates"]  # óók voor een groene route
    assert body["administraties_zichtbaar"] == [
        {"id": "rlz-a", "naam": "Baard beheer & management"},
        {"id": "rlz-b", "naam": "Box"},
    ]
    assert body["administraties_fout"] is None
    assert body["rlz_admin_id"]  # het rlz_admin_id van de administratie-rij


def test_rlz_check_zonder_credential_geeft_leesbare_503(
    monkeypatch: pytest.MonkeyPatch, beheerder_id: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    from app.rlz.credentials import GeenRlzCredentials

    def geen(rlz_admin_id: str) -> None:
        raise GeenRlzCredentials(f"Geen webservice-login voor {rlz_admin_id}")

    monkeypatch.setattr("app.credentialstore.service.open_root_client", geen)
    resp = client.post(f"/administraties/{administratie_id}/rlz-check", headers=_bearer(beheerder_id, rol="beheerder"))
    assert resp.status_code == 503
    assert "Geen webservice-login" in resp.json()["detail"]
