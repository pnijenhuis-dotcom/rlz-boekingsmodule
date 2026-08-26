"""Rechtsgeldige factuur-PDF bij de doorbelasting (blok A 26-08, A5-tests): nummer =
spiegel-Reference, btw-som = verkoopfactuur-btw, centen identiek aan de boeking (grootste-rest),
factuur als EERSTE bijlage op de spiegel + tweede bijlage op de bron-verkoop, ontbreken = zichtbaar
mét reden en nooit blokkerend, spiegel-alsnog-pad, en de pure tekst-toets op de échte RLZ-render."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select

from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.documenten.rlz_ids import (
    rlz_doorbelasting_factuur_upload_id,
    rlz_doorbelasting_spiegel_id,
    rlz_doorbelasting_upload_id,
    rlz_doorbelasting_verkoop_id,
)
from app.documenten.service import _standaard_opslag
from app.doorbelasting import service as doorbelasting_service
from app.doorbelasting.boeken import boek_spiegel_alsnog
from app.doorbelasting.factuur import (
    FACTUUR_STATUS_AANWEZIG,
    FACTUUR_STATUS_ONTBREEKT,
    FactuurVerwachting,
    controleer_factuur_tekst,
    factuur_bestandsnaam,
    nl_bedrag,
    pdf_tekst,
)
from app.doorbelasting.factuur_herstel import herstel_facturen
from app.doorbelasting.models import (
    DoorbelastingBoeking,
    DoorbelastingBoekingStatus,
    DoorbelastingRegel,
    DoorbelastingRunStatus,
)
from tests.doorbelasting.conftest import (
    DOEL_KOSTEN_LEDGER_ID,
    PROVISIE_KOSTEN_LEDGER_ID,
    DoorbelastingOpzet,
    FakeDoorbelastingClient,
    haal_boekingen,
    haal_run,
    maak_administratie,
)
from tests.doorbelasting.test_boeken import _boek

# Letterlijke pypdf-extractie van de RLZ-render op de test-administratie (STAP-0 26-08, factuur
# RLZ-3): gefragmenteerd btw-nummer, bedragen over twee regels — precies wat de toets moet aankunnen.
RLZ_RENDER_TEKST = (
    "Subtotaal (excl. BTW)\n€ 50,00\nBTW 21 % over € 50,00\n€ 10,50\nTe betalen\n€ 60,50\n"
    "Omschrijving\nDatum\nAantal\nPrijs (excl.)\nBedrag (excl.)\nBTW\nwerkzaamheden april\n30-4-2014\n5\n"
    "€ 10,00\n€ 50,00\n21 %\nToxic Assets\nHendrikus Avelinghstraat \n7\n6881\n VP  Velp\nHelmondstraat \n63\n"
    "        KVK: \n60323957\n   IBAN: NL\n59\n KNAB \n0255\n \n2732\n \n58\n        \n6843\n SC Arnhem"
    "         BTW nr: NL\n199235764\nB\n01\n                BIC: KNABNL\n2\nH\nInfo@administratiekantoornijenhuis.nl\n"
    "Factuur\nDatum: 1-5-2014\nFactuurnummer:RLZ-3\nBTW nr. NL813154789B01\nBetreft: administratie werkzaamheden\n"
)


class TestTekstToets:
    def test_echte_rlz_render_is_compleet(self) -> None:
        verwachting = FactuurVerwachting(
            referentie="RLZ-3", netto_totaal=Decimal("40.00"), provisie=Decimal("10.00"), btw_totaal=Decimal("10.50")
        )
        assert controleer_factuur_tekst(RLZ_RENDER_TEKST, verwachting) == []

    def test_een_cent_verschil_valt_door_de_mand(self) -> None:
        # de PDF toont € 10,50 btw en € 60,50 totaal; de boeking zegt 10,51 → beide bedragen ontbreken
        verwachting = FactuurVerwachting(
            referentie="RLZ-3", netto_totaal=Decimal("40.00"), provisie=Decimal("10.00"), btw_totaal=Decimal("10.51")
        )
        ontbrekend = controleer_factuur_tekst(RLZ_RENDER_TEKST, verwachting)
        assert ontbrekend == ["btw-som € 10,51", "totaal incl. € 60,51"]

    def test_verkeerd_nummer_en_ontbrekende_stamgegevens(self) -> None:
        verwachting = FactuurVerwachting(
            referentie="RLZ-4", netto_totaal=Decimal("50.00"), provisie=Decimal("0"), btw_totaal=Decimal("10.50")
        )
        kaal = "Factuur\nFactuurnummer:RLZ-4\nTe betalen € 60,50\nSubtotaal € 50,00\n€ 10,50"
        assert controleer_factuur_tekst(kaal, verwachting) == ["KvK-nummer afzender", "btw-nummer (NL…B..)", "btw-specificatie"]
        assert "factuurnummer RLZ-4" in controleer_factuur_tekst(RLZ_RENDER_TEKST, verwachting)

    @pytest.mark.parametrize(
        ("bedrag", "tekst"),
        [("0.5", "0,50"), ("1607.05", "1.607,05"), ("1234567.8", "1.234.567,80"), ("-12.5", "-12,50"), ("999.999", "1.000,00")],
    )
    def test_nl_bedrag(self, bedrag: str, tekst: str) -> None:
        assert nl_bedrag(Decimal(bedrag)) == tekst

    def test_bestandsnaam_veilig_en_herkenbaar(self) -> None:
        assert factuur_bestandsnaam("RLZ-247123", "Molenhof Verhuur B.V. / Oirschot") == "Factuur RLZ-247123 Molenhof Verhuur B.V.  Oirschot.pdf"


class TestFactuurInDeMotor:
    def test_happy_path_factuur_op_beide_kanten_centen_identiek(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        resultaat = _boek(opzet, beheerder_id, bron=bron, doel=doel)
        assert resultaat == {str(opzet.mapping.id): DoorbelastingBoekingStatus.GEBOEKT.value}

        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        assert boeking.factuur_pdf_status == FACTUUR_STATUS_AANWEZIG
        assert boeking.factuur_pdf_reden is None
        assert boeking.factuur_pdf_bestandsnaam == factuur_bestandsnaam(boeking.verkoop_referentie, opzet.mapping.doelentiteit_naam)
        assert boeking.factuur_pdf_op is not None
        # één render, ná de verkoopboeking (nummer bestaat dan pas)
        verkoop_id = rlz_doorbelasting_verkoop_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        assert bron.factuur_renders == [str(verkoop_id)]

        # A5: nummer = spiegel-Reference; btw-som en totaal in de PDF = de geboekte centen
        spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        assert doel.purchase_invoices[str(spiegel_id)]["Reference"] == boeking.verkoop_referentie
        pdf = _standaard_opslag().lezen(pad=boeking.factuur_pdf_opslag_pad)
        tekst = pdf_tekst(pdf)
        assert f"Factuurnummer:{boeking.verkoop_referentie}" in tekst
        assert f"€ {nl_bedrag(boeking.btw_bedrag)}" in tekst
        assert f"€ {nl_bedrag(boeking.netto_totaal + boeking.provisie_bedrag + boeking.btw_bedrag)}" in tekst
        # en de RLZ-regelsom (wat RLZ rendert) is per constructie exact onze boeking
        regels = bron.sales_invoices[str(verkoop_id)]["DocumentLineList"]
        assert sum(Decimal(str(r["TaxAmount"])) for r in regels) == boeking.btw_bedrag

        # A3: spiegel = factuur EERST (hoofdbijlage), dan de originele bon; bron = bon, dan factuur
        spiegel_uploads = doel.get(f"PurchaseInvoices/{spiegel_id}/Uploads")["value"]
        assert [u["FileName"] for u in spiegel_uploads] == [boeking.factuur_pdf_bestandsnaam, "factuur-doorbelasting.pdf"]
        assert spiegel_uploads[0]["upload_id"] == str(
            rlz_doorbelasting_factuur_upload_id(opzet.document_id, opzet.mapping.doel_customer_guid, kant="spiegel")
        )
        assert spiegel_uploads[1]["upload_id"] == str(
            rlz_doorbelasting_upload_id(opzet.document_id, opzet.mapping.doel_customer_guid, kant="spiegel")
        )
        verkoop_uploads = bron.get(f"SalesInvoices/{verkoop_id}/Uploads")["value"]
        assert [u["FileName"] for u in verkoop_uploads] == ["factuur-doorbelasting.pdf", boeking.factuur_pdf_bestandsnaam]

    def test_render_mislukt_boekt_gewoon_door_met_zichtbare_reden(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron, doel = FakeDoorbelastingClient(faal_op="factuur_render"), FakeDoorbelastingClient()
        resultaat = _boek(opzet, beheerder_id, bron=bron, doel=doel)
        assert resultaat == {str(opzet.mapping.id): DoorbelastingBoekingStatus.GEBOEKT.value}
        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        assert boeking.status == DoorbelastingBoekingStatus.GEBOEKT.value
        assert boeking.factuur_pdf_status == FACTUUR_STATUS_ONTBREEKT
        assert "RLZ-factuurrender mislukt (500)" in (boeking.factuur_pdf_reden or "")
        assert boeking.factuur_pdf_opslag_pad is None
        # spiegel draagt dan alleen de bon; run zelf GEBOEKT zonder run-fout
        spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        assert [u["FileName"] for u in doel.get(f"PurchaseInvoices/{spiegel_id}/Uploads")["value"]] == [
            "factuur-doorbelasting.pdf"
        ]
        assert haal_run(opzet.administratie_id, opzet.run.id).status == DoorbelastingRunStatus.GEBOEKT.value

    def test_onvolledige_layout_geeft_nooit_een_onvolledige_factuur(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron, doel = FakeDoorbelastingClient(faal_op="factuur_onvolledig"), FakeDoorbelastingClient()
        _boek(opzet, beheerder_id, bron=bron, doel=doel)
        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        assert boeking.factuur_pdf_status == FACTUUR_STATUS_ONTBREEKT
        assert "KvK-nummer afzender" in boeking.factuur_pdf_reden
        assert "btw-nummer" in boeking.factuur_pdf_reden
        assert "RLZ-UI" in boeking.factuur_pdf_reden
        spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        assert len(doel.get(f"PurchaseInvoices/{spiegel_id}/Uploads")["value"]) == 1

    def test_spiegel_alsnog_krijgt_de_factuur_als_eerste_bijlage(
        self, spiegel_open_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = spiegel_open_opzet
        bron = FakeDoorbelastingClient()
        _boek(opzet, beheerder_id, bron=bron, doel=None)
        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        assert boeking.status == DoorbelastingBoekingStatus.SPIEGEL_OPEN.value
        # bron-kant al compleet: factuur gerenderd, bewaard en op de verkoop gezet
        assert boeking.factuur_pdf_status == FACTUUR_STATUS_AANWEZIG
        assert boeking.factuur_pdf_opslag_pad is not None

        doel_administratie = maak_administratie(admin_engine, "Veldhoven Recreatie B.V.")
        doorbelasting_service.wijzig_mapping(
            administratie_id=opzet.administratie_id,
            mapping_id=opzet.mapping.id,
            actor_id=beheerder_id,
            doel_administratie_id=doel_administratie,
            provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
        )
        with scoped_session(opzet.administratie_id, actor_id=beheerder_id) as session:
            for regel in session.scalars(select(DoorbelastingRegel).where(DoorbelastingRegel.run_id == opzet.run.id)):
                regel.doel_kosten_ledger_id = DOEL_KOSTEN_LEDGER_ID
        doel = FakeDoorbelastingClient()
        na = boek_spiegel_alsnog(
            administratie_id=opzet.administratie_id, boeking_id=boeking.id, actor_id=beheerder_id, doel_client=doel
        )
        assert na.status == DoorbelastingBoekingStatus.GEBOEKT.value
        assert na.factuur_pdf_status == FACTUUR_STATUS_AANWEZIG
        spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        assert [u["FileName"] for u in doel.get(f"PurchaseInvoices/{spiegel_id}/Uploads")["value"]] == [
            boeking.factuur_pdf_bestandsnaam,
            "factuur-doorbelasting.pdf",
        ]
        # de bewaarkopie is hergebruikt: geen tweede render nodig
        assert bron.factuur_renders == [str(rlz_doorbelasting_verkoop_id(opzet.document_id, opzet.mapping.doel_customer_guid))]


class TestHerstelEnDownload:
    """A4: `make doorbelasting-facturen-herstel` — dry-run raakt niets, echte run zet de factuur op
    beide kanten zonder herboeking, per boeking geauditeerd; plus de download-leesroute."""

    def _boeking_zonder_factuur(self, opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID):
        bron, doel = FakeDoorbelastingClient(faal_op="factuur_render"), FakeDoorbelastingClient()
        _boek(opzet, beheerder_id, bron=bron, doel=doel)
        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        assert boeking.factuur_pdf_status == FACTUUR_STATUS_ONTBREEKT
        # simuleer een boeking van vóór 26-08 (kolom NULL) — óók een kandidaat
        with scoped_session(opzet.administratie_id, actor_id=beheerder_id) as session:
            rij = session.get(DoorbelastingBoeking, boeking.id)
            rij.factuur_pdf_status = None
            rij.factuur_pdf_reden = None
        return boeking, bron, doel

    def test_dry_run_telt_en_wijzigt_niets(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID) -> None:
        opzet = onboarded_opzet
        boeking, bron, doel = self._boeking_zonder_factuur(opzet, beheerder_id)
        resultaat = herstel_facturen(dry_run=True, actor_id=beheerder_id, client_factory=lambda _aid: bron)
        assert [k.boeking_id for k in resultaat.kandidaten] == [boeking.id]
        assert resultaat.kandidaten[0].huidige_factuur_status is None
        assert resultaat.hersteld == [] and resultaat.mislukt == {}
        assert bron.factuur_renders == []  # dry-run raakt RLZ niet
        assert haal_boekingen(opzet.administratie_id, opzet.run.id)[0].factuur_pdf_status is None

    def test_herstel_zet_factuur_op_beide_kanten_zonder_herboeking(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        boeking, bron, doel = self._boeking_zonder_factuur(opzet, beheerder_id)
        bron.faal_op.discard("factuur_render")  # RLZ is weer bereikbaar
        verkoop_id = rlz_doorbelasting_verkoop_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        puts_voor = (len(bron.sales_invoices), len(doel.purchase_invoices))

        def factory(administratie_id: uuid.UUID):
            return bron if administratie_id == opzet.administratie_id else doel

        resultaat = herstel_facturen(dry_run=False, actor_id=beheerder_id, client_factory=factory)
        assert resultaat.hersteld == [boeking.id] and resultaat.mislukt == {}
        na = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        assert na.factuur_pdf_status == FACTUUR_STATUS_AANWEZIG and na.factuur_pdf_reden is None
        assert na.factuur_pdf_opslag_pad is not None
        # beide kanten dragen de factuur náást de bon; documenten zelf onaangeroerd (geen herboeking)
        assert [u["FileName"] for u in bron.get(f"SalesInvoices/{verkoop_id}/Uploads")["value"]] == [
            "factuur-doorbelasting.pdf",
            na.factuur_pdf_bestandsnaam,
        ]
        assert [u["FileName"] for u in doel.get(f"PurchaseInvoices/{spiegel_id}/Uploads")["value"]] == [
            "factuur-doorbelasting.pdf",
            na.factuur_pdf_bestandsnaam,
        ]
        assert (len(bron.sales_invoices), len(doel.purchase_invoices)) == puts_voor
        assert bron.sales_invoices[str(verkoop_id)]["Status"] == 2
        # audit per run
        with scoped_session(opzet.administratie_id) as session:
            acties = session.scalars(
                select(AuditEvent.actie).where(AuditEvent.record_id == boeking.id, AuditEvent.actie.like("doorbelasting_factuur%"))
            ).all()
        assert acties == ["doorbelasting_factuur_hersteld"]
        # tweede run: geen kandidaten meer (idempotent)
        assert herstel_facturen(dry_run=True, actor_id=beheerder_id).kandidaten == []
        # download-leesroute levert dezelfde bytes als de bijlage
        naam, inhoud = doorbelasting_service.factuur_pdf_van_boeking(
            administratie_id=opzet.administratie_id, boeking_id=boeking.id
        )
        assert naam == na.factuur_pdf_bestandsnaam and inhoud.startswith(b"%PDF")
        assert f"Factuurnummer:{na.verkoop_referentie}" in pdf_tekst(inhoud)

    def test_herstel_mislukt_blijft_zichtbaar_en_geauditeerd(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        boeking, bron, doel = self._boeking_zonder_factuur(opzet, beheerder_id)
        bron.faal_op = {"factuur_onvolledig"}
        resultaat = herstel_facturen(dry_run=False, actor_id=beheerder_id, client_factory=lambda _aid: bron)
        assert resultaat.hersteld == [] and list(resultaat.mislukt) == [boeking.id]
        assert "KvK-nummer afzender" in resultaat.mislukt[boeking.id]
        na = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        assert na.factuur_pdf_status == FACTUUR_STATUS_ONTBREEKT and "KvK" in na.factuur_pdf_reden
        with scoped_session(opzet.administratie_id) as session:
            acties = session.scalars(
                select(AuditEvent.actie).where(AuditEvent.record_id == boeking.id, AuditEvent.actie.like("doorbelasting_factuur%"))
            ).all()
        assert acties == ["doorbelasting_factuur_herstel_mislukt"]
        with pytest.raises(doorbelasting_service.DoorbelastingFout):
            doorbelasting_service.factuur_pdf_van_boeking(administratie_id=opzet.administratie_id, boeking_id=boeking.id)
