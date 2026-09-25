"""Casus (a2) — FV-01 feedbackrun A 25-09: de RLZ-export-UBL komt ZONDER haar PDF binnen (productie 02-09: Universal
Nederland RLZ-2080142898 → Universal Steigerbouw, doc 250895e8 — de PDF ging naar een splitsingsvoorstel, de UBL naar de
verzamelbak en werd handmatig toegewezen; geen bron-PDF, geen ingesloten PDF). Tot 25-09 toonde het bijlage-paneel dan
de ruwe XML. Doelgedrag: het document is gewoon te_controleren mét het deterministische UBL-voorstel, de bijlage-route
serveert de XML (het hoofdbestand), en de samenvattingsroute levert de leesbare kaart; een kapotte XML uit dezelfde
export-bron is handmatig_afmaken mét de reden — in tijdlijn én kaart hetzelfde."""

from __future__ import annotations

import uuid

import pytest

from app.documenten.models import DocumentStatus
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import Keten

CASUS = Casus(casussen.A_UNIVERSAL_NEDERLAND)
XML = CASUS.xml_bestandsnaam().replace("2080143037", "2080142898")


def _export_2080142898() -> bytes:
    """Zelfde RLZ-export-vorm als casus a, het productienummer en de productiebedragen (775,26 + 21 % = 938,06)."""
    return (
        CASUS.xml()
        .replace(b"RLZ-2080143037", b"RLZ-2080142898")
        .replace(b"2026-08-01", b"2026-07-20")
        .replace(b"175.38", b"775.26")
        .replace(b"36.83", b"162.80")
        .replace(b"212.21", b"938.06")
    )


@pytest.fixture
def ubl_alleen(keten: Keten):
    """Mail mét alleen de UBL — de PDF-tweeling is er (nog) niet."""
    return keten.mail([(XML, _export_2080142898())], onderwerp="Facturen universal steigerbouw deel 8")


def _samenvatting(keten: Keten, document_id: uuid.UUID) -> dict:
    resp = keten.api.get(
        f"/administraties/{keten.administratie_id}/documenten/{document_id}/ubl-samenvatting", headers=keten.headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestUblZonderBeeld:
    def test_toegewezen_te_controleren_zonder_ai_en_zonder_beeld(self, keten: Keten, ubl_alleen) -> None:
        rij = ubl_alleen.bijlagen[0]
        assert rij.uitkomst == "toegewezen"
        assert keten.status(rij.document_id) == DocumentStatus.TE_CONTROLEREN
        assert keten.ai.aanroepen == []
        lijst_rij = keten.rij(rij.document_id)
        assert lijst_rij["bron_bestandsnaam"] is None, "geen PDF-beeld"
        detail = keten.detail(rij.document_id)
        assert detail["veldvoorstel"]["factuurnummer"] == "RLZ-2080142898"
        assert detail["veldvoorstel"]["project_tekst"] == "26084 - Opdrachtgever A (W03611)"

    def test_bijlage_route_serveert_de_xml_zelf(self, keten: Keten, ubl_alleen) -> None:
        document_id = ubl_alleen.bijlagen[0].document_id
        resp = keten.api.get(
            f"/administraties/{keten.administratie_id}/documenten/{document_id}/bestand", headers=keten.headers
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        assert b"RLZ-2080142898" in resp.content

    def test_samenvattingskaart_is_leesbaar_en_volledig(self, keten: Keten, ubl_alleen) -> None:
        document_id = ubl_alleen.bijlagen[0].document_id
        kaart = _samenvatting(keten, document_id)
        assert kaart["leesbaar"] is True and kaart["onvolledig"] is None
        assert kaart["leverancier"] == "Universal Nederland B.V." and kaart["afnemer"] == "Universal Steigerbouw B.V."
        assert kaart["factuurnummer"] == "RLZ-2080142898" and kaart["factuurdatum"] == "2026-07-20"
        assert kaart["totaal_excl"] == "775.26" and kaart["totaal_btw"] == "162.80" and kaart["totaal_incl"] == "938.06"
        assert kaart["regelaantal"] == 1 and kaart["regels"][0]["btw_percentage"] == "21"
        assert kaart["kvk_nummer"] and kaart["iban"]

    def test_prefill_en_checks_zoals_een_gebundelde_ubl(self, keten: Keten, ubl_alleen) -> None:
        document_id = ubl_alleen.bijlagen[0].document_id
        voorstel = keten.prefill(document_id)
        assert voorstel.vendor_id == keten.vendors["universal_nederland"]
        assert str(voorstel.totaalbedrag) == "938.06"
        keten.open_controlescherm(document_id)
        checks = keten.checks(document_id)
        assert checks["Regeltelling vs totaal"][0]
        assert checks["Duplicaatcheck"][0]

    def test_exporteer_frontend_fixture(self, keten: Keten, ubl_alleen) -> None:
        """Harnas-casus a_ubl_zonder_beeld: het bijlage-paneel krijgt de XML (geen PDF) + de kaart uit de route."""
        document_id = ubl_alleen.bijlagen[0].document_id
        keten.exporteer(
            "a_ubl_zonder_beeld",
            document_id,
            extra={
                "bijlage_xml": _export_2080142898().decode("utf-8"),
                "ubl_samenvatting": _samenvatting(keten, document_id),
            },
        )


class TestKapotteXml:
    def test_kapotte_export_is_handmatig_afmaken_met_dezelfde_reden_in_tijdlijn_en_kaart(self, keten: Keten) -> None:
        kapot = _export_2080142898()[:2000]
        uitkomst = keten.mail([(XML, kapot)], onderwerp="Facturen universal steigerbouw deel 9")
        rij = uitkomst.bijlagen[0]
        # Bij de intake is een onleesbare UBL geen inkoopdocument: verzamelbak mét reden (§2d-failsafe, ongewijzigd).
        assert rij.uitkomst == "verzamelbak" and "ubl_invalide" in (rij.detail or "")
        # Handmatig toegewezen (zoals Barbara op 02-09) → de extractie in de administratie zet 'm op handmatig_afmaken.
        upload = keten.upload(XML, kapot)
        assert keten.status(upload.document_id) == DocumentStatus.HANDMATIG_AFMAKEN
        redenen = [d.get("ubl_parse_fout") for d in keten.tijdlijn(upload.document_id)]
        reden = next(r for r in redenen if r)
        assert reden.startswith("Geen geldige XML")
        kaart = _samenvatting(keten, upload.document_id)
        assert kaart["leesbaar"] is False and kaart["reden"] == reden
        rij_lijst = keten.rij(upload.document_id)
        assert rij_lijst["status"] == "handmatig_afmaken"
