"""Casus (a) — Universal Nederland RLZ-2080143037 (RLZ-export-UBL, geen ingesloten PDF) komt twee keer binnen: mail
"deel 8" droeg de PDF, de UBL én een tweede exemplaar van diezelfde UBL ("… (2).xml"; in productie kregen beide
bijlagen hetzelfde document-id — idempotent binnen één bericht), en de UBL werd later nog eens los herzonden.
Productie: doc 249eb716 (PDF+UBL, geboekt 08-09 RLZ-25-00003231) + huls 37615790 (samengevoegd). Doelgedrag blok 4:
het echte document draagt de chip "1 exemplaar samengevoegd", het dubbele exemplaar staat niet in de standaardlijst."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.documenten import boeken, boekvoorstel
from app.documenten.models import DocumentStatus
from app.intake import nabundelen
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_HUUR_MATERIEEL, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.A_UNIVERSAL_NEDERLAND)
XML, PDF = CASUS.xml_bestandsnaam(), CASUS.pdf_bestandsnaam()
XML_2 = XML.replace(".xml", " (2).xml")


@pytest.fixture
def deel_8(keten: Keten):
    """Mail 'deel 8': PDF + UBL + dubbel UBL-exemplaar (byte-identiek)."""
    ubl = CASUS.xml()
    return keten.mail([(PDF, CASUS.pdf()), (XML, ubl), (XML_2, ubl)], onderwerp="Facturen universal steigerbouw deel 8")


@pytest.fixture
def herzonden(keten: Keten, deel_8):
    """Dezelfde UBL nog eens, in een tweede mail (herzonden)."""
    return keten.mail([(XML, CASUS.xml())], onderwerp="Herzonden: RLZ-2080143037")


def _echt(deel_8):
    return {r.bestandsnaam: r for r in deel_8.bijlagen}[XML].document_id


def _echt_en_dubbel(deel_8, herzonden) -> tuple:
    return _echt(deel_8), herzonden.bijlagen[0].document_id


class TestIntake:
    def test_pdf_bundelt_op_naamstam_dubbel_exemplaar_in_dezelfde_mail_is_hetzelfde_document(self, keten: Keten, deel_8) -> None:
        per_naam = {r.bestandsnaam: r for r in deel_8.bijlagen}
        assert per_naam[XML].uitkomst == "toegewezen"
        assert per_naam[PDF].uitkomst == "gebundeld" and per_naam[PDF].document_id == per_naam[XML].document_id
        assert "naamstam" in (per_naam[PDF].detail or "")
        # Byte-identieke bijlage in hetzélfde bericht: idempotent — geen tweede werkstuk, wél zichtbaar verantwoord.
        assert per_naam[XML_2].uitkomst == "toegewezen"
        assert per_naam[XML_2].document_id == per_naam[XML].document_id
        assert keten.ai.aanroepen == [], "UBL's gaan nooit naar de AI; de PDF is beeld"
        assert keten.standaardlijst_ids() == {str(per_naam[XML].document_id)}

    def test_echte_document_in_standaardlijst_herzonden_exemplaar_niet(self, keten: Keten, deel_8, herzonden) -> None:
        echt, dubbel = _echt_en_dubbel(deel_8, herzonden)
        assert dubbel != echt
        ids = keten.standaardlijst_ids()
        assert str(echt) in ids
        assert str(dubbel) not in ids, "het byte-identieke tweede exemplaar is geen werk"
        assert keten.status(dubbel) in (DocumentStatus.SAMENGEVOEGD, DocumentStatus.AFGEVOERD_DUPLICAAT)
        assert keten.rij(dubbel)["toegewezen_aan"] is None  # casus j: geen eigenaar → geen toewijzing, wél doorgelopen
        # Terugvindbaar via de toggle, mét verwijzing naar het echte document.
        rij = keten.lijst_rij(dubbel, toon_afgehandeld="true")
        assert rij is not None
        verwijzing = rij.get("samengevoegd_in") or rij.get("duplicaat_van")
        assert verwijzing is not None and verwijzing["document_id"] == str(echt)

    def test_echte_document_draagt_chip_exemplaren_samengevoegd(self, keten: Keten, deel_8, herzonden) -> None:
        """Blok 4 (08-09): een byte-identiek exemplaar uit een TWEEDE mail is een duplicaat (categorie a, DUPLICATEN
        HOOFDMODEL 07-09) → `afgevoerd_duplicaat` mét kruisverwijzing naar het echte document; `samengevoegd` (huls)
        blijft het pad voor dubbelen uit DEZELFDE mail (B2). Beide zijn afgehandeld-gedrag (NAZORG 08-09) en tellen op
        het echte document als exemplaar — de chip "1 exemplaar samengevoegd/afgevoerd"."""
        echt, dubbel = _echt_en_dubbel(deel_8, herzonden)
        assert keten.status(dubbel) in (DocumentStatus.SAMENGEVOEGD, DocumentStatus.AFGEVOERD_DUPLICAAT)
        rij = keten.lijst_rij(dubbel, toon_afgehandeld="true")
        verwijzing = rij.get("samengevoegd_in") or rij.get("duplicaat_van")
        assert verwijzing is not None and verwijzing["document_id"] == str(echt)
        assert keten.lijst_rij(echt)["samengevoegde_exemplaren"] == 1

    def test_nabundel_motor_is_idempotent_op_deze_stand(self, keten: Keten, deel_8, herzonden) -> None:
        telling = nabundelen.nabundel_verzamelbak(
            ook_toegewezen=True, opslag=keten.opslag, administratie_id=keten.administratie_id
        )
        assert telling.mislukt == 0
        echt = _echt(deel_8)
        assert keten.status(echt) == DocumentStatus.TE_CONTROLEREN


class TestPrefill:
    def test_prefill_uit_de_ubl(self, keten: Keten, deel_8) -> None:
        echt = _echt(deel_8)
        voorstel = keten.prefill(echt)
        assert voorstel.vendor_id == keten.vendors["universal_nederland"]
        assert voorstel.referentie == "RLZ-2080143037"
        assert voorstel.factuurdatum == date(2026, 8, 1)
        assert voorstel.totaalbedrag == Decimal("212.21")
        assert [(r.netto_bedrag, r.btw_bedrag) for r in voorstel.regels] == [(Decimal("175.38"), Decimal("36.83"))]
        keten.open_controlescherm(echt)
        checks = keten.checks(echt)
        assert checks["Duplicaatcheck"][0] and "Kan niet controleren" not in checks["Duplicaatcheck"][1]
        assert checks["Regeltelling vs totaal"][0]

    def test_ubl_kop_en_regel_rechtstreeks_uit_de_xml(self, keten: Keten, deel_8) -> None:
        echt = _echt(deel_8)
        veldvoorstel = keten.document(echt).veldvoorstel
        assert veldvoorstel["iban"] == "NL20KETN1000000002"
        assert veldvoorstel["kvk_nummer"] == "91000001"
        assert veldvoorstel["btw_nummer"] == "NL100007922B01"
        voorstel = keten.prefill(echt)
        assert voorstel.regels[0].omschrijving == "Huurperiode juli 2026, conform huuroverzicht"
        assert voorstel.regels[0].taxrate_id == TAXRATE_HOOG


class TestBoekenEnLijst:
    def _boek(self, keten: Keten, document_id) -> None:
        voorstel = keten.prefill(document_id)
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=keten.administratie_id,
            document_id=document_id,
            actor_id=keten.actor,
            vendor_id=voorstel.vendor_id,
            referentie=voorstel.referentie,
            factuurdatum=voorstel.factuurdatum,
            totaalbedrag=voorstel.totaalbedrag,
            regels=[
                boekvoorstel.BoekvoorstelRegelData(
                    ledger_id=GB_HUUR_MATERIEEL,
                    taxrate_id=TAXRATE_HOOG,
                    project_id=PROJECT_26084,
                    netto_bedrag=Decimal("175.38"),
                    btw_bedrag=Decimal("36.83"),
                    omschrijving="huur juli",
                )
            ],
        )
        boeken.boek_document(administratie_id=keten.administratie_id, document_id=document_id, actor_id=keten.actor)

    def test_boeken_geeft_boekstuk_en_lijst_toont_geboekt_in_rlz(self, keten: Keten, deel_8) -> None:
        echt = _echt(deel_8)
        self._boek(keten, echt)
        assert keten.status(echt) == DocumentStatus.GEBOEKT
        assert len(keten.rlz.puts) == 1 and keten.rlz.puts[0]["reference"] == "RLZ-2080143037"
        rij = keten.lijst_rij(echt, toon_afgehandeld="true")
        assert rij is not None and rij["status"] == "geboekt"
        assert rij["geboekt_in_rlz"] is not None and rij["geboekt_in_rlz"]["boekstuknummer"]

    # Blok 11 (08-09) staat: `geboekt` is afgehandeld — niet in de standaardlijst, wél achter de toggle mét teller.
    def test_geboekt_document_valt_onder_toon_afgehandeld(self, keten: Keten, deel_8) -> None:
        echt = _echt(deel_8)
        self._boek(keten, echt)
        assert str(echt) not in keten.standaardlijst_ids()
        lijst = keten.lijst(toon_afgehandeld="true")
        assert str(echt) in {d["id"] for d in lijst["documenten"]}
        assert lijst["afgehandeld"].get("geboekt") == 1

    def test_exporteer_frontend_fixture(self, keten: Keten, deel_8) -> None:
        echt = _echt(deel_8)
        keten.exporteer("a_universal_nederland", echt)
