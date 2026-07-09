from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rlz.credentials import GeenRlzCredentials
from app.security.tokens import create_access_token
from tests.sync.conftest import FakeRlzClient

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def test_sync_trigger_zonder_authenticatie_faalt(administratie_id: uuid.UUID) -> None:
    resp = client.post(f"/administraties/{administratie_id}/sync/ledgers")
    assert resp.status_code in (401, 403)


def test_sync_trigger_zonder_scope_faalt(gescoopte_gebruiker: uuid.UUID) -> None:
    andere_administratie_id = uuid.uuid4()
    resp = client.post(
        f"/administraties/{andere_administratie_id}/sync/ledgers",
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    assert resp.status_code == 403


def test_sync_trigger_met_scope_slaagt(
    monkeypatch: pytest.MonkeyPatch, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    ledger = {
        "id": str(uuid.uuid4()),
        "AccountNumber": "4000",
        "Description": "Testrekening",
        "AccountType": 2,
        "IsTotalAccount": False,
    }
    monkeypatch.setattr(
        "app.sync.service.client_voor_rlz_admin_id", lambda rlz_admin_id: FakeRlzClient({"Ledgers": [ledger]})
    )

    resp = client.post(
        f"/administraties/{administratie_id}/sync/ledgers", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"aangemaakt": 1, "bijgewerkt": 0, "verdwenen": 0}


def test_sync_trigger_zonder_credentials_geeft_503(
    monkeypatch: pytest.MonkeyPatch, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    def _geen_credentials(rlz_admin_id: str) -> FakeRlzClient:
        raise GeenRlzCredentials("geen credentials in deze test")

    monkeypatch.setattr("app.sync.service.client_voor_rlz_admin_id", _geen_credentials)

    resp = client.post(
        f"/administraties/{administratie_id}/sync/ledgers", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 503


# --- Sync-triggers voor de overige drie caches (design-pass taak 3) ------------------------


def test_sync_taxrates_trigger_slaagt(
    monkeypatch: pytest.MonkeyPatch, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    monkeypatch.setattr(
        "app.sync.service.client_voor_rlz_admin_id",
        lambda rlz_admin_id: FakeRlzClient({"TaxRates": [{"id": str(uuid.uuid4()), "Name": "NL Hoog 21%"}]}),
    )
    resp = client.post(
        f"/administraties/{administratie_id}/sync/taxrates", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"aangemaakt": 1, "bijgewerkt": 0, "verdwenen": 0}


def test_sync_vendors_trigger_slaagt(
    monkeypatch: pytest.MonkeyPatch, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    monkeypatch.setattr(
        "app.sync.service.client_voor_rlz_admin_id",
        lambda rlz_admin_id: FakeRlzClient(
            {"Vendors": [{"id": str(uuid.uuid4()), "Name": "Leverancier X", "IsArchived": False}]}
        ),
    )
    resp = client.post(
        f"/administraties/{administratie_id}/sync/vendors", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"aangemaakt": 1, "bijgewerkt": 0, "verdwenen": 0}


def test_sync_projects_trigger_slaagt(
    monkeypatch: pytest.MonkeyPatch, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    monkeypatch.setattr(
        "app.sync.service.client_voor_rlz_admin_id",
        lambda rlz_admin_id: FakeRlzClient(
            {"Projects": [{"id": str(uuid.uuid4()), "Name": "Project Y", "IsActive": True}]}
        ),
    )
    resp = client.post(
        f"/administraties/{administratie_id}/sync/projects", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"aangemaakt": 1, "bijgewerkt": 0, "verdwenen": 0}


def test_sync_taxrates_trigger_zonder_scope_faalt(gescoopte_gebruiker: uuid.UUID) -> None:
    resp = client.post(
        f"/administraties/{uuid.uuid4()}/sync/taxrates", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 403


# --- Leeslijsten voor het controlescherm (CLAUDE.md-taak 2.1) ------------------------------


def test_grootboek_lijst_geeft_gesyncte_rekeningen(
    monkeypatch: pytest.MonkeyPatch, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    ledger = {
        "id": str(uuid.uuid4()),
        "AccountNumber": "4699",
        "Description": "Diverse algemene kosten",
        "AccountType": 2,
        "IsTotalAccount": False,
    }
    monkeypatch.setattr(
        "app.sync.service.client_voor_rlz_admin_id", lambda rlz_admin_id: FakeRlzClient({"Ledgers": [ledger]})
    )
    client.post(
        f"/administraties/{administratie_id}/sync/ledgers", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )

    resp = client.get(
        f"/administraties/{administratie_id}/grootboek", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 200, resp.text
    codes = [r["code"] for r in resp.json()["rekeningen"]]
    assert codes == ["4699"]


def test_crediteuren_lijst_zonder_scope_faalt(gescoopte_gebruiker: uuid.UUID) -> None:
    resp = client.get(
        f"/administraties/{uuid.uuid4()}/crediteuren", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 403


def test_lege_lijsten_zijn_gewoon_leeg_geen_fout(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
    headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
    assert client.get(f"/administraties/{administratie_id}/grootboek", headers=headers).json()["rekeningen"] == []
    assert client.get(f"/administraties/{administratie_id}/btw-codes", headers=headers).json()["btw_codes"] == []
    assert client.get(f"/administraties/{administratie_id}/crediteuren", headers=headers).json()["crediteuren"] == []
    assert client.get(f"/administraties/{administratie_id}/projecten", headers=headers).json()["projecten"] == []
