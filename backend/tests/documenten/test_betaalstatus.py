"""Betaalstatus inkoopfactuur (blok 3 bundel 08-09 avond, B3) — de pure motor (app/documenten/betaalstatus.py), de harde
check "Betaalstatus (declaraties)", en de RLZ-port die de status als `QuickPaymentSelection` zet tussen PUT en actie 17
(STAP-0 08-09: kale her-PUT, post blijft open, keuze op label uit de per-document-lijst)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.backends.port import BackendBoekFout
from app.backends.rlz_inkoop import RlzInkoopPort
from app.documenten import betaalstatus as bs
from app.documenten.boekvoorstel import BoekvoorstelData, BoekvoorstelRegelData
from app.documenten.checks import check_betaalstatus_declaraties
from tests.documenten.fake_rlz_client import FakeBoekClient


class TestCanoniekEnLabels:
    def test_acht_rlz_waarden_letterlijk(self) -> None:
        assert bs.BETAALSTATUSSEN == (
            "Nog te betalen",
            "Wordt automatisch geïncasseerd",
            "Betaald per bank",
            "Betaald met PIN",
            "Betaald met Creditcard",
            "Betaald - contant",
            "Verrekend met prive",
            "Verrekend met Rekening Courant",
        )

    @pytest.mark.parametrize(
        ("invoer", "verwacht"),
        [
            ("Betaald per bank", "Betaald per bank"),
            ("betaald PER BANK", "Betaald per bank"),
            ("Betaald – contant", "Betaald - contant"),  # mens-typografie (en-dash) → RLZ-spelling
            ("Verrekend met privé", "Verrekend met prive"),
            ("Wordt automatisch geincasseerd", "Wordt automatisch geïncasseerd"),
            ("Nog te betalen", "Nog te betalen"),
            ("Betaald met giro", None),
            ("", None),
            (None, None),
        ],
    )
    def test_canoniek_normaliseert_accenten_streepjes_en_hoofdletters(self, invoer, verwacht) -> None:
        assert bs.canoniek(invoer) == verwacht
        assert bs.is_geldig(invoer) is (verwacht is not None)

    def test_kies_keuze_id_matcht_op_label_uit_rlz_lijst(self) -> None:
        keuzes = FakeBoekClient.QUICK_PAYMENT_SELECTIONS
        assert bs.kies_keuze_id(keuzes, "Wordt automatisch geïncasseerd") == "1a7732dc-053c-4ea1-87b9-2e0cb863ea19"
        assert bs.kies_keuze_id(keuzes, "Betaald per bank") == "6b541fa5-d3ca-4aac-ac8d-9af47bc8aa44"
        assert bs.kies_keuze_id(keuzes, "Verrekend met privé") == "4e13b2db-3522-454f-aa22-1135bd64b0df"
        assert bs.kies_keuze_id([{"id": "x", "Description": "Iets anders"}], "Betaald per bank") is None
        assert bs.kies_keuze_id([], "Betaald per bank") is None


class TestIncassoDetectie:
    FACTUURDATUM = date(2026, 9, 8)

    @pytest.mark.parametrize(
        ("tekst", "datum"),
        [
            ("Het factuurbedrag wordt automatisch geïncasseerd op 25-09-2026 van uw rekening.", date(2026, 9, 25)),
            ("Wij schrijven het bedrag rond 25 september af van rekening NL00KETN0000000001.", date(2026, 9, 25)),
            ("Betaling via automatische incasso, incassodatum 2026-10-01", date(2026, 10, 1)),
            ("SEPA-incasso: het bedrag wordt binnen 14 dagen afgeschreven.", date(2026, 9, 22)),
            ("Dit bedrag wordt per incasso rond de 27e van de maand afgeschreven.", date(2026, 9, 27)),
            ("Wordt automatisch geincasseerd.", None),  # incasso zonder datum → status wél, datum leeg
            (
                "Bedrag wordt geïncasseerd rond 5 januari",
                date(2027, 1, 5),
            ),  # zonder jaar en vóór het anker → volgend jaar
        ],
    )
    def test_incasso_zinnen_worden_herkend_met_datum(self, tekst: str, datum: date | None) -> None:
        d = bs.detecteer_incasso(tekst, factuurdatum=self.FACTUURDATUM)
        assert d is not None
        assert d.betaalstatus == bs.AUTOMATISCH_GEINCASSEERD
        assert d.verwachte_betaaldatum == datum
        assert d.bron_tekst  # de zin reist mee (chip-tooltip)

    @pytest.mark.parametrize(
        "tekst",
        [
            "Gelieve het bedrag binnen 14 dagen over te maken op NL00KETN0000000001 o.v.v. het factuurnummer.",
            "Betaling per SEPA-overboeking. Wij verzoeken u vriendelijk tijdig te betalen.",
            "U kunt de machtiging voor onze nieuwsbrief intrekken via de website.",
            "Er wordt geen automatische incasso uitgevoerd; maak het bedrag zelf over.",
            "",
        ],
    )
    def test_gewone_betaalverzoeken_en_negaties_zijn_geen_incasso(self, tekst: str) -> None:
        assert bs.detecteer_incasso(tekst, factuurdatum=self.FACTUURDATUM) is None

    def test_meerdere_bronnen_ai_veld_wint_en_datumtekst_vult_aan(self) -> None:
        d = bs.detecteer_incasso(
            "Het bedrag wordt automatisch geïncasseerd.",
            "Factuur 2026-001 — huur september",
            factuurdatum=self.FACTUURDATUM,
            incasso_datum_tekst="30-09-2026",
        )
        assert d is not None and d.verwachte_betaaldatum == date(2026, 9, 30)

    def test_datum_op_de_volgende_regel_wordt_gevonden(self) -> None:
        tekst = "Betaalwijze: automatische incasso\nIncassodatum: 25-09-2026\nKenmerk: ABC"
        d = bs.detecteer_incasso(tekst, factuurdatum=self.FACTUURDATUM)
        assert d is not None and d.verwachte_betaaldatum == date(2026, 9, 25)

    def test_ubl_payment_means_code(self) -> None:
        assert bs.is_ubl_incasso("59") and bs.is_ubl_incasso(" 49 ")
        assert not bs.is_ubl_incasso("30") and not bs.is_ubl_incasso(None) and not bs.is_ubl_incasso("")


class TestHardeCheck:
    def test_declaratie_zonder_status_blokkeert(self) -> None:
        r = check_betaalstatus_declaraties(kanaal="declaraties", betaalstatus=None)
        assert r.naam == "Betaalstatus (declaraties)" and not r.ok and "Declaratie zonder betaalstatus" in r.melding

    def test_declaratie_op_nog_te_betalen_blokkeert(self) -> None:
        assert not check_betaalstatus_declaraties(kanaal="declaraties", betaalstatus="Nog te betalen").ok

    def test_declaratie_met_onbekend_label_blokkeert(self) -> None:
        assert not check_betaalstatus_declaraties(kanaal="declaraties", betaalstatus="Betaald met giro").ok

    def test_declaratie_met_status_groen(self) -> None:
        r = check_betaalstatus_declaraties(kanaal="declaraties", betaalstatus="Betaald per bank")
        assert r.ok and "Betaald per bank" in r.melding

    def test_facturen_kanaal_en_upload_niet_van_toepassing(self) -> None:
        assert check_betaalstatus_declaraties(kanaal="facturen", betaalstatus=None).ok
        assert check_betaalstatus_declaraties(kanaal=None, betaalstatus=None).ok
        r = check_betaalstatus_declaraties(kanaal=None, betaalstatus="Wordt automatisch geïncasseerd")
        assert r.ok and "gaat mee" in r.melding


def _voorstel(document_id: uuid.UUID, **extra) -> BoekvoorstelData:
    return BoekvoorstelData(
        document_id=document_id,
        vendor_id=uuid.uuid4(),
        referentie="DECL-001",
        factuurdatum=date(2026, 9, 8),
        totaalbedrag=Decimal("121.00"),
        rlz_boekstuknummer=None,
        opgeslagen=True,
        regels=[
            BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(),
                taxrate_id=uuid.uuid4(),
                project_id=None,
                netto_bedrag=Decimal("100.00"),
                btw_bedrag=Decimal("21.00"),
                omschrijving="Declaratie",
            )
        ],
        regels_samenvoegen=False,
        **extra,
    )


class TestRlzPortZetBetaalstatus:
    def test_zet_quickpaymentselection_tussen_put_en_boeken(self) -> None:
        client = FakeBoekClient()
        document_id = uuid.uuid4()
        voorstel = _voorstel(document_id, betaalstatus="Betaald per bank", betaalstatus_herkomst="kanaal")
        uitkomst = RlzInkoopPort(client).boek_inkoopfactuur(
            document_id=document_id, voorstel=voorstel, bestand=b"%PDF", bestandsnaam="declaratie.pdf"
        )
        assert len(client.puts) == 1  # de document-PUT zelf
        assert client.betaalstatus_gezet == [
            {"id": str(uitkomst.extern_document_id), "selection_id": "6b541fa5-d3ca-4aac-ac8d-9af47bc8aa44"}
        ]
        assert client.geboekte_acties == [uitkomst.extern_document_id]
        assert uitkomst.detail["betaalstatus"] == "Betaald per bank"
        assert uitkomst.detail["betaalstatus_herkomst"] == "kanaal"
        # Readback: de keuze staat op het (geboekte) document — zoals RLZ 'm via $expand teruggeeft.
        assert client.get(f"PurchaseInvoices/{uitkomst.extern_document_id}")["QuickPaymentSelection"] == {
            "id": "6b541fa5-d3ca-4aac-ac8d-9af47bc8aa44"
        }

    def test_zonder_betaalstatus_of_nog_te_betalen_geen_extra_put(self) -> None:
        for status in (None, "Nog te betalen"):
            client = FakeBoekClient()
            document_id = uuid.uuid4()
            uitkomst = RlzInkoopPort(client).boek_inkoopfactuur(
                document_id=document_id,
                voorstel=_voorstel(document_id, betaalstatus=status),
                bestand=b"%PDF",
                bestandsnaam="f.pdf",
            )
            assert not hasattr(client, "betaalstatus_gezet")
            assert "betaalstatus" not in uitkomst.detail
            assert client.geboekte_acties == [uitkomst.extern_document_id]

    def test_label_niet_in_rlz_lijst_is_zichtbare_boekfout_en_boekt_niet(self) -> None:
        client = FakeBoekClient()
        client.quick_payment_selections = [{"id": "x", "Description": "Nog te betalen"}]
        document_id = uuid.uuid4()
        with pytest.raises(BackendBoekFout, match="staat niet in de keuzelijst"):
            RlzInkoopPort(client).boek_inkoopfactuur(
                document_id=document_id,
                voorstel=_voorstel(document_id, betaalstatus="Betaald per bank"),
                bestand=b"%PDF",
                bestandsnaam="f.pdf",
            )
        assert client.geboekte_acties == []  # nooit stil boeken zonder de status

    def test_put_van_de_status_faalt_is_boekfout(self) -> None:
        client = FakeBoekClient(faal_op="quick_payment_selection_put")
        document_id = uuid.uuid4()
        with pytest.raises(BackendBoekFout):
            RlzInkoopPort(client).boek_inkoopfactuur(
                document_id=document_id,
                voorstel=_voorstel(document_id, betaalstatus="Wordt automatisch geïncasseerd"),
                bestand=b"%PDF",
                bestandsnaam="f.pdf",
            )
        assert client.geboekte_acties == []
