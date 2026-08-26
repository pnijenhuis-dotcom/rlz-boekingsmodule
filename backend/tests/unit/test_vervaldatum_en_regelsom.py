"""C1 + C3 (gecombineerde run 26-08): deterministische vervaldatum-checks en de regelsom-badge
met exact dezelfde netto+btw=incl-logica als de boekingsregels-toets (casus AddGuests)."""

from __future__ import annotations

from datetime import date

import pytest

from app.documenten.checks import check_vervaldatum, vervaldatum_signaal
from app.extractie.controle import bouw_veldvoorstel
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld


class TestVervaldatumChecks:
    def test_leeg_is_toegestaan(self) -> None:
        r = check_vervaldatum(factuurdatum=date(2026, 8, 1), vervaldatum=None)
        assert r.ok and "RLZ leidt" in r.melding
        assert vervaldatum_signaal(factuurdatum=date(2026, 8, 1), vervaldatum=None) is None

    def test_voor_factuurdatum_blokkeert(self) -> None:
        r = check_vervaldatum(factuurdatum=date(2026, 8, 10), vervaldatum=date(2026, 8, 1))
        assert not r.ok and "vóór de factuurdatum" in r.melding
        assert vervaldatum_signaal(factuurdatum=date(2026, 8, 10), vervaldatum=date(2026, 8, 1)) is None

    def test_normale_termijn_groen_zonder_signaal(self) -> None:
        r = check_vervaldatum(factuurdatum=date(2026, 8, 1), vervaldatum=date(2026, 8, 31))
        assert r.ok and "30 dagen" in r.melding
        assert vervaldatum_signaal(factuurdatum=date(2026, 8, 1), vervaldatum=date(2026, 8, 31)) is None

    @pytest.mark.parametrize("dagen", [90, 91, 400])
    def test_grens_negentig_dagen(self, dagen: int) -> None:
        f = date(2026, 1, 1)
        v = date.fromordinal(f.toordinal() + dagen)
        assert check_vervaldatum(factuurdatum=f, vervaldatum=v).ok  # nooit blokkerend
        signaal = vervaldatum_signaal(factuurdatum=f, vervaldatum=v)
        assert (signaal is not None) == (dagen > 90)
        if signaal:
            assert f"{dagen} dagen" in signaal


def _extractie(regels: list[tuple[str, str | None]], *, totaal_excl: str | None, totaal_incl: str | None, btw: str | None):
    def veld(w: str | None) -> AiVeld:
        return AiVeld(waarde=w, zekerheid=0.95 if w is not None else 0.0)

    kop = {
        "leverancier_naam": veld("AddGuests"),
        "factuurnummer": veld("AG-1"),
        "factuurdatum": veld("2026-08-20"),
        "vervaldatum": veld(None),
        "valuta": veld("EUR"),
        "totaal_excl": veld(totaal_excl),
        "totaal_incl": veld(totaal_incl),
        "btw_bedrag": veld(btw),
    }
    return AiFactuurExtractie(
        kop=kop,
        regels=[
            AiRegel(omschrijving=f"regel {i}", netto_bedrag=n, btw_bedrag=b, hoeveelheid=None, zekerheid=0.9)
            for i, (n, b) in enumerate(regels)
        ],
        bsn_verwijderd=0,
        volledig=True,
    )


class TestRegelsomBadge:
    def _controle(self, extractie):
        return bouw_veldvoorstel(extractie, vendors=[], taxrates=[], zekerheid_drempel=0.7)["controle"]

    def test_addguests_netto_plus_btw_sluit_aan_op_incl(self) -> None:
        c = self._controle(_extractie([("1328.14", "278.91")], totaal_excl="1328.14", totaal_incl="1607.05", btw="278.91"))
        assert c["regelsom"] == "1607.05" and c["regelsom_basis"] == "incl" and c["regelsom_wijkt_af"] is False

    def test_regels_zonder_btw_worden_tegen_excl_getoetst(self) -> None:
        # de oude bug: Σnetto (1.328,14) tegen incl (1.607,05) → vals "wijkt af"
        c = self._controle(_extractie([("1000.00", None), ("328.14", None)], totaal_excl="1328.14", totaal_incl="1607.05", btw="278.91"))
        assert c["regelsom"] == "1328.14" and c["regelsom_basis"] == "excl" and c["regelsom_wijkt_af"] is False

    def test_regels_zonder_btw_en_zonder_excl_gebruikt_factuur_btw(self) -> None:
        c = self._controle(_extractie([("1328.14", None)], totaal_excl=None, totaal_incl="1607.05", btw="278.91"))
        assert c["regelsom"] == "1607.05" and c["regelsom_basis"] == "incl" and c["regelsom_wijkt_af"] is False

    def test_echt_verschil_blijft_zichtbaar(self) -> None:
        c = self._controle(_extractie([("1300.00", "273.00")], totaal_excl="1328.14", totaal_incl="1607.05", btw="278.91"))
        assert c["regelsom"] == "1573.00" and c["regelsom_wijkt_af"] is True

    def test_niets_te_toetsen_geeft_geen_badge(self) -> None:
        c = self._controle(_extractie([("1328.14", None)], totaal_excl=None, totaal_incl=None, btw=None))
        assert c["regelsom"] is None and c["regelsom_basis"] is None and c["regelsom_wijkt_af"] is None
