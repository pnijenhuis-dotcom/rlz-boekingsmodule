"""Verkoop-boekmotor: boekt SalesInvoice mét Entity = de échte huurder (idempotente
debiteur-aanmaak), creditnota als negatieve tegenboeking, webhook alleen voor
vastgoed-administraties, en elke weiger-reden zichtbaar."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, select, text

from app.db.session import scoped_session
from app.documenten import boeken as documenten_boeken
from app.documenten.models import DocumentStatus, WebhookUitgaand
from app.documenten.rlz_ids import rlz_customer_id, rlz_sales_invoice_id
from app.documenten.storage import LokaleBestandsopslag
from app.verkoop import boeken as verkoop_boeken
from app.verkoop import voorstel as voorstel_service
from app.verkoop.models import VerkoopBoeking
from tests.verkoop.conftest import (
    OMZET_LEDGER_ID,
    TAXRATE_21_ID,
    FakeVerkoopClient,
    bouw_vastly_creditnote_ubl,
    bouw_vastly_verkoop_ubl,
    upload_verkoopfactuur,
)


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: FakeVerkoopClient) -> None:
    monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)


def _upload_en_bevestig(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    inhoud: bytes,
    bestandsnaam: str = "vastly-verkoop.xml",
) -> uuid.UUID:
    document_id = upload_verkoopfactuur(
        administratie_id=administratie_id,
        actor_id=actor_id,
        opslag=opslag,
        inhoud=inhoud,
        bestandsnaam=bestandsnaam,
    )
    prefill = voorstel_service.haal_verkoop_voorstel_op(
        administratie_id=administratie_id, document_id=document_id
    )
    voorstel_service.sla_verkoop_voorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        debiteur_naam=prefill.debiteur_naam,
        factuurnummer=prefill.factuurnummer,
        factuurdatum=prefill.factuurdatum,
        totaalbedrag_incl=prefill.totaalbedrag_incl,
        regels=[
            voorstel_service.VerkoopRegelInput(
                omschrijving=r.omschrijving,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                gb_code=r.gb_code,
                ledger_id=r.ledger_id or OMZET_LEDGER_ID,
                taxrate_id=r.taxrate_id or TAXRATE_21_ID,
            )
            for r in prefill.regels
        ],
    )
    return document_id


class TestBoekVerkoopDocument:
    def test_boekt_met_entity_en_registreert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
    ) -> None:
        client = FakeVerkoopClient()
        _patch_client(monkeypatch, client)
        document_id = _upload_en_bevestig(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )
        resultaat = verkoop_boeken.boek_verkoop_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status is DocumentStatus.GEBOEKT
        # SalesInvoice draagt Entity = de deterministische debiteur-GUID van deze huurder.
        verwachte_customer = rlz_customer_id(administratie_id, "J. van den Berg")
        factuur = client.sales_invoices[str(rlz_sales_invoice_id(document_id))]
        assert factuur["Entity"] == {"id": str(verwachte_customer)}
        assert factuur["Status"] == 2
        # Marker als regel-1-prefix (verkoop-STAP-0: document-Description = regel 1).
        assert factuur["Description"] == "VASTLY-VERKOOP VF-2026-0042 · Huur augustus 2026"
        [line] = factuur["DocumentLineList"]
        assert line["NetAmount"] == 1000.0
        assert line["TaxAmount"] == 210.0
        assert str(verwachte_customer) in client.customers  # debiteur idempotent aangemaakt
        assert client.uploads  # UBL als bijlage meegegeven
        with scoped_session(administratie_id) as session:
            registratie = session.scalars(
                select(VerkoopBoeking).where(VerkoopBoeking.document_id == document_id)
            ).one()
            assert registratie.factuurnummer == "VF-2026-0042"
            assert registratie.debiteur_customer_id == verwachte_customer
            # Geen vastgoed-administratie → géén webhook-outbox-rij.
            outbox = session.scalars(
                select(WebhookUitgaand).where(WebhookUitgaand.document_id == document_id)
            ).all()
            assert outbox == []

    def test_bestaande_debiteur_wordt_hergebruikt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
    ) -> None:
        bestaande_id = str(uuid.uuid4())
        client = FakeVerkoopClient(
            bestaande_customers=[{"id": bestaande_id, "Name": "J. van den Berg"}]
        )
        _patch_client(monkeypatch, client)
        document_id = _upload_en_bevestig(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )
        verkoop_boeken.boek_verkoop_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        factuur = client.sales_invoices[str(rlz_sales_invoice_id(document_id))]
        assert factuur["Entity"] == {"id": bestaande_id}
        assert client.customers == {}  # nooit een tweede debiteur naast een bestaande

    def test_creditnota_boekt_negatieve_tegenboeking_op_zelfde_debiteur(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
    ) -> None:
        client = FakeVerkoopClient()
        _patch_client(monkeypatch, client)
        origineel = _upload_en_bevestig(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )
        verkoop_boeken.boek_verkoop_document(
            administratie_id=administratie_id, document_id=origineel, actor_id=gescoopte_gebruiker
        )
        credit = _upload_en_bevestig(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_creditnote_ubl(),
            bestandsnaam="vastly-credit.xml",
        )
        resultaat = verkoop_boeken.boek_verkoop_document(
            administratie_id=administratie_id, document_id=credit, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status is DocumentStatus.GEBOEKT
        factuur = client.sales_invoices[str(rlz_sales_invoice_id(credit))]
        [line] = factuur["DocumentLineList"]
        assert line["NetAmount"] == -1000.0
        assert line["TaxAmount"] == -210.0
        assert factuur["Description"].startswith("VASTLY-CREDIT VF-2026-0042-C1 ·")
        verwachte_customer = rlz_customer_id(administratie_id, "J. van den Berg")
        assert factuur["Entity"] == {"id": str(verwachte_customer)}

    def test_creditnota_zonder_origineel_blokkeert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
    ) -> None:
        client = FakeVerkoopClient()
        _patch_client(monkeypatch, client)
        credit = _upload_en_bevestig(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_creditnote_ubl(),
            bestandsnaam="vastly-credit.xml",
        )
        with pytest.raises(documenten_boeken.BoekenGeblokkeerdDoorChecks) as excinfo:
            verkoop_boeken.boek_verkoop_document(
                administratie_id=administratie_id, document_id=credit, actor_id=gescoopte_gebruiker
            )
        geblokkeerd = [r.naam for r in excinfo.value.rapport.resultaten if not r.ok]
        assert "creditnota_herleiding" in geblokkeerd

    def test_webhook_outbox_bij_vastgoed_administratie(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"),
                {"id": administratie_id},
            )
        client = FakeVerkoopClient()
        _patch_client(monkeypatch, client)
        document_id = _upload_en_bevestig(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )
        verkoop_boeken.boek_verkoop_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        with scoped_session(administratie_id) as session:
            [rij] = session.scalars(
                select(WebhookUitgaand).where(WebhookUitgaand.document_id == document_id)
            ).all()
            assert rij.event == "factuur_geboekt"
            data = rij.payload["data"]
            assert data["soort"] == "verkoopfactuur"
            assert data["referentie"] == "VF-2026-0042"  # het Vastly-factuurnummer, §3 v1.10
            assert data["debiteur"]["naam"] == "J. van den Berg"
            assert data["is_creditnota"] is False
            assert data["regels"][0]["grootboek_code"] == "8000"
            assert "handtekening" not in rij.payload  # tekenen gebeurt per verzendpoging

    def test_soortpoort_weigert_inkoopfactuur(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        from app.documenten import service as documenten_service

        client = FakeVerkoopClient()
        _patch_client(monkeypatch, client)
        resultaat = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.pdf",
            inhoud=b"%PDF-1.4 inkoop",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with pytest.raises(documenten_boeken.OngeldigeBoekpoging, match="alleen voor verkoopfacturen"):
            verkoop_boeken.boek_verkoop_document(
                administratie_id=administratie_id,
                document_id=resultaat.document_id,
                actor_id=gescoopte_gebruiker,
            )

    def test_rlz_fout_zet_boeken_mislukt_en_retry_is_idempotent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
    ) -> None:
        from app.documenten.models import Document

        client = FakeVerkoopClient(faal_op="verkoop_boeken")
        _patch_client(monkeypatch, client)
        document_id = _upload_en_bevestig(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )
        with pytest.raises(documenten_boeken.RlzBoekingMislukt):
            verkoop_boeken.boek_verkoop_document(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
            )
        with scoped_session(administratie_id) as session:
            document = session.get(Document, document_id)
            assert document.status is DocumentStatus.BOEKEN_MISLUKT
        # Retry raakt exact hetzelfde client-GUID en slaagt zodra RLZ meewerkt.
        client.faal_op = None
        resultaat = verkoop_boeken.boek_verkoop_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status is DocumentStatus.GEBOEKT
        assert len(client.sales_invoices) == 1

    def test_debiteur_lookup_fout_is_zichtbare_boekfout(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
    ) -> None:
        client = FakeVerkoopClient(faal_op="customer_lookup")
        _patch_client(monkeypatch, client)
        document_id = _upload_en_bevestig(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )
        with pytest.raises(documenten_boeken.RlzBoekingMislukt, match="duplicaatcheck"):
            verkoop_boeken.boek_verkoop_document(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
            )

    def test_volumerem_geldt_onverkort(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
        boeken_aan: None,
    ) -> None:
        from app.config import settings

        client = FakeVerkoopClient()
        _patch_client(monkeypatch, client)
        monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 0)
        document_id = _upload_en_bevestig(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )
        with pytest.raises(documenten_boeken.VolumeremBereikt):
            verkoop_boeken.boek_verkoop_document(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
            )
