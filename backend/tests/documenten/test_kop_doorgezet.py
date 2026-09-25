"""FV-07 (feedbackrun A 25-09): project en btw-code op FACTUURNIVEAU worden door de client naar álle regels doorgezet
(per regel daarna overschrijfbaar); de PUT draagt `kop_doorgezet` en de server schrijft één tijdlijnregel
"kop → regels" (sleutel `kop_doorgezet`) — nooit op een autosave, nooit zonder aantal. Geen migratie."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.boekvoorstel import KOP_DOORGEZET_SLEUTEL
from app.documenten.models import DocumentGebeurtenis
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token

GB_ID = uuid.UUID("44444444-0000-0000-0000-000000004500")
BTW_ID = uuid.UUID("55555555-0000-0000-0000-000000000021")


@pytest.fixture
def document_id(administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    uitkomst = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="fv07.pdf",
        inhoud=b"%PDF-1.4 fv07",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    return uitkomst.document_id


def _regels(n: int) -> list[boekvoorstel.BoekvoorstelRegelData]:
    return [
        boekvoorstel.BoekvoorstelRegelData(
            ledger_id=GB_ID, taxrate_id=BTW_ID, project_id=None, netto_bedrag=Decimal("10.00"), btw_bedrag=Decimal("2.10"), omschrijving=f"r{i}"
        )
        for i in range(n)
    ]


def _notities(document_id: uuid.UUID, administratie_id: uuid.UUID) -> list[dict]:
    with scoped_session(administratie_id) as session:
        return [
            g.detail[KOP_DOORGEZET_SLEUTEL]
            for g in session.scalars(select(DocumentGebeurtenis).where(DocumentGebeurtenis.document_id == document_id))
            if g.detail and KOP_DOORGEZET_SLEUTEL in g.detail
        ]


def _sla_op(administratie_id, document_id, actor_id, *, kop_doorgezet: dict | None) -> None:
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=None,
        referentie="FV-07",
        factuurdatum=date(2026, 9, 1),
        totaalbedrag=Decimal("36.30"),
        regels=_regels(3),
        regels_samenvoegen=False,
        kop_doorgezet=kop_doorgezet,
    )


def test_doorzet_geeft_een_tijdlijnregel(administratie_id, gescoopte_gebruiker, document_id) -> None:
    _sla_op(administratie_id, document_id, gescoopte_gebruiker, kop_doorgezet={"btw": 3, "btw_code": "NL Hoog 21%"})
    assert _notities(document_id, administratie_id) == [{"btw": 3, "btw_code": "NL Hoog 21%"}]


def test_zonder_vlag_of_zonder_aantal_geen_regel(administratie_id, gescoopte_gebruiker, document_id) -> None:
    _sla_op(administratie_id, document_id, gescoopte_gebruiker, kop_doorgezet=None)
    _sla_op(administratie_id, document_id, gescoopte_gebruiker, kop_doorgezet={"project_naam": "26127 Tilburg"})
    assert _notities(document_id, administratie_id) == []


def test_route_neemt_kop_doorgezet_mee(administratie_id, gescoopte_gebruiker, document_id) -> None:
    client = TestClient(app)
    token = create_access_token(gescoopte_gebruiker, rol="boekhouding")
    body = {
        "vendor_id": None,
        "referentie": "FV-07",
        "factuurdatum": "2026-09-01",
        "totaalbedrag": "36.30",
        "regels_samenvoegen": False,
        "regels": [
            {"ledger_id": str(GB_ID), "taxrate_id": str(BTW_ID), "project_id": None, "netto_bedrag": "10.00", "btw_bedrag": "2.10", "omschrijving": "r"}
            for _ in range(3)
        ],
        "kop_doorgezet": {"project": 3, "project_naam": "26127 Tilburg (Heijmans)"},
    }
    resp = client.put(
        f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert _notities(document_id, administratie_id) == [{"project": 3, "project_naam": "26127 Tilburg (Heijmans)"}]
