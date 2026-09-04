"""Btw-default per administratie (blok E medewerker-wensen 04-09, migratie 0108): Beheerder-only
GET/PUT `/administraties/{id}/btw-default`, audit oud→nieuw mét tariefnaam, onbekend tarief = 422,
null = uit."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import btw_default
from app.db.session import scoped_session
from app.main import app
from app.security.tokens import create_access_token
from app.sync.models import TaxRateCache

client = TestClient(app)

VERLEGD_ID = uuid.UUID("55555555-0000-0000-0000-000000000001")
HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000002")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def tarieven(administratie_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        session.add(
            TaxRateCache(
                id=VERLEGD_ID,
                administratie_id=administratie_id,
                naam="NL, BTW verlegd (hoog)",
                percentage=Decimal("0"),
                brondata={},
            )
        )
        session.add(
            TaxRateCache(
                id=HOOG_ID,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.2100"),
                brondata={},
            )
        )


def _audit(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple[dict, dict]]:
    with admin_engine.connect() as conn:
        return [
            (r[0], r[1])
            for r in conn.execute(
                text(
                    "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                    "WHERE actie = 'standaard_taxrate_gewijzigd' AND record_id = :id ORDER BY tijdstip"
                ),
                {"id": administratie_id},
            ).all()
        ]


def test_default_uit_met_keuzelijst(beheerder_id: uuid.UUID, administratie_id: uuid.UUID, tarieven: None) -> None:
    resp = client.get(f"/administraties/{administratie_id}/btw-default", headers=_bearer(beheerder_id, rol="beheerder"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["taxrate_id"] is None and body["taxrate_naam"] is None
    assert [o["naam"] for o in body["opties"]] == ["NL, BTW verlegd (hoog)", "NL, Hoog Tarief"]


def test_zetten_lezen_uitzetten_met_audit(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, tarieven: None, admin_engine: Engine
) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    resp = client.put(
        f"/administraties/{administratie_id}/btw-default", headers=headers, json={"taxrate_id": str(VERLEGD_ID)}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["taxrate_id"] == str(VERLEGD_ID) and resp.json()["taxrate_naam"] == "NL, BTW verlegd (hoog)"

    resp = client.get(f"/administraties/{administratie_id}/btw-default", headers=headers)
    assert resp.json()["taxrate_id"] == str(VERLEGD_ID)

    resp = client.put(f"/administraties/{administratie_id}/btw-default", headers=headers, json={"taxrate_id": None})
    assert resp.status_code == 200 and resp.json()["taxrate_id"] is None

    audit = _audit(admin_engine, administratie_id)
    assert len(audit) == 2
    assert audit[0][0] == {"standaard_taxrate_id": None, "naam": None}
    assert audit[0][1] == {"standaard_taxrate_id": str(VERLEGD_ID), "naam": "NL, BTW verlegd (hoog)"}
    assert audit[1][0]["naam"] == "NL, BTW verlegd (hoog)" and audit[1][1] == {
        "standaard_taxrate_id": None,
        "naam": None,
    }


def test_zelfde_waarde_opnieuw_zetten_geeft_geen_audit_ruis(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, tarieven: None, admin_engine: Engine
) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    for _ in range(2):
        assert (
            client.put(
                f"/administraties/{administratie_id}/btw-default", headers=headers, json={"taxrate_id": str(HOOG_ID)}
            ).status_code
            == 200
        )
    assert len(_audit(admin_engine, administratie_id)) == 1


def test_onbekend_tarief_422(beheerder_id: uuid.UUID, administratie_id: uuid.UUID, tarieven: None) -> None:
    resp = client.put(
        f"/administraties/{administratie_id}/btw-default",
        headers=_bearer(beheerder_id, rol="beheerder"),
        json={"taxrate_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 422
    assert "gesyncte lijst" in resp.json()["detail"]


def test_verdwenen_tarief_is_geen_optie_meer(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, tarieven: None
) -> None:
    with scoped_session(administratie_id) as session:
        from datetime import UTC, datetime

        session.get(TaxRateCache, (HOOG_ID, administratie_id)).verdwenen_uit_bron_op = datetime.now(UTC)
    resp = client.put(
        f"/administraties/{administratie_id}/btw-default",
        headers=_bearer(beheerder_id, rol="beheerder"),
        json={"taxrate_id": str(HOOG_ID)},
    )
    assert resp.status_code == 422


def test_niet_beheerder_403(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, tarieven: None) -> None:
    headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
    assert client.get(f"/administraties/{administratie_id}/btw-default", headers=headers).status_code == 403
    assert (
        client.put(
            f"/administraties/{administratie_id}/btw-default", headers=headers, json={"taxrate_id": str(HOOG_ID)}
        ).status_code
        == 403
    )


def test_onbekende_administratie_404(beheerder_id: uuid.UUID) -> None:
    resp = client.get(f"/administraties/{uuid.uuid4()}/btw-default", headers=_bearer(beheerder_id, rol="beheerder"))
    assert resp.status_code == 404


def test_service_onbekende_administratie(beheerder_id: uuid.UUID) -> None:
    with pytest.raises(btw_default.BtwDefaultFout):
        btw_default.zet_btw_default(actor_id=beheerder_id, administratie_id=uuid.uuid4(), taxrate_id=None)
