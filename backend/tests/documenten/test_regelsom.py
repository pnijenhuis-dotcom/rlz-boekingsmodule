"""Gedeelde regelsom-beslisboom (bugfix 04-09, Huvanco-casus) — pure tests op app/documenten/regelsom.py.
De badge (extractie/controle.py) en de harde check (documenten/checks.py) gebruiken beide déze functie;
hier ligt de semantiek per tak vast."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.documenten.regelsom import (
    CENT_TOLERANTIE,
    REDEN_BTW_PER_REGEL_ONTBREEKT,
    REDEN_GEEN_REGELS,
    REDEN_GEEN_TOTAAL,
    REDEN_NETTO_ONTBREEKT,
    corrigeer_btw_centen,
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


class TestCorrigeerBtwCenten:
    """Cent-fix aan de bron (reconciliatie-nazorg 15-09, punt 2): het verschil tussen Σ(netto + btw) en het factuur-
    totaal (1–5 ct) gaat in de LAATSTE btw-dragende regel; alles wat geen afronding is blijft ongemoeid."""

    def _c(self, regels, incl):  # noqa: ANN001
        return corrigeer_btw_centen(
            netto=[_d(n) for n, _ in regels], btw=[_d(b) for _, b in regels], totaal_incl=_d(incl)
        )

    def test_lusso_patroon_twee_regels_een_cent_te_veel(self) -> None:
        # 2 × 15,55 @ 21 %: per regel 3,27 (3,2655), factuur per totaal 31,10 × 21 % = 6,53 → incl 37,63; Σ regels 37,64
        c = self._c([("15.55", "3.27"), ("15.55", "3.27")], "37.63")
        assert c.gecorrigeerd and c.regel == 1 and c.verschil == Decimal("-0.01")
        assert c.btw == (Decimal("3.27"), Decimal("3.26"))

    def test_drie_cent_te_weinig_op_de_laatste_btw_dragende_regel(self) -> None:
        # Verlegd-regel achteraan (btw 0) draagt nooit het verschil.
        c = self._c([("100.00", "21.00"), ("50.00", "10.50"), ("30.00", "0")], "211.53")
        assert c.regel == 1 and c.verschil == Decimal("0.03")
        assert c.btw == (Decimal("21.00"), Decimal("10.53"), Decimal("0"))

    def test_grens_vijf_cent_inclusief_zes_niet(self) -> None:
        assert self._c([("100.00", "21.00")], "121.05").gecorrigeerd
        c = self._c([("100.00", "21.00")], "121.06")
        assert not c.gecorrigeerd and c.verschil == Decimal("0.06") and c.btw == (Decimal("21.00"),)
        assert Decimal("0.05") == CENT_TOLERANTIE

    def test_sluitend_geen_totaal_of_onbekende_bedragen_blijft_ongemoeid(self) -> None:
        assert not self._c([("100.00", "21.00")], "121.00").gecorrigeerd
        assert not self._c([("100.00", "21.00")], None).gecorrigeerd
        assert not self._c([(None, "21.00")], "121.03").gecorrigeerd
        # een regel zonder btw (None = verlegd) telt als 0, blijft None en is nooit de drager
        c = self._c([("100.00", None), ("10.00", "2.10")], "112.13")
        assert c.gecorrigeerd and c.regel == 1 and c.btw == (None, Decimal("2.13"))

    def test_verlegd_factuur_zonder_btw_dragende_regel_niets_te_verschuiven(self) -> None:
        c = self._c([("100.00", "0"), ("23.23", "0")], "123.25")
        assert not c.gecorrigeerd and c.verschil == Decimal("0.02")

    def test_negatieve_creditnota_werkt_in_beide_richtingen(self) -> None:
        c = self._c([("-15.55", "-3.27"), ("-15.55", "-3.27")], "-37.63")
        assert c.regel == 1 and c.btw == (Decimal("-3.27"), Decimal("-3.26"))

    def test_gepaard(self) -> None:
        with pytest.raises(ValueError):
            corrigeer_btw_centen(netto=[Decimal("1")], btw=[], totaal_incl=Decimal("1"))
