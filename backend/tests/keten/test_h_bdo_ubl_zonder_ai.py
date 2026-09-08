"""Casus (h) — BDO Accountancy, Tax & Legal 6088744: UBL mét ingesloten PDF + dezelfde PDF als losse bijlage, in één
mail van administratie@universal-steigerbouw (productie 02-09: doc bc5da422, huls 6119694a, derde exemplaar 23465af9).
Een UBL gaat NOOIT naar de AI; de PDF is het beeld. Doelgedrag blok 3: alle kopvelden rechtstreeks uit de XML."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.documenten.models import DocumentStatus
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.H_BDO)


@pytest.fixture
def bdo(keten: Keten):
    pdf = CASUS.pdf()
    resultaat = keten.mail([(CASUS.xml_bestandsnaam(), CASUS.xml(ingesloten_pdf=pdf)), (CASUS.pdf_bestandsnaam(), pdf)])
    return resultaat


class TestIntakeEnBundeling:
    def test_ubl_plus_pdf_wordt_een_document_pdf_is_beeld_geen_ai(self, keten: Keten, bdo) -> None:
        uitkomsten = [(r.bestandsnaam, r.uitkomst) for r in bdo.bijlagen]
        assert uitkomsten == [(CASUS.xml_bestandsnaam(), "toegewezen"), (CASUS.pdf_bestandsnaam(), "gebundeld")]
        document_id = bdo.bijlagen[0].document_id
        assert bdo.bijlagen[1].document_id == document_id
        rij = keten.rij(document_id)
        assert rij["status"] == "te_controleren"
        assert rij["bron_bestandsnaam"] == CASUS.pdf_bestandsnaam()
        assert rij["administratie_id"] == keten.administratie_id
        assert keten.ai.aanroepen == [], "een UBL gaat nooit naar de AI"
        assert keten.splitsing.aanroepen == [], "een gebundelde PDF gaat niet door de splitsings-AI"

    def test_verschijnt_in_de_standaardlijst_met_kopgegevens_uit_de_ubl(self, keten: Keten, bdo) -> None:
        document_id = bdo.bijlagen[0].document_id
        rij = keten.lijst_rij(document_id)
        assert rij is not None
        assert rij["status"] == "te_controleren"
        assert rij["leverancier"] == "BDO Accountancy, Tax & Legal B.V."
        assert Decimal(rij["totaalbedrag"]) == Decimal("6655.00")
        assert rij["factuurdatum"] == "2026-07-02"
        assert rij["samengevoegde_exemplaren"] == 0
        assert rij["toegewezen_aan"] is None


class TestPrefillEnChecks:
    def test_prefill_uit_ubl_crediteur_referentie_bedrag_datum_regel(self, keten: Keten, bdo) -> None:
        document_id = bdo.bijlagen[0].document_id
        voorstel = keten.prefill(document_id)
        assert voorstel.vendor_id == keten.vendors["bdo"]
        assert voorstel.referentie == "6088744"
        assert voorstel.factuurdatum.isoformat() == "2026-07-02"
        assert voorstel.totaalbedrag == Decimal("6655.00")
        assert len(voorstel.regels) == 1
        assert voorstel.regels[0].netto_bedrag == Decimal("5500.00")
        assert voorstel.regels[0].btw_bedrag == Decimal("1155.00")
        assert voorstel.periode is not None and (voorstel.periode.jaar, voorstel.periode.week_van) == (2026, 27)

    def test_duplicaatcheck_nooit_kan_niet_controleren_bij_een_ubl(self, keten: Keten, bdo) -> None:
        document_id = bdo.bijlagen[0].document_id
        keten.open_controlescherm(document_id)
        checks = keten.checks(document_id)
        ok, melding = checks["Duplicaatcheck"]
        assert ok and "Kan niet controleren" not in melding
        assert checks["Regeltelling vs totaal"][0]
        assert checks["Duplicaat (module)"][0]
        assert not checks["Verplichte velden"][0]
        # Zonder geheugen ontbreken alleen grootboek/btw-code/project op de ene regel — nooit crediteur/referentie.
        assert "crediteur" not in checks["Verplichte velden"][1]
        assert "referentie" not in checks["Verplichte velden"][1]

    def test_ubl_kopvelden_rechtstreeks_uit_de_xml(self, keten: Keten, bdo) -> None:
        document_id = bdo.bijlagen[0].document_id
        veldvoorstel = keten.document(document_id).veldvoorstel
        assert veldvoorstel is not None
        assert veldvoorstel.get("iban") == "NL95KETN1000000010"
        assert veldvoorstel.get("kvk_nummer") == "91000006"
        assert veldvoorstel.get("btw_nummer") == "NL100039595B01"
        assert veldvoorstel.get("vervaldatum") == "2026-07-16"
        voorstel = keten.prefill(document_id)
        assert voorstel.vervaldatum is not None and voorstel.vervaldatum.isoformat() == "2026-07-16"

    def test_ubl_regel_draagt_btw_code_en_omschrijving(self, keten: Keten, bdo) -> None:
        document_id = bdo.bijlagen[0].document_id
        voorstel = keten.prefill(document_id)
        regel = voorstel.regels[0]
        assert regel.taxrate_id == TAXRATE_HOOG
        assert regel.omschrijving == "Samenstellen jaarrekening en aangifte vennootschapsbelasting 2025"


class TestExport:
    def test_exporteer_frontend_fixture(self, keten: Keten, bdo) -> None:
        """Schrijft de DTO-stand van deze casus voor het frontend-harnas (harness-keten.html?casus=h)."""
        document_id = bdo.bijlagen[0].document_id
        keten.exporteer("h_bdo", document_id, extra={"stamgegevens": {"grootboek_advies": str(GB_ADVIES)}})
        assert keten.status(document_id) == DocumentStatus.TE_CONTROLEREN
