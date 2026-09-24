"""Bundeling — stam-normalisatie (`-ubl`/`_ubl`/`-xml`/`_xml`-suffix) + derde regel factuurnummer (blok 1 bundelrun
24-09, casus Vastly-batch 23-09: `factuur-RUB-2026-0031-ubl.xml` + `factuur-RUB-2026-0031.pdf` werden 23 keer NIET
gebundeld en stonden als losse inkoopfacturen in de werkvoorraad). Puur; geen DB."""

from __future__ import annotations

from app.intake.bundeling import (
    REDEN_FACTUURNUMMER,
    REDEN_INGESLOTEN_HASH,
    REDEN_NAAMSTAM,
    BijlagePaar,
    bundel_bijlagen,
    genormaliseerde_stam,
    pdf_draagt_factuurnummer,
    ubl_factuurnummer,
)
from tests.extractie.pdf_helper import maak_tekst_pdf
from tests.intake.conftest import bouw_pdf, bouw_ubl
from tests.intake.test_bundeling_en_samenvoegen import bijlage, bouw_ubl_met_pdf


class TestGenormaliseerdeStam:
    def test_suffixen_worden_gestript_hoofdletterongevoelig(self) -> None:
        assert genormaliseerde_stam("factuur-RUB-2026-0031-ubl.xml") == "factuur-rub-2026-0031"
        assert genormaliseerde_stam("factuur-RUB-2026-0031_UBL.xml") == "factuur-rub-2026-0031"
        assert genormaliseerde_stam("factuur-RUB-2026-0031-xml.pdf") == "factuur-rub-2026-0031"
        assert genormaliseerde_stam("factuur-RUB-2026-0031.pdf") == "factuur-rub-2026-0031"

    def test_alleen_een_echt_suffix_niet_middenin_de_naam(self) -> None:
        assert genormaliseerde_stam("ubl-factuur-1.xml") == "ubl-factuur-1"
        assert genormaliseerde_stam("factuur-ubl-1.xml") == "factuur-ubl-1"


class TestStamRegel:
    def test_vastly_tweeling_wordt_een_paar_op_naamstam(self) -> None:
        ubl = bijlage("factuur-RUB-2026-0031-ubl.xml", bouw_ubl(factuurnummer="RUB-2026-0031"))
        pdf = bijlage("factuur-RUB-2026-0031.pdf", bouw_pdf(1))
        items = bundel_bijlagen([ubl, pdf])
        assert len(items) == 1 and isinstance(items[0], BijlagePaar)
        assert items[0].reden == REDEN_NAAMSTAM and items[0].pdf is pdf and items[0].pdf_is_losse_bijlage

    def test_hele_vastly_batch_in_een_mail_paart_elk_nummer_met_zijn_eigen_pdf(self) -> None:
        nummers = ["RUB-2026-0031", "RUB-2026-0032", "ARV-2026-0007"]
        ubls = [bijlage(f"factuur-{n}-ubl.xml", bouw_ubl(factuurnummer=n)) for n in nummers]
        pdfs = [bijlage(f"factuur-{n}.pdf", bouw_pdf(1)) for n in nummers]
        items = bundel_bijlagen([*ubls, *pdfs])
        assert len(items) == 3 and all(isinstance(i, BijlagePaar) for i in items)
        for paar in items:
            assert isinstance(paar, BijlagePaar)
            assert genormaliseerde_stam(paar.ubl.bestandsnaam) == genormaliseerde_stam(paar.pdf.bestandsnaam)

    def test_twee_pdf_kandidaten_met_dezelfde_stam_is_twijfel(self) -> None:
        ubl = bijlage("factuur-RUB-2026-0031-ubl.xml", bouw_ubl(factuurnummer="RUB-2026-0031"))
        pdf_a = bijlage("factuur-RUB-2026-0031.pdf", bouw_pdf(1))
        pdf_b = bijlage("factuur-RUB-2026-0031-xml.pdf", bouw_pdf(2))
        items = bundel_bijlagen([ubl, pdf_a, pdf_b])
        assert len(items) == 3 and not any(isinstance(i, BijlagePaar) for i in items)

    def test_oude_exacte_stam_blijft_werken_en_hash_wint(self) -> None:
        pdf = bouw_pdf(1)
        ubl = bijlage("2026-8151.xml", bouw_ubl_met_pdf(pdf))
        los = bijlage("andere-naam.pdf", pdf)
        items = bundel_bijlagen([los, ubl])
        assert isinstance(items[0], BijlagePaar) and items[0].reden == REDEN_INGESLOTEN_HASH
        items = bundel_bijlagen([bijlage("114164.xml", bouw_ubl()), bijlage("114164.PDF", bouw_pdf(1))])
        assert isinstance(items[0], BijlagePaar) and items[0].reden == REDEN_NAAMSTAM


