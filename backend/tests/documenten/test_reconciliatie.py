from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.beheer import service as beheer_service
from app.documenten import boeken, boekvoorstel, reconciliatie, service
from app.documenten.rlz_ids import rlz_purchase_invoice_id
from app.documenten.storage import LokaleBestandsopslag
from tests.documenten.fake_rlz_client import FakeBoekClient


def _regel(**overrides) -> boekvoorstel.BoekvoorstelRegelData:
    basis = dict(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"),
        omschrijving=None,
    )
    basis.update(overrides)
    return boekvoorstel.BoekvoorstelRegelData(**basis)


def _boek_een_document(
    *,
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    beheerder_id: uuid.UUID,
    monkeypatch,
) -> uuid.UUID:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"%PDF-1.4 reconciliatie",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=uuid.uuid4(),
        referentie=f"F-{resultaat.document_id}",
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal("121.00"),
        regels=[_regel()],
    )
    fake_client = FakeBoekClient()
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
    boeken.boek_document(
        administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
    )
    return resultaat.document_id


class TestReconciliatie:
    def test_geen_geboekte_documenten_geeft_leeg_rapport_zonder_rlz_aanroep(self, administratie_id: uuid.UUID) -> None:
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=object())
        assert rapport.aantal_gecontroleerd == 0
        assert rapport.afwijkingen == ()

    def test_matchende_rlz_staat_geeft_geen_afwijkingen(
        self, gescoopte_gebruiker, administratie_id, opslag, beheerder_id, monkeypatch
    ) -> None:
        document_id = _boek_een_document(
            gescoopte_gebruiker=gescoopte_gebruiker,
            administratie_id=administratie_id,
            opslag=opslag,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
        )
        rlz_document_id = rlz_purchase_invoice_id(document_id)
        client = FakeBoekClient(
            bestaande_invoices={
                str(rlz_document_id): {"Status": 2, "ReceiptNumber": "RLZ-TEST-00001", "BaseInvoiceAmount": 121.00}
            }
        )
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=client)
        assert rapport.aantal_gecontroleerd == 1
        assert rapport.afwijkingen == ()

    def test_ontbrekend_in_rlz_wordt_gerapporteerd(
        self, gescoopte_gebruiker, administratie_id, opslag, beheerder_id, monkeypatch
    ) -> None:
        _boek_een_document(
            gescoopte_gebruiker=gescoopte_gebruiker,
            administratie_id=administratie_id,
            opslag=opslag,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
        )
        client = FakeBoekClient()  # geen enkele invoice bekend
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=client)
        assert [a.soort for a in rapport.afwijkingen] == ["ontbreekt_in_rlz"]

    def test_afwijkend_bedrag_wordt_gerapporteerd(
        self, gescoopte_gebruiker, administratie_id, opslag, beheerder_id, monkeypatch
    ) -> None:
        document_id = _boek_een_document(
            gescoopte_gebruiker=gescoopte_gebruiker,
            administratie_id=administratie_id,
            opslag=opslag,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
        )
        rlz_document_id = rlz_purchase_invoice_id(document_id)
        client = FakeBoekClient(
            bestaande_invoices={
                str(rlz_document_id): {"Status": 2, "ReceiptNumber": "RLZ-TEST-00001", "BaseInvoiceAmount": 999.00}
            }
        )
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=client)
        assert [a.soort for a in rapport.afwijkingen] == ["bedrag_wijkt_af"]

    def test_status_1_teruggezet_naar_concept_wordt_gerapporteerd(
        self, gescoopte_gebruiker, administratie_id, opslag, beheerder_id, monkeypatch
    ) -> None:
        """Status 1 (Tentative/Concept) op een lokaal geboekt document = échte afwijking: het is
        in RLZ teruggezet naar concept (actie 19 of handmatig) terwijl wij 'geboekt' denken."""
        document_id = _boek_een_document(
            gescoopte_gebruiker=gescoopte_gebruiker,
            administratie_id=administratie_id,
            opslag=opslag,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
        )
        rlz_document_id = rlz_purchase_invoice_id(document_id)
        client = FakeBoekClient(
            bestaande_invoices={
                str(rlz_document_id): {"Status": 1, "ReceiptNumber": "RLZ-TEST-00001", "BaseInvoiceAmount": 121.00}
            }
        )
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=client)
        assert [a.soort for a in rapport.afwijkingen] == ["status_niet_definitief"]

    def test_status_3_afgeletterd_is_geen_afwijking(
        self, gescoopte_gebruiker, administratie_id, opslag, beheerder_id, monkeypatch
    ) -> None:
        """Status 3 = Closed/Gesloten (volledig afgeletterd, DocumentStatuses-enumeratie
        2026-07-13) — de normale levensloop van een geboekte én betaalde factuur, geen drift."""
        document_id = _boek_een_document(
            gescoopte_gebruiker=gescoopte_gebruiker,
            administratie_id=administratie_id,
            opslag=opslag,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
        )
        rlz_document_id = rlz_purchase_invoice_id(document_id)
        client = FakeBoekClient(
            bestaande_invoices={
                str(rlz_document_id): {
                    "Status": 3,
                    "ReceiptNumber": "RLZ-TEST-00001",
                    "BaseInvoiceAmount": 121.00,
                    "BaseRemainingAmount": 0.0,
                }
            }
        )
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=client)
        assert rapport.aantal_gecontroleerd == 1
        assert rapport.afwijkingen == ()

    def test_afwijkend_boekstuknummer_wordt_gerapporteerd(
        self, gescoopte_gebruiker, administratie_id, opslag, beheerder_id, monkeypatch
    ) -> None:
        document_id = _boek_een_document(
            gescoopte_gebruiker=gescoopte_gebruiker,
            administratie_id=administratie_id,
            opslag=opslag,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
        )
        rlz_document_id = rlz_purchase_invoice_id(document_id)
        client = FakeBoekClient(
            bestaande_invoices={
                str(rlz_document_id): {"Status": 2, "ReceiptNumber": "ANDER-NUMMER", "BaseInvoiceAmount": 121.00}
            }
        )
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=client)
        assert [a.soort for a in rapport.afwijkingen] == ["boekstuknummer_wijkt_af"]

    def test_reconcilieer_alle_administraties_geeft_een_rapport_per_administratie(
        self, administratie_id: uuid.UUID
    ) -> None:
        resultaten = reconciliatie.reconcilieer_alle_administraties()
        assert administratie_id in resultaten
        assert resultaten[administratie_id].aantal_gecontroleerd == 0

    def test_reconcilieer_alle_administraties_laat_een_kapotte_er_niet_de_rest_stoppen(
        self, gescoopte_gebruiker, administratie_id, opslag, beheerder_id, monkeypatch
    ) -> None:
        """Een administratie mét geboekte documenten maar zonder werkende RLZ-credentials mag de
        rest van de run niet laten stoppen — het resultaat-dict zet de foutmelding als string op
        precies die administratie (zelfde patroon als sync_alle_administraties)."""
        _boek_een_document(
            gescoopte_gebruiker=gescoopte_gebruiker,
            administratie_id=administratie_id,
            opslag=opslag,
            beheerder_id=beheerder_id,
            monkeypatch=monkeypatch,
        )
        # De monkeypatch op app.documenten.boeken hierboven raakt niet reconciliatie.py's eigen
        # credential-resolutie — reconcilieer_alle_administraties() opent zijn eigen client en
        # vindt dus geen credentials voor deze test-administratie.
        resultaten = reconciliatie.reconcilieer_alle_administraties()
        assert isinstance(resultaten[administratie_id], str)
        assert "credential" in resultaten[administratie_id].lower()
