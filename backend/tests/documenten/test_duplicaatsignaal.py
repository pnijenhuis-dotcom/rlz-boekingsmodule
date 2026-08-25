"""Duplicaatsignaal (besluit Peter 25-08, RLZ-feedbackronde deel 2 punt 6): de gecachete
RLZ-duplicaatuitkomst per document — berekend ná extractie/veldopslag, zichtbaar in de
werkvoorraad zonder live RLZ-call per rij; de live check op het boekmoment blijft bindend."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.session import scoped_session
from app.documenten import boekvoorstel, duplicaatsignaal, service
from app.documenten.models import DuplicaatSignaal, DuplicaatSignaalUitkomst
from app.documenten.rlz_ids import rlz_herboeking_id
from app.documenten.storage import LokaleBestandsopslag
from app.rlz.client import RlzApiError
from tests.documenten.fake_rlz_client import FakeBoekClient


class _KapotteClient(FakeBoekClient):
    def find_purchase_invoices_by_reference(self, **kwargs):  # type: ignore[override]
        raise RlzApiError(503, "GET", "PurchaseInvoices", "RLZ onbereikbaar (simulatie)")


def _upload_met_kop(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    vendor_id: uuid.UUID | None,
    referentie: str | None = "F-2026-0042",
    totaal: Decimal | None = Decimal("121.00"),
    naam: str = "factuur.pdf",
) -> uuid.UUID:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=b"%PDF-1.4 " + naam.encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=date(2026, 8, 20),
        totaalbedrag=totaal,
        regels=[],
    )
    return resultaat.document_id


def _rij(administratie_id: uuid.UUID, document_id: uuid.UUID) -> DuplicaatSignaal | None:
    with scoped_session(administratie_id) as session:
        rij = session.get(DuplicaatSignaal, document_id)
        if rij is not None:
            session.expunge(rij)
        return rij


class TestBerekenDuplicaatsignaal:
    def test_veldopslag_schrijft_direct_een_rij_ook_zonder_rlz_verbinding(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        """De hook ná sla_boekvoorstel_op draait altijd; zonder credentials (test-administratie)
        is de uitkomst zichtbaar 'onbekend' — nooit stil, nooit een fout voor de opslag."""
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=uuid.uuid4()
        )
        rij = _rij(administratie_id, document_id)
        assert rij is not None
        assert rij.uitkomst == DuplicaatSignaalUitkomst.ONBEKEND.value
        assert rij.melding and "niet te berekenen" in rij.melding

    def test_treffer_in_rlz_geeft_mogelijk_duplicaat_met_herleidbare_treffers(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        vendor_id = uuid.uuid4()
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=vendor_id
        )
        client = FakeBoekClient(
            duplicaten=[{"id": str(uuid.uuid4()), "Reference": "F-2026-0042", "InvoiceNumber": "INK-77"}]
        )
        data = duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=document_id, client=client
        )
        assert data is not None and data.uitkomst is DuplicaatSignaalUitkomst.MOGELIJK_DUPLICAAT
        rij = _rij(administratie_id, document_id)
        assert rij is not None
        assert rij.uitkomst == "mogelijk_duplicaat"
        assert rij.vendor_id == vendor_id and rij.referentie == "F-2026-0042" and rij.totaalbedrag == Decimal("121.00")
        assert rij.treffers == [
            {"id": client.duplicaten[0]["id"], "reference": "F-2026-0042", "invoice_number": "INK-77", "status": None}
        ]
        # Herberekenen = UPDATE van dezelfde rij (geen tweede rij, geen delete).
        duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient(duplicaten=[])
        )
        with scoped_session(administratie_id) as session:
            rijen = session.scalars(select(DuplicaatSignaal).where(DuplicaatSignaal.document_id == document_id)).all()
        assert len(rijen) == 1 and rijen[0].uitkomst == "geen" and rijen[0].treffers == []

    def test_eigen_guid_en_correctieketen_tellen_niet_als_duplicaat(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=uuid.uuid4()
        )
        eigen = str(rlz_herboeking_id(document_id, 0))
        data = duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id,
            document_id=document_id,
            client=FakeBoekClient(duplicaten=[{"id": eigen, "Reference": "F-2026-0042"}]),
        )
        assert data is not None and data.uitkomst is DuplicaatSignaalUitkomst.GEEN

    def test_onvolledige_kop_is_niet_toetsbaar(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=None
        )
        data = duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient(duplicaten=[{"id": "x"}])
        )
        assert data is not None and data.uitkomst is DuplicaatSignaalUitkomst.NIET_TOETSBAAR

    def test_rlz_fout_is_zichtbaar_onbekend_geen_crash(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=uuid.uuid4()
        )
        data = duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=document_id, client=_KapotteClient()
        )
        assert data is not None and data.uitkomst is DuplicaatSignaalUitkomst.ONBEKEND
        assert data.melding and "onbereikbaar" in data.melding


class TestWerkvoorraadZichtbaarheid:
    def test_lijst_en_klantteller_dragen_het_signaal(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        dup_id = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=uuid.uuid4()
        )
        schoon_id = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=uuid.uuid4(),
            referentie="F-ANDERS",
            naam="schoon.pdf",
        )
        duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id,
            document_id=dup_id,
            client=FakeBoekClient(duplicaten=[{"id": str(uuid.uuid4())}, {"id": str(uuid.uuid4())}]),
        )
        duplicaatsignaal.bereken_duplicaatsignaal(
            administratie_id=administratie_id, document_id=schoon_id, client=FakeBoekClient(duplicaten=[])
        )
        lijst = {i.document.id: i for i in service.lijst_documenten(administratie_id=administratie_id)}
        assert lijst[dup_id].duplicaatsignaal is not None
        assert lijst[dup_id].duplicaatsignaal.uitkomst == "mogelijk_duplicaat"
        assert lijst[dup_id].duplicaatsignaal.aantal_treffers == 2
        assert lijst[schoon_id].duplicaatsignaal is not None and lijst[schoon_id].duplicaatsignaal.uitkomst == "geen"
        [klant] = service.werkvoorraad_overzicht(administratie_ids_met_naam=[(administratie_id, "Test")])
        assert klant.duplicaat_signalen == 1
        # Signaal-teller, geen status: telt niet mee in "heeft openstaand werk" op zichzelf.
        assert klant.te_controleren >= 2
