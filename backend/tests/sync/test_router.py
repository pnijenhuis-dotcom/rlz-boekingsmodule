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


def test_btw_codes_lijst_geeft_percentage_mee(
    monkeypatch: pytest.MonkeyPatch, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    """Design-pass taak 3: percentage moet door de lees-endpoint heen komen — de frontend gebruikt
    dit als "code" in de combobox en om het btw-bedrag automatisch af te leiden."""
    taxrate = {"id": str(uuid.uuid4()), "Name": "NL Hoog Tarief", "Percentage": 0.21}
    monkeypatch.setattr(
        "app.sync.service.client_voor_rlz_admin_id", lambda rlz_admin_id: FakeRlzClient({"TaxRates": [taxrate]})
    )
    client.post(
        f"/administraties/{administratie_id}/sync/taxrates", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )

    resp = client.get(
        f"/administraties/{administratie_id}/btw-codes", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 200, resp.text
    [code] = resp.json()["btw_codes"]
    # 18-09 (btw-keuzelijst NL-eerst, agent B): de lijst draagt óók verlegd/vrijgesteld/buitenland/favoriet/gebruik_12m — de kern blijft.
    assert {k: code[k] for k in ("id", "naam", "percentage")} == {"id": taxrate["id"], "naam": "NL Hoog Tarief", "percentage": "0.2100"}
    assert code["gebruik_12m"] == 0 and code["buitenland"] is False


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


def test_projecten_lijst_draagt_code_en_is_actief(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
    """Blok C 16-09: code = cijfer-prefix uit de naamconventie (RLZ heeft geen codeveld), inactieve projecten
    onderaan mét is_actief=false, een naam zonder code krijgt code null en houdt de volledige naam."""
    from app.db.session import scoped_session
    from app.sync.models import ProjectCache

    ids = [uuid.uuid4() for _ in range(3)]
    with scoped_session(administratie_id) as session:
        for project_id, naam, actief in (
            (ids[0], "26140 Koningstraat (Kempen)", True),
            (ids[1], "00001 Oud werk", False),
            (ids[2], "Overhead", True),
        ):
            session.add(
                ProjectCache(id=project_id, administratie_id=administratie_id, naam=naam, is_actief=actief, brondata={})
            )
    rijen = client.get(
        f"/administraties/{administratie_id}/projecten", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    ).json()["projecten"]
    assert [(r["code"], r["naam"], r["is_actief"]) for r in rijen] == [
        ("26140", "Koningstraat (Kempen)", True),
        (None, "Overhead", True),
        ("00001", "Oud werk", False),
    ]


def test_splits_projectcode_deterministisch() -> None:
    from app.sync.service import splits_projectcode

    assert splits_projectcode("26140 Koningstraat (Kempen)") == ("26140", "Koningstraat (Kempen)")
    assert splits_projectcode("144  Breda (Moeskops)") == ("144", "Breda (Moeskops)")
    assert splits_projectcode("Overhead") == (None, "Overhead")
    assert splits_projectcode("26140") == (None, "26140")  # alleen een code zonder naam = geen splitsing
    assert splits_projectcode(None) == (None, None)
