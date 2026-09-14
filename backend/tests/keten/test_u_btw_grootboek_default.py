"""Casus (u) — btw-code uit de standaard van de grootboekrekening (opdracht Peter 14-09, casus L.H.G. Holding "Kosten
mobiele telefonie"; migratie 0142). Gespeeld op de Floor-PDF (casus b/g: drie regels zónder leesbaar btw-bedrag, dus
geen factuur-afleiding): het regel-geheugen zet de rekening "Huur materieel" op regel 1, die rekening draagt in de
bron een standaard-btw-tarief (RLZ `PreferentialTaxRate` → `grootboekrekening.standaard_taxrate_id`) → de btw volgt
mét herkomst 'grootboek' (chip "standaard grootboek"), de autosave persisteert 'm en de checks zien dezelfde btw."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import update

from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten.regel_prefill import BTW_BRON_GROOTBOEK
from app.geheugen.models import BoekingObservatie
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_HUUR_MATERIEEL, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.B_FLOOR)
PDF = CASUS.pdf_bestandsnaam()


@pytest.fixture
def floor_met_grootboek_default(keten: Keten) -> uuid.UUID:
    # De bron (RLZ-sync) zette het standaard-tarief op de rekening; het regel-geheugen kent "Huur per werkdag".
    with scoped_session(keten.administratie_id) as session:
        session.execute(
            update(Grootboekrekening)
            .where(Grootboekrekening.ledger_id == GB_HUUR_MATERIEEL)
            .values(standaard_taxrate_id=TAXRATE_HOOG)
        )
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=keten.administratie_id,
                vendor_id=keten.vendors["floor"],
                regel_sleutel=normaliseer_regel_sleutel("Huur per werkdag"),
                gb_id=GB_HUUR_MATERIEEL,
                btw_id=None,  # het geheugen zegt niets over de btw — anders wint het geheugen (stap 3)
                bron="app",
                bron_datum=date(2026, 8, 1),
                boekstuk_ref="RLZ-04-00003100",
            )
        )
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    return keten.upload(PDF, pdf).document_id


class TestBtwVolgtDeGrootboekrekening:
    def test_prefill_btw_uit_de_rekening_met_herkomst_grootboek(
        self, keten: Keten, floor_met_grootboek_default: uuid.UUID
    ) -> None:
        voorstel = keten.prefill(floor_met_grootboek_default)
        huur = voorstel.regels[0]
        assert huur.omschrijving == "Huur per werkdag"
        assert huur.ledger_id == GB_HUUR_MATERIEEL and huur.gb_bron == "geheugen"
        assert (huur.taxrate_id, huur.btw_bron) == (TAXRATE_HOOG, BTW_BRON_GROOTBOEK)
        assert huur.prefill_herkomst is not None and huur.prefill_herkomst["btw"] == BTW_BRON_GROOTBOEK
        # Elke regel mét die rekening krijgt de default; een regel zonder rekening blijft leeg.
        for regel in voorstel.regels:
            if regel.ledger_id == GB_HUUR_MATERIEEL:
                assert (regel.taxrate_id, regel.btw_bron) == (TAXRATE_HOOG, BTW_BRON_GROOTBOEK)
            else:
                assert regel.taxrate_id is None

    def test_controlescherm_dto_autosave_en_checks_zien_dezelfde_btw(
        self, keten: Keten, floor_met_grootboek_default: uuid.UUID
    ) -> None:
        dto = keten.open_controlescherm(floor_met_grootboek_default)
        huur = dto["regels"][0]
        assert huur["taxrate_id"] == str(TAXRATE_HOOG) and huur["btw_bron"] == BTW_BRON_GROOTBOEK
        # A10-autosave: de herkomst 'grootboek' is een trigger — het voorstel staat opgeslagen mét de btw.
        assert any("btw regel 1: grootboek" in str(detail) for detail in keten.tijdlijn(floor_met_grootboek_default))
        checks = keten.checks(floor_met_grootboek_default)
        ok, melding = checks["Verplichte velden"]
        assert "btw" not in melding.lower(), melding  # de btw ontbreekt niet meer; project/andere regels mogelijk wel
        # Heropenen: de chip komt terug zolang de waarde de prefill is (waarde-gelijkheid, snapshot-regel).
        opnieuw = keten.open_controlescherm(floor_met_grootboek_default)
        assert opnieuw["regels"][0]["btw_bron"] == BTW_BRON_GROOTBOEK

    def test_zonder_default_op_de_rekening_blijft_de_btw_leeg(self, keten: Keten) -> None:
        with scoped_session(keten.administratie_id) as session:
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=keten.administratie_id,
                    vendor_id=keten.vendors["floor"],
                    regel_sleutel=normaliseer_regel_sleutel("Huur per werkdag"),
                    gb_id=GB_HUUR_MATERIEEL,
                    btw_id=None,
                    bron="app",
                    bron_datum=date(2026, 8, 1),
                    boekstuk_ref="RLZ-04-00003100",
                )
            )
        pdf = CASUS.pdf()
        keten.ai.registreer(pdf, CASUS.ai_antwoord())
        document_id = keten.upload(PDF, pdf).document_id
        huur = keten.prefill(document_id).regels[0]
        assert huur.ledger_id == GB_HUUR_MATERIEEL and huur.taxrate_id is None and huur.btw_bron is None
