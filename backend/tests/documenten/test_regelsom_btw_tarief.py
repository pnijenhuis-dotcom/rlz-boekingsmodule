"""Btw volgt het tarief (opdracht Peter 18-09, casus Rituals 88-186308) — pure regelsom-functies + de harde check
"Btw-bedrag past bij tarief" (app/documenten/checks.py). Geen DB."""

from __future__ import annotations

import uuid
from decimal import Decimal as D

from app.documenten import regelsom
from app.documenten.checks import (
    ACTIE_BTW_IN_KOSTEN,
    ACTIE_ZET_TARIEF,
    NAAM_BTW_TARIEF,
    CheckRegel,
    TariefInfo,
    check_btw_past_bij_tarief,
    nul_tarief_voor,
)

HOOG = uuid.UUID("55555555-0000-0000-0000-000000000021")
LAAG = uuid.UUID("55555555-0000-0000-0000-000000000009")
NUL = uuid.UUID("55555555-0000-0000-0000-000000000000")
VERLEGD = uuid.UUID("55555555-0000-0000-0000-000000000099")
EU = uuid.UUID("55555555-0000-0000-0000-000000000077")
TARIEVEN = {
    HOOG: TariefInfo(D("0.21"), "NL, Hoog Tarief", favoriet=True),
    LAAG: TariefInfo(D("0.09"), "NL, Laag Tarief"),
    NUL: TariefInfo(D("0"), "NL, Nul"),
    VERLEGD: TariefInfo(D("0.21"), "NL, Verlegd hoog", verlegd=True),
    EU: TariefInfo(D("0.21"), "EU, Producten Hoog tarief", buitenland=True),
}


def _regel(taxrate, netto, btw, ledger=None) -> CheckRegel:
    return CheckRegel(ledger_id=ledger or uuid.uuid4(), taxrate_id=taxrate, netto_bedrag=D(netto), btw_bedrag=D(btw))


class TestRegelsomFuncties:
    def test_btw_uit_tarief_en_bruto(self) -> None:
        assert regelsom.btw_uit_tarief(D("96.36"), D("0.21")) == D("20.24")
        assert regelsom.bruto_uit_netto(D("96.36"), D("0.21")) == D("116.60")

    def test_btw_in_kosten_en_terug_splitsen_is_cent_exact(self) -> None:
        # Rituals: 96,36 + 20,24 → btw in de kosten = 116,60 / 0,00; terug naar 21 % = exact de oorspronkelijke splitsing.
        assert regelsom.zet_btw_in_kosten(D("96.36"), D("20.24")) == (D("116.60"), D("0.00"))
        assert regelsom.splits_bruto(D("116.60"), D("0.21")) == (D("96.36"), D("20.24"))
        assert regelsom.splits_bruto(D("116.60"), D("0")) == (D("116.60"), D("0.00"))

    def test_marge_1_cent_per_samengevoegde_regel_min_1_max_5(self) -> None:
        assert regelsom.marge_voor(0) == D("0.01")
        assert regelsom.marge_voor(1) == D("0.01")
        assert regelsom.marge_voor(3) == D("0.03")
        assert regelsom.marge_voor(6) == D("0.05")

    def test_btw_past_bij_tarief(self) -> None:
        assert regelsom.btw_past_bij_tarief(D("96.36"), D("20.24"), D("0.21"))
        assert regelsom.btw_past_bij_tarief(D("96.36"), D("20.21"), D("0.21"), samengevoegd_n=6)  # marge 5 ct
        assert not regelsom.btw_past_bij_tarief(D("96.36"), D("20.21"), D("0.21"))  # 3 ct op één regel
        assert not regelsom.btw_past_bij_tarief(D("96.36"), D("20.10"), D("0.21"))

    def test_verklarende_percentages(self) -> None:
        assert regelsom.verklarende_percentages(D("96.36"), D("20.24"), [D("0.09"), D("0.21")]) == [D("0.21")]
        assert regelsom.verklarende_percentages(D("96.36"), D("5.00"), [D("0.09"), D("0.21")]) == []


