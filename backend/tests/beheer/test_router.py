from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.security.tokens import create_access_token

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def test_niet_beheerder_kan_instellingen_lijst_niet_zien(gescoopte_gebruiker: uuid.UUID) -> None:
    resp = client.get("/instellingen/administraties", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
    assert resp.status_code == 403


def test_beheerder_krijgt_instellingen_lijst_met_beide_schakelaars(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    client.put(f"/administraties/{administratie_id}/boeken-instelling", headers=headers, json={"ingeschakeld": True})
    client.put(f"/administraties/{administratie_id}/project-instelling", headers=headers, json={"verplicht": True})

    resp = client.get("/instellingen/administraties", headers=headers)
    assert resp.status_code == 200, resp.text
    rijen = resp.json()["administraties"]
    rij = next(r for r in rijen if r["id"] == str(administratie_id))
    assert rij["boeken_ingeschakeld"] is True
    assert rij["project_verplicht"] is True


def test_niet_beheerder_kan_toggle_niet_zien(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
    resp = client.get(
        f"/administraties/{administratie_id}/boeken-instelling", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 403


def test_beheerder_kan_toggle_zetten_en_lezen(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    resp = client.put(
        f"/administraties/{administratie_id}/boeken-instelling", headers=headers, json={"ingeschakeld": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ingeschakeld": True}

    resp = client.get(f"/administraties/{administratie_id}/boeken-instelling", headers=headers)
    assert resp.json() == {"ingeschakeld": True}


def test_gescoopte_gebruiker_kan_project_instelling_lezen(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    """Design-pass taak 4: dit is bewust GEEN Beheerder-only endpoint — elke gebruiker met scope
    op deze administratie moet kunnen weten of de Project-kolom verplicht is."""
    resp = client.get(
        f"/administraties/{administratie_id}/project-instelling",
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"verplicht": False}


def test_gescoopte_gebruiker_kan_project_instelling_niet_zetten(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    resp = client.put(
        f"/administraties/{administratie_id}/project-instelling",
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        json={"verplicht": True},
    )
    assert resp.status_code == 403


def test_beheerder_kan_project_instelling_zetten(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    resp = client.put(
        f"/administraties/{administratie_id}/project-instelling", headers=headers, json={"verplicht": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"verplicht": True}

    resp = client.get(f"/administraties/{administratie_id}/project-instelling", headers=headers)
    assert resp.json() == {"verplicht": True}


def test_niet_beheerder_kan_kill_switch_niet_zetten(gescoopte_gebruiker: uuid.UUID) -> None:
    resp = client.put(
        "/instellingen/boeken-kill-switch",
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        json={"ingeschakeld": False},
    )
    assert resp.status_code == 403


def test_beheerder_kan_kill_switch_zetten(beheerder_id: uuid.UUID) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    resp = client.put("/instellingen/boeken-kill-switch", headers=headers, json={"ingeschakeld": False})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ingeschakeld": False}

    resp = client.get("/instellingen/boeken-kill-switch", headers=headers)
    assert resp.json() == {"ingeschakeld": False}
