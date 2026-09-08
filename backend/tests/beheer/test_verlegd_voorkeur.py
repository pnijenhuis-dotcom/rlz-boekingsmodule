"""Voorkeurs-verlegd-code per administratie (blok 6 herstelrun 08-09, migratie 0123): Beheerder-only PUT
`/administraties/{id}/verlegd-voorkeur`, alleen IsRelayed-tarieven (anders 422), audit oud→nieuw mét tariefnaam;
GET btw-default toont voorkeur + verlegd-opties + wat de prefill nú kiest mét herkomst."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.main import app
from app.security.tokens import create_access_token
from app.sync.models import TaxRateCache

client = TestClient(app)

VERLEGD_HOOG = uuid.UUID("77777777-0000-0000-0000-000000000001")
VERLEGD_LAAG = uuid.UUID("77777777-0000-0000-0000-000000000002")
HOOG_21 = uuid.UUID("77777777-0000-0000-0000-000000000003")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def tarieven(administratie_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        for id_, naam, verlegd in (
            (VERLEGD_HOOG, "NL, BTW verlegd (hoog)", True),
            (VERLEGD_LAAG, "NL, BTW verlegd (laag)", True),
            (HOOG_21, "NL, Hoog Tarief", False),
        ):
            session.add(
                TaxRateCache(
                    id=id_,
                    administratie_id=administratie_id,
                    naam=naam,
                    percentage=Decimal("0") if verlegd else Decimal("0.2100"),
                    brondata={"IsRelayed": verlegd},
                )
            )


def _audit(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple[dict, dict]]:
    with admin_engine.connect() as conn:
        return [
            (r[0], r[1])
            for r in conn.execute(
                text(
                    "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                    "WHERE actie = 'voorkeurs_verlegd_taxrate_gewijzigd' AND record_id = :id ORDER BY tijdstip"
                ),
                {"id": administratie_id},
            ).all()
        ]


def test_get_toont_verlegd_opties_en_effectieve_keuze_zonder_voorkeur(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, tarieven: None
) -> None:
    resp = client.get(f"/administraties/{administratie_id}/btw-default", headers=_bearer(beheerder_id, rol="beheerder"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verlegd_taxrate_id"] is None
    assert [o["naam"] for o in body["verlegd_opties"]] == ["NL, BTW verlegd (hoog)", "NL, BTW verlegd (laag)"]
    # hoog + laag zonder historie/favoriet/default = meerduidig: de prefill kiest niets, dat is zichtbaar
    assert body["verlegd_effectief_id"] is None and body["verlegd_effectief_herkomst"] is None


def test_zetten_lezen_uitzetten_met_audit(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, tarieven: None, admin_engine: Engine
) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    resp = client.put(
        f"/administraties/{administratie_id}/verlegd-voorkeur", headers=headers, json={"taxrate_id": str(VERLEGD_LAAG)}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verlegd_taxrate_id"] == str(VERLEGD_LAAG) and body["verlegd_taxrate_naam"] == "NL, BTW verlegd (laag)"
    assert body["verlegd_effectief_id"] == str(VERLEGD_LAAG)
    assert body["verlegd_effectief_herkomst"] == "voorkeur beheerder"

    resp = client.get(f"/administraties/{administratie_id}/btw-default", headers=headers)
    assert resp.json()["verlegd_taxrate_id"] == str(VERLEGD_LAAG)

    resp = client.put(
        f"/administraties/{administratie_id}/verlegd-voorkeur", headers=headers, json={"taxrate_id": None}
    )
    assert resp.status_code == 200 and resp.json()["verlegd_taxrate_id"] is None

    audit = _audit(admin_engine, administratie_id)
    assert len(audit) == 2
    assert audit[0][0] == {"voorkeurs_verlegd_taxrate_id": None, "naam": None}
    assert audit[0][1] == {"voorkeurs_verlegd_taxrate_id": str(VERLEGD_LAAG), "naam": "NL, BTW verlegd (laag)"}
    assert audit[1][1] == {"voorkeurs_verlegd_taxrate_id": None, "naam": None}


def test_niet_verlegd_of_onbekend_tarief_is_422(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, tarieven: None
) -> None:
    headers = _bearer(beheerder_id, rol="beheerder")
    for id_ in (HOOG_21, uuid.uuid4()):
        resp = client.put(
            f"/administraties/{administratie_id}/verlegd-voorkeur", headers=headers, json={"taxrate_id": str(id_)}
        )
        assert resp.status_code == 422, resp.text
        assert "verlegd" in resp.json()["detail"]


def test_niet_beheerder_krijgt_403(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, tarieven: None) -> None:
    resp = client.put(
        f"/administraties/{administratie_id}/verlegd-voorkeur",
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        json={"taxrate_id": str(VERLEGD_HOOG)},
    )
    assert resp.status_code == 403