class TestCheckBtwPastBijTarief:
    def test_rituals_0_procent_met_20_24_btw_is_rood_met_twee_acties(self) -> None:
        r = check_btw_past_bij_tarief(regels=[_regel(NUL, "96.36", "20.24")], tarieven=TARIEVEN)
        assert r.naam == NAAM_BTW_TARIEF and r.ok is False
        assert "regel 1: 0 % · NL, Nul met btw € 20.24 op netto € 96.36 — verwacht € 0.00" in r.melding
        codes = [(a.code, a.regel, a.taxrate_id) for a in r.acties]
        assert codes == [(ACTIE_BTW_IN_KOSTEN, 1, NUL), (ACTIE_ZET_TARIEF, 1, HOOG)]
        assert "116.60" in r.acties[0].label and "Zet 21 %" in r.acties[1].label

    def test_btw_in_kosten_toegepast_is_groen(self) -> None:
        r = check_btw_past_bij_tarief(regels=[_regel(NUL, "116.60", "0.00")], tarieven=TARIEVEN)
        assert r.ok and "1 regel" in r.melding

    def test_21_procent_met_20_24_is_groen(self) -> None:
        assert check_btw_past_bij_tarief(regels=[_regel(HOOG, "96.36", "20.24")], tarieven=TARIEVEN).ok

    def test_samengevoegd_6_regels_marge_5_cent(self) -> None:
        regels = [_regel(HOOG, "96.36", "20.21")]
        assert check_btw_past_bij_tarief(regels=regels, tarieven=TARIEVEN, samengevoegd_n=6).ok
        assert not check_btw_past_bij_tarief(regels=regels, tarieven=TARIEVEN, samengevoegd_n=1).ok

    def test_21_procent_met_20_10_is_rood_zonder_zet_actie(self) -> None:
        r = check_btw_past_bij_tarief(regels=[_regel(HOOG, "96.36", "20.10")], tarieven=TARIEVEN)
        assert not r.ok
        # 20,10 past bij géén tarief (21 % = 20,24; 9 % = 8,67) → alleen "btw in kosten".
        assert [a.code for a in r.acties] == [ACTIE_BTW_IN_KOSTEN]
        assert r.acties[0].taxrate_id == NUL  # favoriet-loos: de enige NL-0 %-code

    def test_verlegd_en_buitenland_verwachten_nul(self) -> None:
        assert check_btw_past_bij_tarief(regels=[_regel(VERLEGD, "100.00", "0.00")], tarieven=TARIEVEN).ok
        assert check_btw_past_bij_tarief(regels=[_regel(EU, "100.00", "0.00")], tarieven=TARIEVEN).ok
        assert not check_btw_past_bij_tarief(regels=[_regel(VERLEGD, "100.00", "21.00")], tarieven=TARIEVEN).ok

    def test_zet_actie_kiest_favoriet_en_geen_verlegd_of_eu(self) -> None:
        r = check_btw_past_bij_tarief(regels=[_regel(LAAG, "96.36", "20.24")], tarieven=TARIEVEN)
        zet = [a for a in r.acties if a.code == ACTIE_ZET_TARIEF]
        assert len(zet) == 1 and zet[0].taxrate_id == HOOG  # niet VERLEGD/EU, ook al dragen die 0.21

    def test_onbekend_tarief_is_niet_toetsbaar_maar_niet_rood(self) -> None:
        r = check_btw_past_bij_tarief(regels=[_regel(uuid.uuid4(), "10.00", "2.10")], tarieven=TARIEVEN)
        assert r.ok and "niet toetsbaar" in r.melding

    def test_regel_zonder_btw_of_tarief_telt_niet(self) -> None:
        regels = [CheckRegel(ledger_id=None, taxrate_id=None, netto_bedrag=D("1"), btw_bedrag=D("1"))]
        assert check_btw_past_bij_tarief(regels=regels, tarieven=TARIEVEN).ok

    def test_nul_tarief_voor(self) -> None:
        assert nul_tarief_voor(TARIEVEN, huidig=NUL) == NUL
        assert nul_tarief_voor(TARIEVEN, huidig=HOOG) == NUL
        assert nul_tarief_voor({HOOG: TARIEVEN[HOOG]}) is None
