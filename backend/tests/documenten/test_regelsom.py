"""Gedeelde regelsom-beslisboom (bugfix 04-09, Huvanco-casus) — pure tests op app/documenten/regelsom.py.
De badge (extractie/controle.py) en de harde check (documenten/checks.py) gebruiken beide déze functie;
hier ligt de semantiek per tak vast."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.documenten.regelsom import (
    REDEN_BTW_PER_REGEL_ONTBREEKT,
    REDEN_GEEN_REGELS,
    REDEN_GEEN_TOTAAL,
    REDEN_NETTO_ONTBREEKT,
    toets_regelsom,
)


def _d(waarde: str | None) -> Decimal | None:
    return Decimal(waarde) if waarde is not None else None


def _toets(regels: list[tuple[str | None, str | None]], *, incl=None, excl=None, btw=None):
    return toets_regelsom(
        netto=[_d(n) for n, _ in regels],
        btw=[_d(b) for _, b in regels],
        totaal_incl=_d(incl),
        totaal_excl=_d(excl),
        factuur_btw=_d(btw),
    )


class TestBeslisboom:
    def test_1_btw_per_regel_compleet_toetst_netto_plus_btw_tegen_incl(self) -> None:
        t = _toets([("100.00", "21.00"), ("50.00", "10.50")], incl="181.50", excl="150.00")
        assert t.basis == "incl" and t.regelsom == Decimal("181.50") and t.wijkt_af is False
        assert t.netto_som == Decimal("150.00") and t.btw_bijgeteld == Decimal("31.50")

    def test_2_zonder_btw_per_regel_toetst_netto_tegen_excl(self) -> None:
        # De Huvanco-vorm: regels zonder btw, kortingsregel negatief, excl gelezen → netto-vs-netto.
        t = _toets([("400.00", None), ("164.40", None), ("-56.44", None)], incl="614.63", excl="507.96")
        assert t.basis == "excl" and t.regelsom == Decimal("507.96") and t.wijkt_af is False

    def test_3_zonder_excl_maar_met_factuur_btw_toetst_tegen_incl(self) -> None:
        t = _toets([("400.00", None), ("164.40", None), ("-56.44", None)], incl="614.63", btw="106.67")
        assert t.basis == "incl" and t.regelsom == Decimal("614.63") and t.wijkt_af is False
        assert t.btw_bijgeteld == Decimal("106.67")

    def test_4_alleen_incl_en_geen_btw_per_regel_is_expliciet_niet_toetsbaar(self) -> None:
        # Nooit stil Σnetto (excl) tegen incl — dát gaf de valse € 117,95.
        t = _toets([("400.00", None), ("164.40", "34.52"), ("-56.44", None)], incl="614.63")
        assert not t.toetsbaar and t.reden == REDEN_BTW_PER_REGEL_ONTBREEKT
        assert t.regels_zonder_btw == (1, 3)
        assert t.netto_som == Decimal("507.96")
        assert t.regelsom is None and t.wijkt_af is None

    def test_echte_afwijking_blijft_zichtbaar_op_elke_basis(self) -> None:
        assert _toets([("100.00", "21.00")], incl="200.00").wijkt_af is True
        assert _toets([("100.00", None)], excl="150.00").wijkt_af is True
        assert _toets([("100.00", None)], incl="150.00", btw="21.00").wijkt_af is True

    def test_tolerantie_van_een_cent(self) -> None:
        assert _toets([("100.00", "21.00")], incl="121.01").wijkt_af is False
        assert _toets([("100.00", "21.00")], incl="121.02").wijkt_af is True

    def test_geen_regels(self) -> None:
        t = _toets([], incl="121.00")
        assert t.reden == REDEN_GEEN_REGELS and not t.toetsbaar

    def test_onparseerbare_netto_is_nooit_een_som(self) -> None:
        t = _toets([("100.00", "21.00"), (None, None)], incl="121.00", excl="100.00")
        assert t.reden == REDEN_NETTO_ONTBREEKT and t.regelsom is None

    def test_geen_enkel_totaal(self) -> None:
        t = _toets([("100.00", None)])
        assert t.reden == REDEN_GEEN_TOTAAL and t.netto_som == Decimal("100.00")

    def test_negatieve_regel_met_negatieve_btw_telt_gewoon_mee(self) -> None:
        # Korting mét btw-vermelding: −56,44 / −11,85 → Σ(netto+btw) = 121,00 + (−68,29) = 52,71.
        t = _toets([("100.00", "21.00"), ("-56.44", "-11.85")], incl="52.71")
        assert t.basis == "incl" and t.regelsom == Decimal("52.71") and t.wijkt_af is False

    def test_volledige_creditnota_negatief_totaal(self) -> None:
        t = _toets([("-100.00", "-21.00")], incl="-121.00")
        assert t.wijkt_af is False

    def test_ongepaarde_lijsten_zijn_een_programmeerfout(self) -> None:
        with pytest.raises(ValueError):
            toets_regelsom(netto=[Decimal(1)], btw=[], totaal_incl=None, totaal_excl=None, factuur_btw=None)
