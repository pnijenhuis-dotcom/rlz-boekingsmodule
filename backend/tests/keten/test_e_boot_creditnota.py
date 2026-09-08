"""Casus (e) — BOOT organiserend ingenieursburo 202633199: UBL CreditNote (381) + PDF, Kempen Facilities (mail 31-08
'Fw: Factuur betreffende Ulestraten'). Productie: de UBL (54b55252) werd 'dubbel' verwijderd, de PDF (357faef3) kreeg
via de AI negatieve bedragen (-1.775,98) en staat ter accordering. De UBL-bedragen zijn positief (CreditNote-conventie)
— in het boekvoorstel hoort een creditnota NEGATIEF te staan (negatieve regels accepteren, praktijkles)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.documenten.models import DocumentStatus
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import TAXRATE_HOOG, Keten

CASUS = Casus(casussen.E_BOOT)
XML, PDF = CASUS.xml_bestandsnaam(), CASUS.pdf_bestandsnaam()
AFZENDER = "facturen@kempenrecreatie.example"


@pytest.fixture
def kempen(keten: Keten, admin_engine: Engine) -> Keten:
    """Dezelfde testadministratie heet voor deze casus 'Kempen Facilities B.V.' (de tenaamstelling op de UBL)."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET naam = 'Kempen Facilities B.V.', project_verplicht = false WHERE id = :id"),
            {"id": keten.administratie_id},
        )
    keten.splitsing.standaard_tenaamstelling = "Kempen Facilities B.V."
    return keten


class TestUblCreditnota:
    def test_intake_bundel_en_herkenning_creditnota(self, kempen: Keten) -> None:
        pdf = CASUS.pdf()
        resultaat = kempen.mail([(PDF, pdf), (XML, CASUS.xml())], afzender=AFZENDER, onderwerp="Fw: Factuur")
        per_naam = {r.bestandsnaam: r for r in resultaat.bijlagen}
        assert per_naam[XML].uitkomst == "toegewezen" and per_naam[PDF].uitkomst == "gebundeld"
        document_id = per_naam[XML].document_id
        assert kempen.status(document_id) == DocumentStatus.TE_CONTROLEREN
        assert kempen.ai.aanroepen == []
        veldvoorstel = kempen.document(document_id).veldvoorstel
        assert veldvoorstel["is_creditnota"] is True
        assert veldvoorstel["gecrediteerde_factuurnummers"] == ["1234"]
        assert veldvoorstel["referenties"] == ["P25-0699"]
        assert veldvoorstel["leverancier_naam"] == "BOOT organiserend ingenieursburo B.V."
        rij = kempen.lijst_rij(document_id)
        assert rij is not None and rij["leverancier"] == "BOOT organiserend ingenieursburo B.V."
        voorstel = kempen.prefill(document_id)
        assert voorstel.vendor_id == kempen.vendors["boot"] and voorstel.referentie == "202633199"

    def test_creditnota_bedragen_negatief_in_prefill_en_lijst(self, kempen: Keten) -> None:
        resultaat = kempen.mail([(XML, CASUS.xml())], afzender=AFZENDER)
        document_id = resultaat.bijlagen[0].document_id
        voorstel = kempen.prefill(document_id)
        assert voorstel.totaalbedrag == Decimal("-1775.98")
        assert [(r.netto_bedrag, r.btw_bedrag) for r in voorstel.regels] == [(Decimal("-1467.75"), Decimal("-308.23"))]
        rij = kempen.lijst_rij(document_id)
        assert Decimal(rij["totaalbedrag"]) == Decimal("-1775.98")


class TestPdfCreditnota:
    def test_ai_leest_negatieve_bedragen_regeltelling_sluit(self, kempen: Keten) -> None:
        pdf = CASUS.pdf()
        kempen.ai.registreer(pdf, CASUS.ai_antwoord())
        resultaat = kempen.mail([(PDF, pdf)], afzender=AFZENDER)
        document_id = resultaat.bijlagen[0].document_id
        assert kempen.status(document_id) == DocumentStatus.TE_CONTROLEREN
        voorstel = kempen.prefill(document_id)
        assert voorstel.vendor_id == kempen.vendors["boot"]  # fuzzy 'bv' ↔ 'B.V.' + btw-nummer
        assert voorstel.referentie == "202633199"
        assert voorstel.totaalbedrag == Decimal("-1775.98")
        assert [(r.netto_bedrag, r.btw_bedrag, r.taxrate_id) for r in voorstel.regels] == [
            (Decimal("-1467.75"), Decimal("-308.23"), TAXRATE_HOOG)
        ]
        kempen.open_controlescherm(document_id)
        checks = kempen.checks(document_id)
        assert checks["Regeltelling vs totaal"][0], checks["Regeltelling vs totaal"][1]
        assert checks["Duplicaatcheck"][0]
        rij = kempen.lijst_rij(document_id)
        assert Decimal(rij["totaalbedrag"]) == Decimal("-1775.98")
