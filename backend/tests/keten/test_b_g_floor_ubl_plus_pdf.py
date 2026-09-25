"""Casus (b) + (g) — Floor Bouwliftenservice 26219. Productie 02-09: mail "deel 5" droeg UBL (mét ingesloten PDF) en
dezelfde PDF los; mail "deel 9" droeg exact dezelfde twee bijlagen nog eens (byte-identiek). Uitkomst toen: doc
647b9bde + huls 4f981bc3, tweede exemplaar 2f961933 (afgewezen als duplicaat 07-09) + huls ad57853e.
(b) UBL+PDF = bundel, nooit duplicaat; (g) byte-identieke PDF uit twee mails = één werkstuk."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.documenten.models import DocumentStatus
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import PROJECT_25011, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.B_FLOOR)
XML, PDF = CASUS.xml_bestandsnaam(), CASUS.pdf_bestandsnaam()


@pytest.fixture
def deel_5(keten: Keten):
    pdf = CASUS.pdf()
    return keten.mail([(XML, CASUS.xml(ingesloten_pdf=pdf)), (PDF, pdf)], onderwerp="Facturen universal steigerbouw deel 5")


@pytest.fixture
def deel_9(keten: Keten, deel_5):
    pdf = CASUS.pdf()
    return keten.mail([(XML, CASUS.xml(ingesloten_pdf=pdf)), (PDF, pdf)], onderwerp="Facturen universal steigerbouw deel 9")


class TestBundelNooitDuplicaat:
    def test_ubl_en_pdf_uit_een_mail_worden_een_document(self, keten: Keten, deel_5) -> None:
        per_naam = {r.bestandsnaam: r for r in deel_5.bijlagen}
        assert per_naam[XML].uitkomst == "toegewezen"
        assert per_naam[PDF].uitkomst == "gebundeld"
        assert per_naam[PDF].document_id == per_naam[XML].document_id
        assert "ingesloten_pdf_hash" in (per_naam[PDF].detail or "")
        document_id = per_naam[XML].document_id
        assert keten.status(document_id) == DocumentStatus.TE_CONTROLEREN
        assert keten.rij(document_id)["mogelijk_duplicaat_van_id"] is None
        assert keten.ai.aanroepen == []
        checks_module = keten.document(document_id)
        assert checks_module.duplicaat_referentie is None

    def test_lijst_en_prefill(self, keten: Keten, deel_5) -> None:
        document_id = deel_5.bijlagen[0].document_id
        rij = keten.lijst_rij(document_id)
        assert rij is not None and rij["leverancier"] == "Floor Bouwliftenservice"
        assert Decimal(rij["totaalbedrag"]) == Decimal("2516.80") and rij["factuurdatum"] == "2026-08-13"
        voorstel = keten.prefill(document_id)
        assert voorstel.vendor_id == keten.vendors["floor"]
        assert voorstel.referentie == "26219" and voorstel.totaalbedrag == Decimal("2516.80")
        keten.open_controlescherm(document_id)
        checks = keten.checks(document_id)
        assert checks["Duplicaatcheck"][0] and checks["Duplicaat (module)"][0]
        assert checks["Regeltelling vs totaal"][0]

    def test_ubl_regels_en_project_rechtstreeks_uit_de_xml(self, keten: Keten, deel_5) -> None:
        document_id = deel_5.bijlagen[0].document_id
        voorstel = keten.prefill(document_id)
        assert [r.netto_bedrag for r in voorstel.regels] == [Decimal("330.00"), Decimal("1400.00"), Decimal("350.00")]
        assert all(r.taxrate_id == TAXRATE_HOOG for r in voorstel.regels)
        assert all(r.project_id == PROJECT_25011 for r in voorstel.regels)
        assert voorstel.vervaldatum is not None and voorstel.vervaldatum.isoformat() == "2026-09-12"


class TestByteIdentiekeDubbelUitTweedeMail:
    def test_tweede_mail_levert_geen_tweede_werkstuk(self, keten: Keten, deel_5, deel_9) -> None:
        eerste = deel_5.bijlagen[0].document_id
        tweede = deel_9.bijlagen[0].document_id
        assert tweede != eerste
        assert deel_9.bijlagen[1].uitkomst == "gebundeld"
        ids = keten.standaardlijst_ids()
        assert str(eerste) in ids and str(tweede) not in ids
        assert keten.status(tweede) in (DocumentStatus.AFGEVOERD_DUPLICAAT, DocumentStatus.SAMENGEVOEGD)
        assert keten.rij(tweede)["toegewezen_aan"] is None  # casus j
        assert keten.status(eerste) == DocumentStatus.TE_CONTROLEREN
        # Het echte document blijft schoon: geen "mogelijk duplicaat"-verdenking op het werkstuk zelf.
        assert keten.lijst_rij(eerste)["mogelijk_duplicaat_van"] is None

    def test_reden_en_verwijzing_op_het_afgevoerde_exemplaar(self, keten: Keten, deel_5, deel_9) -> None:
        eerste = deel_5.bijlagen[0].document_id
        tweede = deel_9.bijlagen[0].document_id
        rij = keten.lijst_rij(tweede, toon_afgehandeld="true")
        assert rij is not None
        verwijzing = rij.get("duplicaat_van") or rij.get("samengevoegd_in")
        assert verwijzing is not None and verwijzing["document_id"] == str(eerste)
        if keten.status(tweede) == DocumentStatus.AFGEVOERD_DUPLICAAT:
            afwijzing = keten.afwijzing(tweede)
            assert afwijzing is not None and afwijzing["automatisch"] is True
            assert afwijzing["duplicaat_van_document_id"] == eerste
            assert afwijzing["toegewezen_aan"] is None
            assert "26219" in afwijzing["reden"]

    def test_echte_document_draagt_chip_exemplaren_samengevoegd(self, keten: Keten, deel_5, deel_9) -> None:
        """Blok 4 (08-09): het byte-identieke exemplaar uit de tweede mail is `afgevoerd_duplicaat` (categorie a) óf
        `samengevoegd` — beide tellen op het echte document als exemplaar (chip "1 exemplaar
        samengevoegd/afgevoerd")."""
        eerste = deel_5.bijlagen[0].document_id
        assert keten.lijst_rij(eerste)["samengevoegde_exemplaren"] == 1

    def test_exporteer_frontend_fixture(self, keten: Keten, deel_5, deel_9) -> None:
        keten.exporteer("b_floor", deel_5.bijlagen[0].document_id)


class TestPdfZonderUblUitTweeMails:
    """Casus (g) zuiver: alleen de PDF (geen UBL) twee keer — de AI leest 'm één keer, het tweede exemplaar is dubbel."""

    def test_pdf_dubbel_uit_twee_mails(self, keten: Keten) -> None:
        pdf = CASUS.pdf()
        keten.ai.registreer(pdf, CASUS.ai_antwoord())
        eerste = keten.mail([(PDF, pdf)], onderwerp="Floor factuur").bijlagen[0].document_id
        assert keten.status(eerste) == DocumentStatus.TE_CONTROLEREN
        assert len(keten.ai.aanroepen) == 1
        voorstel = keten.prefill(eerste)
        assert voorstel.vendor_id == keten.vendors["floor"] and voorstel.referentie == "26219"
        assert [r.netto_bedrag for r in voorstel.regels] == [Decimal("330.00"), Decimal("1400.00"), Decimal("350.00")]

        tweede = keten.mail([(PDF, pdf)], onderwerp="Floor factuur (nogmaals)").bijlagen[0].document_id
        assert tweede != eerste
        assert str(tweede) not in keten.standaardlijst_ids()
        assert keten.status(tweede) == DocumentStatus.AFGEVOERD_DUPLICAAT
        afwijzing = keten.afwijzing(tweede)
        assert afwijzing is not None and afwijzing["duplicaat_van_document_id"] == eerste
        assert afwijzing["toegewezen_aan"] is None and afwijzing["automatisch"] is True
        assert keten.status(eerste) == DocumentStatus.TE_CONTROLEREN


class TestVastlySuffixStam:
    """Blok 1 bundelrun 24-09 (Vastly-batch 23-09): de UBL-exporteur plakt `-ubl` achter de factuurstam en de UBL
    draagt géén ingesloten PDF — de hash-regel kan niets, de oude exacte-stam-regel zag `…-ubl` ≠ `…` en de PDF landde
    23 keer als losse inkoopfactuur in de werkvoorraad. Sinds 24-09 normaliseert de stam-regel het suffix weg."""

    def test_ubl_met_suffix_zonder_ingesloten_pdf_wordt_alsnog_gebundeld(self, keten: Keten) -> None:
        pdf = CASUS.pdf()
        xml_suffix = XML[:-4] + "-ubl.xml"
        mail = keten.mail([(xml_suffix, CASUS.xml(ingesloten_pdf=b"")), (PDF, pdf)], onderwerp="Facturen oktober")
        per_naam = {r.bestandsnaam: r for r in mail.bijlagen}
        assert per_naam[xml_suffix].uitkomst == "toegewezen"
        assert per_naam[PDF].uitkomst == "gebundeld" and "naamstam" in (per_naam[PDF].detail or "")
        assert per_naam[PDF].document_id == per_naam[xml_suffix].document_id
        document_id = per_naam[xml_suffix].document_id
        assert keten.status(document_id) == DocumentStatus.TE_CONTROLEREN
        assert keten.ai.aanroepen == []  # de PDF ging nooit naar de AI
        # Geen tweede werkstuk: precies één document uit deze mail in de standaardlijst.
        ids = keten.standaardlijst_ids()
        assert str(document_id) in ids
        rij = keten.lijst_rij(document_id)
        assert rij is not None and rij["leverancier"] == "Floor Bouwliftenservice"


class TestSchrijfwijzeFloor:
    """Blok 2 feedbackrun A 25-09 (FV-21): een factuur mét een afwijkende schrijfwijze van de leveranciersnaam landt op
    dezelfde crediteur (één normalisatie `app/crediteuren/naam.py`, óók in de extractie-match) — geen nieuwe
    crediteur."""

    def test_afwijkende_schrijfwijze_matcht_dezelfde_crediteur(self, keten: Keten, deel_5) -> None:
        from app.db.session import scoped_session
        from app.documenten.crediteur_kenmerk import kandidaten_met_kenmerken
        from app.extractie.controle import match_vendor_met_waarschuwing

        with scoped_session(keten.administratie_id) as session:
            kandidaten = kandidaten_met_kenmerken(session, administratie_id=keten.administratie_id)
        for schrijfwijze in ("Floor bouwliftenservice", "FLOOR BOUWLIFTENSERVICE B.V.", "Floor Bouwliftenservice"):
            vendor_id, _, waarschuwing = match_vendor_met_waarschuwing(schrijfwijze, kandidaten)
            assert vendor_id == keten.vendors["floor"] and waarschuwing is None, schrijfwijze
