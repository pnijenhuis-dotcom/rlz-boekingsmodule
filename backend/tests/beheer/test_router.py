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


def test_niet_beheerder_kan_intake_ai_niet_zetten(gescoopte_gebruiker: uuid.UUID) -> None:
    resp = client.put(
        "/instellingen/intake-ai",
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        json={"ingeschakeld": True},
    )
    assert resp.status_code == 403


def test_beheerder_kan_intake_ai_zetten_en_lezen(beheerder_id: uuid.UUID) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    resp = client.get("/instellingen/intake-ai", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ingeschakeld": False}

    resp = client.put("/instellingen/intake-ai", headers=headers, json={"ingeschakeld": True})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ingeschakeld": True}

    resp = client.get("/instellingen/intake-ai", headers=headers)
    assert resp.json() == {"ingeschakeld": True}


PAD = "/administraties"


class TestIsVastgoedEndpoint:
    """Avondrun 26-08: PATCH /administraties/{id}/is-vastgoed — Beheerder-only (router-brede
    kantoorpoort + require_beheerder), 404 op onbekend, verkoop-autoboeken zichtbaar mee uit."""

    def test_niet_beheerder_403(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        assert client.get(f"/administraties/{administratie_id}/is-vastgoed", headers=headers).status_code == 403
        resp = client.patch(f"{PAD}/{administratie_id}/is-vastgoed", headers=headers, json={"is_vastgoed": True})
        assert resp.status_code == 403

    def test_beheerder_zet_en_leest(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        resp = client.patch(f"{PAD}/{administratie_id}/is-vastgoed", headers=headers, json={"is_vastgoed": True})
        assert resp.status_code == 200, resp.text
        # v2 30-08: verkoop-autoboeken volgt is_vastgoed — de spiegel gaat mee AAN.
        assert resp.json() == {
            "is_vastgoed": True,
            "verkoop_autoboeken_ingeschakeld": True,
            "verkoop_autoboeken_uitgezet": False,
        }
        gelezen = client.get(f"{PAD}/{administratie_id}/is-vastgoed", headers=headers).json()
        assert gelezen["is_vastgoed"] is True
        lijst = client.get("/instellingen/administraties", headers=headers).json()["administraties"]
        assert next(r for r in lijst if r["id"] == str(administratie_id))["is_vastgoed"] is True

    def test_uit_neemt_verkoop_autoboeken_mee(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        client.patch(f"{PAD}/{administratie_id}/is-vastgoed", headers=headers, json={"is_vastgoed": True})
        r = client.put(
            f"{PAD}/{administratie_id}/verkoop-autoboeken-instelling", headers=headers, json={"ingeschakeld": True}
        )
        assert r.status_code == 200, r.text
        resp = client.patch(f"{PAD}/{administratie_id}/is-vastgoed", headers=headers, json={"is_vastgoed": False})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "is_vastgoed": False,
            "verkoop_autoboeken_ingeschakeld": False,
            "verkoop_autoboeken_uitgezet": True,
        }
        # De 409-regel blijft: opnieuw aanzetten zonder is_vastgoed weigert.
        r = client.put(
            f"{PAD}/{administratie_id}/verkoop-autoboeken-instelling", headers=headers, json={"ingeschakeld": True}
        )
        assert r.status_code == 409

    def test_onbekende_administratie_404_en_strikte_invoer_422(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        onbekend = client.patch(f"{PAD}/{uuid.uuid4()}/is-vastgoed", headers=headers, json={"is_vastgoed": True})
        assert onbekend.status_code == 404
        verkeerd = client.patch(f"{PAD}/{administratie_id}/is-vastgoed", headers=headers, json={"ingeschakeld": True})
        assert verkeerd.status_code == 422
