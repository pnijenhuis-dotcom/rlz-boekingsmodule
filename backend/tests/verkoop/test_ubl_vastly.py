"""UBL-parsing van de §2d-golden-cases: regels + AccountingCost (BT-133/BT-19), en de
CreditNote-381-herkenning (eigen root, CreditNoteLine, BillingReference)."""

from __future__ import annotations

from app.documenten.ubl import is_vastly_verkoop, nlcius_kernvelden_ontbrekend, parseer_ubl_factuur
from tests.verkoop.conftest import bouw_vastly_creditnote_ubl, bouw_vastly_verkoop_ubl


class TestInvoiceRegels:
    def test_regels_met_accountingcost_en_btw(self) -> None:
        voorstel = parseer_ubl_factuur(
            bouw_vastly_verkoop_ubl(
                regels=[
                    {"naam": "Huur", "netto": "1000.00", "pct": "21.00", "categorie": "S", "gb_code": "8000"},
                    {"naam": "Servicekosten", "netto": "150.00", "pct": "21.00", "categorie": "S", "gb_code": "8010"},
                ]
            )
        )
        assert voorstel.is_creditnota is False
        assert is_vastly_verkoop(voorstel)
        assert voorstel.regelaantal == 2
        assert voorstel.ubl_regels[0]["netto_bedrag"] == "1000.00"
        assert voorstel.ubl_regels[0]["btw_percentage"] == "21.00"
        assert voorstel.ubl_regels[0]["gb_code"] == "8000"
        assert voorstel.ubl_regels[1]["gb_code"] == "8010"
        assert voorstel.totaal_btw == "241.50"

    def test_document_gb_code_bt19_is_fallback_per_regel(self) -> None:
        voorstel = parseer_ubl_factuur(
            bouw_vastly_verkoop_ubl(
                document_gb_code="8000",
                regels=[
                    {"naam": "Huur", "netto": "1000.00", "pct": "21.00", "categorie": "S", "gb_code": None},
                    {"naam": "Borg", "netto": "100.00", "pct": "0.00", "categorie": "E", "gb_code": "8020"},
                ],
            )
        )
        assert voorstel.ubl_regels[0]["gb_code"] == "8000"  # BT-19-fallback
        assert voorstel.ubl_regels[1]["gb_code"] == "8020"  # regelwaarde wint

    def test_regel_zonder_code_blijft_leeg(self) -> None:
        voorstel = parseer_ubl_factuur(
            bouw_vastly_verkoop_ubl(
                regels=[{"naam": "Huur", "netto": "1000.00", "pct": "21.00", "categorie": "S", "gb_code": None}]
            )
        )
        assert voorstel.ubl_regels[0]["gb_code"] is None


class TestCreditNote381:
    def test_creditnote_herkend_met_billingreference(self) -> None:
        voorstel = parseer_ubl_factuur(bouw_vastly_creditnote_ubl())
        assert voorstel.is_creditnota is True
        assert is_vastly_verkoop(voorstel)
        assert voorstel.gecrediteerde_factuurnummers == ("VF-2026-0042",)
        assert voorstel.regelaantal == 1  # CreditNoteLine, niet InvoiceLine
        assert voorstel.ubl_regels[0]["netto_bedrag"] == "1000.00"
        assert nlcius_kernvelden_ontbrekend(voorstel) == []

    def test_creditnote_zonder_billingreference_is_kernveld_incompleet(self) -> None:
        voorstel = parseer_ubl_factuur(bouw_vastly_creditnote_ubl(gecrediteerd_factuurnummer=None))
        assert voorstel.is_creditnota is True
        ontbrekend = nlcius_kernvelden_ontbrekend(voorstel)
        assert any("BillingReference" in v for v in ontbrekend)

    def test_gewone_invoice_is_geen_creditnota(self) -> None:
        voorstel = parseer_ubl_factuur(bouw_vastly_verkoop_ubl())
        assert voorstel.is_creditnota is False
        assert voorstel.gecrediteerde_factuurnummers == ()
