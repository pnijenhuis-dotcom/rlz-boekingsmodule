"""FV-01 (feedbackrun A 25-09) — de RLZ-export-UBL deterministisch lezen + leesbare redenen voor alles wat géén UBL is
(`app/documenten/ubl.py`, `app/documenten/ubl_samenvatting.py`). Pure tests (geen DB): BOM, UTF-16, gzip, kapotte XML,
vreemd root-element, UBL zonder regels, `cbc:Note` "Werk: …" → kop-projecttekst, samenvattingskaart leesbaar/niet."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from app.documenten import ubl_samenvatting
from app.documenten.ubl import (
    GeenGeldigeUbl,
    parseer_ubl_factuur,
    project_tekst_uit_note,
    ubl_onvolledig_reden,
)

FIXTURES = Path(__file__).resolve().parents[1] / "keten" / "fixtures"
#: Geanonimiseerde RLZ-export (SI-UBL 1.x, `doc:Invoice`, CustomizationID 1.9, geen ingesloten PDF) — casus a.
RLZ_EXPORT = (FIXTURES / "a_universal_nederland_rlz2080143037" / "factuur.xml").read_bytes()


def _rlz_export_2080142898() -> bytes:
    """De productiecasus (Universal Steigerbouw 250895e8): zelfde export-vorm, ander nummer/bedragen (775,26 + 21 % =
    938,06), geen PII — afgeleid van de geanonimiseerde casus a."""
    return (
        RLZ_EXPORT.replace(b"RLZ-2080143037", b"RLZ-2080142898")
        .replace(b"2026-08-01", b"2026-07-20")
        .replace(b"175.38", b"775.26")
        .replace(b"36.83", b"162.80")
        .replace(b"212.21", b"938.06")
    )


class TestRlzExportVorm:
    def test_rlz_export_leest_kop_partijen_regels_en_identiteit(self) -> None:
        v = parseer_ubl_factuur(_rlz_export_2080142898())
        assert v.factuurnummer == "RLZ-2080142898"
        assert v.factuurdatum == "2026-07-20"
        assert v.leverancier_naam == "Universal Nederland B.V."
        assert v.klant_naam == "Universal Steigerbouw B.V."
        assert v.totaal_excl == "775.26" and v.totaal_incl == "938.06"
        assert v.regelaantal == 1 and v.ubl_regels[0]["btw_percentage"] == "21"
        assert ubl_onvolledig_reden(v) is None

    def test_utf8_bom_en_utf16_lezen_hetzelfde(self) -> None:
        met_bom = b"\xef\xbb\xbf" + RLZ_EXPORT
        assert parseer_ubl_factuur(met_bom).factuurnummer == "RLZ-2080143037"
        utf16 = RLZ_EXPORT.decode("utf-8").replace('encoding="utf-8"', 'encoding="utf-16"').encode("utf-16")
        assert parseer_ubl_factuur(utf16).factuurnummer == "RLZ-2080143037"

    def test_note_werk_wordt_kop_projecttekst(self) -> None:
        v = parseer_ubl_factuur(RLZ_EXPORT)
        assert v.note == "Werk: 26084 - Opdrachtgever A (W03611)"
        assert v.project_tekst == "26084 - Opdrachtgever A (W03611)"
        assert v.als_dict()["project_tekst"] == "26084 - Opdrachtgever A (W03611)"

    @pytest.mark.parametrize(
        ("note", "verwacht"),
        [
            (None, None),
            ("", None),
            ("Bedankt voor uw opdracht", None),
            ("Werk: 26084 - Opdrachtgever A (W03611)", "26084 - Opdrachtgever A (W03611)"),
            ("werk:26140", "26140"),
        ],
    )
    def test_project_tekst_uit_note_is_deterministisch(self, note: str | None, verwacht: str | None) -> None:
        assert project_tekst_uit_note(note) == verwacht


class TestNietLeesbaar:
    def test_gzip_geeft_leesbare_reden(self) -> None:
        with pytest.raises(GeenGeldigeUbl, match="gecomprimeerd bestand \\(gzip\\)"):
            parseer_ubl_factuur(gzip.compress(RLZ_EXPORT))

    def test_leeg_en_pdf_met_xml_naam(self) -> None:
        with pytest.raises(GeenGeldigeUbl, match="leeg bestand"):
            parseer_ubl_factuur(b"   \n")
        with pytest.raises(GeenGeldigeUbl, match="PDF met een .xml-bestandsnaam"):
            parseer_ubl_factuur(b"%PDF-1.4 iets")

    def test_kapotte_xml(self) -> None:
        with pytest.raises(GeenGeldigeUbl, match="Geen geldige XML"):
            parseer_ubl_factuur(RLZ_EXPORT[:2000])

    def test_vreemd_root_element_is_geen_ubl(self) -> None:
        xml = (
            b'<?xml version="1.0"?><Order xmlns="urn:x" '
            b'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
            b"<cbc:ID>1</cbc:ID><cbc:IssueDate>2026-01-01</cbc:IssueDate></Order>"
        )
        with pytest.raises(GeenGeldigeUbl, match="root-element <Order> is geen UBL Invoice of CreditNote"):
            parseer_ubl_factuur(xml)

    def test_invoice_zonder_default_namespace_blijft_ubl(self) -> None:
        """Sommige exporteurs (en de intake-testhelper) laten de default-namespace weg — de lokale rootnaam telt."""
        from tests.intake.conftest import bouw_ubl

        assert parseer_ubl_factuur(bouw_ubl()).factuurnummer == "F-2026-001"

    def test_ubl_zonder_regels_is_onvolledig(self) -> None:
        from tests.intake.conftest import bouw_ubl

        v = parseer_ubl_factuur(bouw_ubl(regels=0))
        assert v.regelaantal == 0
        assert ubl_onvolledig_reden(v) == "UBL onvolledig — ontbreekt: factuurregels (InvoiceLine)"


class TestSamenvattingskaart:
    def test_leesbare_kaart_uit_rlz_export(self) -> None:
        s = ubl_samenvatting.samenvatting_uit_ubl(_rlz_export_2080142898(), bestandsnaam="x.xml")
        assert s.leesbaar and s.reden is None and s.onvolledig is None
        assert s.leverancier == "Universal Nederland B.V." and s.afnemer == "Universal Steigerbouw B.V."
        assert s.totaal_incl == "938.06" and s.totaal_btw == "162.80"
        assert s.kvk_nummer and s.iban
        assert s.regels[0].netto_bedrag == "775.26" and s.regels[0].btw_bedrag == "162.80"
        assert s.project_tekst == "26084 - Opdrachtgever A (W03611)"

    def test_niet_leesbaar_draagt_dezelfde_reden_als_de_parser(self) -> None:
        s = ubl_samenvatting.samenvatting_uit_ubl(gzip.compress(RLZ_EXPORT), bestandsnaam="x.xml")
        assert not s.leesbaar and s.reden and "gecomprimeerd" in s.reden and s.regels == []

    def test_onvolledige_ubl_is_leesbaar_met_onvolledig_reden(self) -> None:
        from tests.intake.conftest import bouw_ubl

        s = ubl_samenvatting.samenvatting_uit_ubl(bouw_ubl(regels=0), bestandsnaam="x.xml")
        assert s.leesbaar and s.onvolledig and "factuurregels" in s.onvolledig
