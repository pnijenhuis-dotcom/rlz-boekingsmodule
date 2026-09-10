"""`GET/PUT /instellingen/boeken/ai-toets` (blok B bundel 10-09): Beheerder-only, default AAN, audit oud→nieuw."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import app
from app.security.tokens import create_access_token

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def test_niet_beheerder_403(gescoopte_gebruiker: uuid.UUID) -> None:
    assert (
        client.get("/instellingen/boeken/ai-toets", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code
        == 403
    )
    resp = client.put(
        "/instellingen/boeken/ai-toets",
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        json={"ingeschakeld": False},
    )
    assert resp.status_code == 403


def test_beheerder_leest_default_aan_en_zet_uit_met_audit(beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    resp = client.get("/instellingen/boeken/ai-toets", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ingeschakeld": True}

    resp = client.put("/instellingen/boeken/ai-toets", headers=headers, json={"ingeschakeld": False})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ingeschakeld": False}
    assert client.get("/instellingen/boeken/ai-toets", headers=headers).json() == {"ingeschakeld": False}

    with admin_engine.connect() as conn:
        oud, nieuw = conn.execute(
            text(
                "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                "WHERE actie = 'ai_toets_facturen_gewijzigd'"
            )
        ).one()
    assert oud == {"ai_toets_facturen_ingeschakeld": True} and nieuw == {"ai_toets_facturen_ingeschakeld": False}

    client.put("/instellingen/boeken/ai-toets", headers=headers, json={"ingeschakeld": True})