class TestFactuurnummerRegel:
    def test_factuurnummer_uit_de_ubl(self) -> None:
        assert ubl_factuurnummer(bouw_ubl(factuurnummer="RUB-2026-0031")) == "RUB-2026-0031"
        assert ubl_factuurnummer(bouw_ubl(factuurnummer="12")) is None  # te kort/generiek
        assert ubl_factuurnummer(b"<niet>xml") is None

    def test_nummer_in_de_pdf_bestandsnaam(self) -> None:
        ubl = bijlage("vastly-export-1.xml", bouw_ubl(factuurnummer="RUB-2026-0031"))
        pdf = bijlage("Factuur RUB-2026-0031 Rubicon.pdf", bouw_pdf(1))
        items = bundel_bijlagen([ubl, pdf])
        assert len(items) == 1 and isinstance(items[0], BijlagePaar) and items[0].reden == REDEN_FACTUURNUMMER

    def test_nummer_in_de_pdf_tekstlaag(self) -> None:
        ubl = bijlage("vastly-export-1.xml", bouw_ubl(factuurnummer="RUB-2026-0031"))
        pdf = bijlage("scan.pdf", maak_tekst_pdf(["Factuur", "Factuurnummer: RUB-2026- 0031", "Totaal 121,00"]))
        assert pdf_draagt_factuurnummer("scan.pdf", pdf.inhoud, "RUB-2026-0031")
        items = bundel_bijlagen([ubl, pdf])
        assert len(items) == 1 and isinstance(items[0], BijlagePaar) and items[0].reden == REDEN_FACTUURNUMMER

    def test_twee_pdfs_met_het_nummer_is_twijfel(self) -> None:
        ubl = bijlage("vastly-export-1.xml", bouw_ubl(factuurnummer="RUB-2026-0031"))
        pdf_a = bijlage("Factuur RUB-2026-0031.pdf", bouw_pdf(1))
        pdf_b = bijlage("Herinnering RUB-2026-0031.pdf", bouw_pdf(2))
        items = bundel_bijlagen([ubl, pdf_a, pdf_b])
        assert len(items) == 3 and not any(isinstance(i, BijlagePaar) for i in items)

    def test_te_kort_nummer_paart_nooit(self) -> None:
        ubl = bijlage("vastly-export-1.xml", bouw_ubl(factuurnummer="123"))
        pdf = bijlage("Factuur 123.pdf", bouw_pdf(1))
        assert not pdf_draagt_factuurnummer("Factuur 123.pdf", pdf.inhoud, "123")
        items = bundel_bijlagen([ubl, pdf])
        assert len(items) == 2

    def test_geen_match_blijft_los(self) -> None:
        ubl = bijlage("vastly-export-1.xml", bouw_ubl(factuurnummer="RUB-2026-0031"))
        pdf = bijlage("iets-anders.pdf", bouw_pdf(1))
        assert len(bundel_bijlagen([ubl, pdf])) == 2
