"""Casus (w) — btw-code uit het FACTUURTOTAAL (bug-onderzoek 15-09, Peter 14/15-09, L.H.G. Holding "Kosten mobiele
telefonie"; KPN-/telecom-patroon: regels excl. btw, één btw-totaal onderaan). Per regel is de btw "onbepaalbaar" en
bleef de code tot 15-09 leeg; nu is het factuurtotaal het tweede bewijs: 69,41 × 21 % = 14,58 → beide regels "NL, Hoog
Tarief" mét herkomst 'factuur' (groen) en een deterministisch berekend regel-btw-bedrag (9,45 + 5,13, cent-exact). De
factuur wint van de administratie-default; de samengevoegde regel draagt dezelfde code; heropenen houdt de stand.

NB de échte LHG-casus was een bank-direct-boeking (zie fixtures/w_telefonie_btw_totaal/bron.json) — het bankformulier is
frontend (HandmatigBoekenBtwDefault.test.tsx) en de historie-verbreding staat in tests/geheugen."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten import boekvoorstel
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import TAXRATE_GEEN_BTW, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.W_TELEFONIE_BTW_TOTAAL)
PDF = CASUS.pdf_bestandsnaam()


@pytest.fixture
def kpn(keten: Keten) -> uuid.UUID:
    # Administratie-default (blok E) staat op "Geen BTW": die mag de factuur-afleiding niet overschrijven.
    with scoped_session(keten.administratie_id) as session:
        session.execute(
            update(Administratie)
            .where(Administratie.id == keten.administratie_id)
            .values(standaard_taxrate_id=TAXRATE_GEEN_BTW)
        )
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    return keten.upload(PDF, pdf).document_id


class TestBtwUitHetFactuurtotaal:
    def test_veldvoorstel_en_prefill_beide_regels_hoog_uit_factuur_groen(self, keten: Keten, kpn: uuid.UUID) -> None:
        veldvoorstel = keten.document(kpn).veldvoorstel
        assert veldvoorstel["btw_factuur_totaal"] == {
            "taxrate_id": str(TAXRATE_HOOG),
            "percentage": "0.2100",
            "reden": None,
            "regels": [1, 2],
            "rest_netto": "69.41",
            "rest_btw": "14.58",
        }
        assert [(r["btw_bedrag"], r["btw_afleiding_basis"], r["btw_bron"]) for r in veldvoorstel["regels"]] == [
            ("9.45", "factuur_totaal", "factuur"),
            ("5.13", "factuur_totaal", "factuur"),
        ]
        assert (
            veldvoorstel["controle"]["regelsom_basis"] == "incl"
            and veldvoorstel["controle"]["regelsom_wijkt_af"] is False
        )

        voorstel = keten.prefill(kpn)
        assert voorstel.vendor_id == keten.vendors["telecom"]
        assert voorstel.totaalbedrag == Decimal("83.99")
        assert [
            (r.netto_bedrag, r.btw_bedrag, r.taxrate_id, r.btw_bron, r.btw_bewust_leeg) for r in voorstel.regels
        ] == [
            (Decimal("45.00"), Decimal("9.45"), TAXRATE_HOOG, "factuur", False),
            (Decimal("24.41"), Decimal("5.13"), TAXRATE_HOOG, "factuur", False),
        ]
        assert all((r.prefill_herkomst or {}).get("btw") == "factuur" for r in voorstel.regels)
        # Eén grootboek voor het hele bedrag: dezelfde code, de gelezen totalen (de keten-administratie heeft
        # projectplicht → de DTO biedt samenvoegen niet aan; de berekening zelf is dezelfde functie).
        samengevoegd = boekvoorstel._samengevoegde_regel(veldvoorstel)
        assert samengevoegd is not None and (samengevoegd.taxrate_id, samengevoegd.btw_bron) == (
            TAXRATE_HOOG,
            "factuur",
        )
        assert (samengevoegd.netto_bedrag, samengevoegd.btw_bedrag) == (Decimal("69.41"), Decimal("14.58"))

    def test_controlescherm_dto_checks_en_heropenen(self, keten: Keten, kpn: uuid.UUID) -> None:
        dto = keten.open_controlescherm(kpn)
        assert [(r["taxrate_id"], r["btw_bron"], r["btw_bedrag"]) for r in dto["regels"]] == [
            (str(TAXRATE_HOOG), "factuur", "9.45"),
            (str(TAXRATE_HOOG), "factuur", "5.13"),
        ]
        checks = keten.checks(kpn)
        assert checks["Regeltelling vs totaal"][0], checks["Regeltelling vs totaal"][1]
        assert checks["Vervaldatum"][0]
        # Heropenen (A10-autosave heeft de prefill gepersisteerd): dezelfde btw, chip-herkomst blijft 'factuur'.
        opnieuw = keten.open_controlescherm(kpn)
        assert [(r["taxrate_id"], r["btw_bron"]) for r in opnieuw["regels"]] == [(str(TAXRATE_HOOG), "factuur")] * 2
        assert any("btw regel 1: factuur" in str(d) or "factuur" in str(d) for d in keten.tijdlijn(kpn))
