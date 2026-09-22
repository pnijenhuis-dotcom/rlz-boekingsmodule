"""Casus (ak) — niet-btw-plichtige administratie (BUG Peter 22-09, casus Vastgoedgroep Nederland / Studio Lacy Lion
2026-042 → RLZ-04-00000925: module splitste 1.535,13 + 322,38, RLZ boekte alleen het netto → € 322,38 te weinig betaald).
Hergebruikt het Rituals-document (ae: 96,36 + 21 % 20,24 = 116,60) in een administratie mét `btw_plichtig = false`:
(1) de prefill zet de regel bruto 116,60 / btw 0,00 mét "NL, Geen BTW (Vrijgesteld)" en chip, de DTO draagt
`btw_plichtig=false` + de geen-btw-code, de checks zijn groen (tarief-check n.v.t., regeltelling sluit) en de
RLZ-regels dragen TaxAmount 0; (2) splitst de mens tóch (21 %, 96,36/20,24), dan is de harde check "Btw in
niet-btw-plichtige administratie" ROOD mét de ene actie "Btw in de kosten zetten (alle regels)"; de actie toegepast →
groen."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.backends.rlz_inkoop import regels_naar_rlz_lines
from app.beheer import btw_plichtig
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.checks import ACTIE_BTW_IN_KOSTEN_ALLES, NAAM_BTW_NIET_PLICHTIG, NAAM_BTW_TARIEF
from app.sync.models import VendorCache
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import TAXRATE_GEEN_BTW, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.AE_RITUALS_BUA)
PDF = CASUS.pdf_bestandsnaam()
VENDOR = uuid.UUID("33333333-0000-0000-0000-000000000099")
GB_4510 = uuid.UUID("44444444-0000-0000-0000-000000004510")


@pytest.fixture
def niet_plichtig(keten: Keten) -> uuid.UUID:
    with scoped_session(keten.administratie_id) as session:
        session.add(
            VendorCache(
                id=VENDOR,
                administratie_id=keten.administratie_id,
                naam="Rituals Nieuwegein",
                brondata={"Name": "Rituals Nieuwegein"},
            )
        )
        session.add(
            Grootboekrekening(
                ledger_id=GB_4510,
                administratie_id=keten.administratie_id,
                code="4510",
                naam="Representatiekosten",
                soort=2,
                is_totaalrekening=False,
            )
        )
    btw_plichtig.zet(actor_id=SYSTEEM_ACTOR_ID, administratie_id=keten.administratie_id, btw_plichtig=False)
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    return keten.upload(PDF, pdf).document_id


def _put(keten: Keten, document_id: uuid.UUID, dto: dict, regel: dict) -> dict:
    body = {
        "vendor_id": dto["vendor_id"],
        "referentie": dto["referentie"],
        "factuurdatum": dto["factuurdatum"],
        "totaalbedrag": dto["totaalbedrag"],
        "regels": [regel],
        "regels_samenvoegen": False,
    }
    resp = keten.api.put(
        f"/administraties/{keten.administratie_id}/documenten/{document_id}/boekvoorstel",
        json=body,
        headers=keten.headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _check(rapport: dict, naam: str) -> dict:
    return next(r for r in rapport["resultaten"] if r["naam"] == naam)


class TestNietBtwPlichtig:
    def test_prefill_bruto_met_geen_btw_code_dto_en_checks_groen(self, keten: Keten, niet_plichtig: uuid.UUID) -> None:
        voorstel = keten.prefill(niet_plichtig)
        regel = voorstel.regels[0]
        assert regel.taxrate_id == TAXRATE_GEEN_BTW and regel.btw_in_kosten is True
        assert (regel.netto_bedrag, regel.btw_bedrag) == (Decimal("116.60"), Decimal("0.00"))
        assert (
            regel.btw_bron == btw_plichtig.BTW_BRON_NIET_PLICHTIG and regel.btw_bron_detail == btw_plichtig.CHIP_TEKST
        )
        lines = regels_naar_rlz_lines(voorstel)
        assert lines[0]["TaxAmount"] == 0.0 and lines[0]["NetAmount"] == 116.6
        assert lines[0]["TaxRate"] == {"id": str(TAXRATE_GEEN_BTW)}
        dto = keten.open_controlescherm(niet_plichtig)
        assert dto["btw_plichtig"] is False and dto["geen_btw_taxrate_id"] == str(TAXRATE_GEEN_BTW)
        r0 = dto["regels"][0]
        assert (r0["taxrate_id"], r0["btw_bron"], r0["btw_in_kosten"]) == (
            str(TAXRATE_GEEN_BTW),
            btw_plichtig.BTW_BRON_NIET_PLICHTIG,
            True,
        )
        checks = keten.checks(niet_plichtig)
        assert checks[NAAM_BTW_NIET_PLICHTIG][0], checks[NAAM_BTW_NIET_PLICHTIG][1]
        assert checks[NAAM_BTW_TARIEF][0] and "niet btw-plichtig" in checks[NAAM_BTW_TARIEF][1]
        assert checks["Regeltelling vs totaal"][0], checks["Regeltelling vs totaal"][1]

    def test_mens_splitst_toch_rood_met_actie_alle_regels_en_actie_maakt_groen(
        self, keten: Keten, niet_plichtig: uuid.UUID
    ) -> None:
        dto = keten.open_controlescherm(niet_plichtig)
        regel = dict(dto["regels"][0])
        regel.update({"taxrate_id": str(TAXRATE_HOOG), "netto_bedrag": "96.36", "btw_bedrag": "20.24"})
        uit = _put(keten, niet_plichtig, dto, regel)
        check = _check(uit["checks"], NAAM_BTW_NIET_PLICHTIG)
        assert check["ok"] is False and uit["checks"]["geblokkeerd"] is True
        assert "regel 1: btw € 20.24, tarief 21 % · NL, Hoog Tarief" in check["melding"]
        assert [(a["code"], a["regel"], a["taxrate_id"]) for a in check["acties"]] == [
            (ACTIE_BTW_IN_KOSTEN_ALLES, 0, str(TAXRATE_GEEN_BTW))
        ]
        assert _check(uit["checks"], NAAM_BTW_TARIEF)["ok"] is True  # n.v.t., niet dubbel rood
        regel.update({"taxrate_id": str(TAXRATE_GEEN_BTW), "netto_bedrag": "116.60", "btw_bedrag": "0.00"})
        uit = _put(keten, niet_plichtig, uit["boekvoorstel"], regel)
        assert _check(uit["checks"], NAAM_BTW_NIET_PLICHTIG)["ok"] is True
        assert _check(uit["checks"], "Regeltelling vs totaal")["ok"] is True
