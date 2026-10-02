# ruff: noqa: F811 — pytest-fixtures als parameters
"""Run D 02-10 blok C — "Afwijzen…" in het ⋯-menu van het verkoop- en kassarapport-controlescherm gebruikt exact de
bestaande route `POST /administraties/{adm}/documenten/{id}/afwijzen` (zelfde als de bulkbalk/inkoop). Dit is het
route-contract voor die twee documentsoorten: 201 op een afwijsbare status (ook `klaar_om_te_boeken`, de stand ná
"Corrigeren…"), 422 zonder reden — ongeacht de soort. Geen nieuwe route, geen verbreding nodig."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.documenten import service
from app.documenten.models import DocumentSoort, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.test_vragen import _status, _zet_document_op

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _upload(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, soort: DocumentSoort
) -> uuid.UUID:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"{soort.value}-{uuid.uuid4().hex[:6]}.pdf",
        inhoud=uuid.uuid4().bytes,
        actor_id=actor_id,
        opslag=opslag,
        soort=soort,
    )
    assert resultaat.status == DocumentStatus.TE_CONTROLEREN
    return resultaat.document_id


@pytest.mark.parametrize("soort", [DocumentSoort.VERKOOPFACTUUR, DocumentSoort.KASSARAPPORT])
@pytest.mark.parametrize("herkomst", [DocumentStatus.TE_CONTROLEREN, DocumentStatus.KLAAR_OM_TE_BOEKEN])
def test_afwijzen_route_accepteert_verkoop_en_kassarapport_vanuit_afwijsbare_status(
    soort: DocumentSoort,
    herkomst: DocumentStatus,
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
) -> None:
    document_id = _upload(administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, soort=soort)
    _zet_document_op(
        admin_engine,
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=gescoopte_gebruiker,
        herkomst=herkomst,
    )

    resp = client.post(
        f"/administraties/{administratie_id}/documenten/{document_id}/afwijzen",
        json={"reden": "hoort niet in deze administratie"},
        headers=_bearer(gescoopte_gebruiker),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["status_voor_afwijzing"] == herkomst.value
    assert _status(admin_engine, document_id) == DocumentStatus.AFGEWEZEN.value


@pytest.mark.parametrize("soort", [DocumentSoort.VERKOOPFACTUUR, DocumentSoort.KASSARAPPORT])
def test_afwijzen_route_weigert_zonder_reden_422(
    soort: DocumentSoort,
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
) -> None:
    document_id = _upload(administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, soort=soort)

    resp = client.post(
        f"/administraties/{administratie_id}/documenten/{document_id}/afwijzen",
        json={"reden": "   "},
        headers=_bearer(gescoopte_gebruiker),
    )

    assert resp.status_code == 422, resp.text
    assert _status(admin_engine, document_id) == DocumentStatus.TE_CONTROLEREN.value
