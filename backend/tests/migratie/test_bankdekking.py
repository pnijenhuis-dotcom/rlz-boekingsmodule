"""Run 2 VGG 12-09 blok 1: `app/migratie/bankdekking.py` — bank is leidend bij dubbelen (CONTRACT_RUN2 besluit 6).

Puur, geen DB, geen RLZ. Guards: gelijk aantal bankmutaties → bevestigd; minder → niet; bank niet gelezen → niet
bevestigd mét markering; elke mutatie telt één keer; teken en venster tellen; bank-directe reeks uit de data (VGG:
RLZ-25/28/46/60/09) en Receipts per definitie."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.migratie import bankdekking
from app.migratie.bankdekking import (
    BANK_REEKSEN_VGG,
    BankMutatie,
    bankmutaties_uit_rijen,
    dekking_voor,
    is_bank_direct,
    leid_bank_reeksen_af,
    reeks_van,
    teken_van,
)


def _tx(bedrag: float, datum: str, *, id_: str = "t") -> dict:
    return {"id": id_, "Amount": bedrag, "BookDate": f"{datum}T00:00:00", "OpenAmount": 0.0}


def _m(bedrag: str, datum: str, teken: int, *, id_: str = "m") -> BankMutatie:
    return BankMutatie(rlz_id=id_, bedrag=Decimal(bedrag), boekdatum=date.fromisoformat(datum), teken=teken)


D = Decimal


class TestHelpers:
    @pytest.mark.parametrize(
        ("boekstuk", "verwacht"),
        [("RLZ-25-00000312", "RLZ-25"), ("RLZ-09-00001173", "RLZ-09"), ("00112", None), (None, None), ("x", None)],
    )
    def test_reeks_van(self, boekstuk: str | None, verwacht: str | None) -> None:
        assert reeks_van(boekstuk) == verwacht

    def test_bankmutaties_uit_rijen_abs_bedrag_teken_en_sortering(self) -> None:
        uit = bankmutaties_uit_rijen(
            [
                _tx(-415.0, "2025-12-19", id_="b"),
                _tx(135000.0, "2025-11-07", id_="a"),
                {"id": "zonder-bedrag", "BookDate": "2025-11-07T00:00:00"},
                _tx(0.0, "2025-11-07", id_="nul"),
                {"id": "zonder-datum", "Amount": 5.0},
            ]
        )
        assert uit == [
            BankMutatie(rlz_id="a", bedrag=D("135000.00"), boekdatum=date(2025, 11, 7), teken=1),
            BankMutatie(rlz_id="b", bedrag=D("415.00"), boekdatum=date(2025, 12, 19), teken=-1),
        ]

    @pytest.mark.parametrize(
        ("collectie", "bedrag", "verwacht"),
        [
            ("PurchaseInvoices", D("415.00"), -1),
            ("PurchaseInvoices", D("-50.00"), 1),  # creditnota = geld terug
            ("SalesInvoices", D("43666.14"), 1),
            ("SalesInvoices", D("-10.00"), -1),
            ("ManualJournals", D("-20000.00"), -1),
            ("ManualJournals", D("135000.00"), 1),
            ("Receipts", D("-187144.23"), -1),
            ("ManualJournals", D("0.00"), None),
            ("PurchaseInvoices", None, None),
            ("Onbekend", D("1.00"), None),
        ],
    )
    def test_teken_van(self, collectie: str, bedrag: Decimal | None, verwacht: int | None) -> None:
        assert teken_van(collectie, bedrag) == verwacht


class TestIsBankDirect:
    def test_receipts_altijd(self) -> None:
        assert is_bank_direct("Receipts", None, None) is True

    def test_reeks_alleen_uit_de_meegegeven_set_niet_uit_de_vgg_lijst_alleen(self) -> None:
        assert is_bank_direct("PurchaseInvoices", "RLZ-25-00000312", None) is False
        assert is_bank_direct("PurchaseInvoices", "RLZ-25-00000312", None, bank_reeksen={"RLZ-25"}) is True
        assert is_bank_direct("PurchaseInvoices", "RLZ-04-00000846", None, bank_reeksen=BANK_REEKSEN_VGG) is False
        assert sorted(BANK_REEKSEN_VGG) == ["RLZ-09", "RLZ-25", "RLZ-28", "RLZ-46", "RLZ-60"]

    @pytest.mark.parametrize("dagboek", ["Rabobank NL71RABO0360567371", "Bank", "ING zakelijk", "KNAB"])
    def test_bankdagboeknaam(self, dagboek: str) -> None:
        assert is_bank_direct("ManualJournals", "RLZ-06-00000026", dagboek) is True

    def test_memoriaal_dagboek_niet(self) -> None:
        assert is_bank_direct("ManualJournals", "RLZ-06-00000026", "Memoriaal") is False


class TestDekkingVoor:
    BANK = [_m("415.00", "2025-12-19", -1, id_="1"), _m("415.00", "2025-12-19", -1, id_="2")]

    def test_evenveel_bankmutaties_als_boekingen_is_bevestigd(self) -> None:
        d = dekking_voor([(D("415.00"), date(2025, 12, 19), -1), (D("415.00"), date(2025, 12, 19), -1)], self.BANK)
        assert d.bank_bevestigd is True and d.bank_gelezen is True
        assert (d.boekingen, d.bankmutaties) == (2, 2)
        assert d.detail == "2 boekingen, 2 bankmutaties (±3 d)"

    def test_meer_bankmutaties_ook_bevestigd(self) -> None:
        d = dekking_voor([(D("415.00"), date(2025, 12, 19), -1)], self.BANK)
        assert d.bank_bevestigd is True and d.bankmutaties == 1  # elke boeking vindt er één; meer is niet nodig

    def test_minder_bankmutaties_is_niet_bevestigd_met_n_en_k(self) -> None:
        d = dekking_voor([(D("415.00"), date(2025, 12, 19), -1)] * 3, self.BANK)
        assert d.bank_bevestigd is False
        assert d.detail == "3 boekingen, 2 bankmutaties (±3 d)"

    def test_elke_bankmutatie_telt_een_keer(self) -> None:
        d = dekking_voor([(D("415.00"), date(2025, 12, 19), -1)] * 2, self.BANK[:1])
        assert (d.bankmutaties, d.bank_bevestigd) == (1, False)

    def test_teken_moet_gelijk_zijn(self) -> None:
        d = dekking_voor([(D("415.00"), date(2025, 12, 19), 1)], self.BANK)
        assert (d.bankmutaties, d.bank_bevestigd) == (0, False)

    def test_venster_plus_min_drie_dagen_boekdatum(self) -> None:
        bank = [_m("70000.00", "2026-02-23", 1)]
        assert dekking_voor([(D("70000.00"), date(2026, 2, 20), 1)], bank).bank_bevestigd is True
        assert dekking_voor([(D("70000.00"), date(2026, 2, 19), 1)], bank).bank_bevestigd is False
        assert dekking_voor([(D("70000.00"), date(2026, 2, 19), 1)], bank, venster_dagen=4).bank_bevestigd is True

    def test_negatief_bedrag_in_groep_matcht_op_absolute_waarde(self) -> None:
        bank = [_m("20000.00", "2025-09-02", -1)]
        assert dekking_voor([(D("-20000.00"), date(2025, 9, 2), -1)], bank).bank_bevestigd is True

    def test_dichtstbijzijnde_mutatie_eerst(self) -> None:
        bank = [_m("100.00", "2026-01-04", -1, id_="ver"), _m("100.00", "2026-01-01", -1, id_="dichtbij")]
        # Boeking 01-01 pakt 'dichtbij'; boeking 01-05 pakt 'ver' (01-04) — andersom zou 01-05 leeg staan.
        d = dekking_voor([(D("100.00"), date(2026, 1, 5), -1), (D("100.00"), date(2026, 1, 1), -1)], bank)
        assert d.bank_bevestigd is True

    def test_bank_niet_gelezen_nooit_bevestigd_wel_gemarkeerd(self) -> None:
        d = dekking_voor([(D("415.00"), date(2025, 12, 19), -1)] * 2, None)
        assert d.bank_bevestigd is False and d.bank_gelezen is False
        assert d.detail == "bank niet gelezen" and d.bankmutaties == 0

    def test_teken_onbekend_geen_bankfilter(self) -> None:
        d = dekking_voor([(D("0.00"), date(2025, 12, 19), None)], self.BANK)  # type: ignore[list-item]
        assert d.bank_bevestigd is False and d.bank_gelezen is True and "teken onbekend" in d.detail

    def test_lege_groep_is_niet_bevestigd(self) -> None:
        assert dekking_voor([], self.BANK).bank_bevestigd is False


class TestLeidBankReeksenAf:
    def _doc(self, boekstuk: str, bedrag: float, datum: str, *, entity: bool = False, status: int = 2) -> dict:
        return {
            "id": boekstuk,
            "ReceiptNumber": boekstuk,
            "BaseInvoiceAmount": bedrag,
            "Date": f"{datum}T00:00:00",
            "Entity": {"id": "e", "Name": "X"} if entity else None,
            "Status": status,
        }

    def test_vgg_reeksen_uit_gedrag_inkoop_positief_valt_op_afboeking(self) -> None:
        documenten = {
            "PurchaseInvoices": [
                self._doc("RLZ-25-00000312", 415.0, "2025-12-19"),
                self._doc("RLZ-25-00000313", 415.0, "2025-12-19"),
                self._doc("RLZ-25-00000177", 758.74, "2025-10-04"),
                self._doc("RLZ-04-00000846", 20000.0, "2026-08-15"),  # geen bank → geen reeks
                self._doc("RLZ-04-00000847", 20000.0, "2026-08-15"),
                self._doc("RLZ-04-00000737", 20000.0, "2026-07-06"),
                self._doc("RLZ-04-00000868", 349.0, "2026-08-28", entity=True),  # mét Entity telt niet mee
            ],
            "ManualJournals": [
                self._doc("RLZ-46-00000166", 70000.0, "2026-02-20"),
                self._doc("RLZ-46-00000167", 70000.0, "2026-02-20"),
                self._doc("RLZ-46-00000124", 185000.0, "2025-10-23"),
                self._doc("RLZ-06-00000026", -20000.0, "2025-09-02"),
                self._doc("RLZ-06-00000074", -20000.0, "2025-09-02"),
                self._doc("RLZ-06-00000076", -20000.0, "2025-09-02"),
            ],
            "Receipts": [
                self._doc("RLZ-09-00001104", -2500.0, "2026-08-21"),
                self._doc("RLZ-09-00001105", -2500.0, "2026-08-21"),
                self._doc("RLZ-09-00001056", 21388.37, "2026-08-03"),
            ],
        }
        bank = bankmutaties_uit_rijen(
            [
                _tx(-415.0, "2025-12-19", id_="1"),
                _tx(-415.0, "2025-12-19", id_="2"),
                _tx(-758.74, "2025-10-04", id_="3"),
                _tx(70000.0, "2026-02-20", id_="4"),
                _tx(70000.0, "2026-02-20", id_="5"),
                _tx(185000.0, "2025-10-23", id_="6"),
                _tx(-20000.0, "2025-09-02", id_="7"),  # één van de drie RLZ-06 → 1/3 < 0,8
                _tx(-2500.0, "2026-08-21", id_="8"),
                _tx(-2500.0, "2026-08-21", id_="9"),
                _tx(21388.37, "2026-08-03", id_="10"),
            ]
        )
        assert leid_bank_reeksen_af(documenten, bank) == {"RLZ-09": (3, 3), "RLZ-25": (3, 3), "RLZ-46": (3, 3)}

    def test_minimaal_drie_documenten_en_dekking_80_procent(self) -> None:
        documenten = {
            "PurchaseInvoices": [
                self._doc("RLZ-25-00000312", 415.0, "2025-12-19"),
                self._doc("RLZ-25-00000313", 415.0, "2025-12-19"),
            ]
        }
        bank = bankmutaties_uit_rijen([_tx(-415.0, "2025-12-19", id_="1"), _tx(-415.0, "2025-12-19", id_="2")])
        assert leid_bank_reeksen_af(documenten, bank) == {}
        documenten["PurchaseInvoices"].append(self._doc("RLZ-25-00000177", 758.74, "2025-10-04"))
        assert leid_bank_reeksen_af(documenten, bank) == {}  # 2/3 < 0,8
        assert leid_bank_reeksen_af(documenten, bank, min_dekking=bankdekking.Decimal("0.6")) == {"RLZ-25": (3, 2)}

    def test_bank_niet_gelezen_leidt_niets_af(self) -> None:
        documenten = {"PurchaseInvoices": [self._doc("RLZ-25-00000312", 415.0, "2025-12-19")] * 3}
        assert leid_bank_reeksen_af(documenten, None) == {}
