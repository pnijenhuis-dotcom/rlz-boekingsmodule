"""Regelsom-beslisboom — ÉÉN bron voor de veldvoorstel-badge (app/extractie/controle.py, C3 26-08)
én de harde check "Regeltelling vs totaal" (app/documenten/checks.py).

Bugfix 04-09 (Huvanco-casus): de check vergeleek Σ(netto + btw) met het INCLUSIEF gelezen
factuurtotaal, terwijl de btw per regel ontbrak (AI las alleen netto's) — de som was dus feitelijk
exclusief en de check riep vals "wijkt € 117,95 af". De badge in het veldvoorstel had die situatie
sinds C3 al goed (netto-vs-netto), de check niet: twee beslisbomen die uit de pas liepen. Sinds
04-09 gebruiken beide plekken deze ene pure functie.

Beslisboom (in deze volgorde, exact de C3-lijn):
  1. btw per regel bij ÁLLE regels bekend én incl-totaal bekend  → Σ(netto + btw)  vs incl
  2. excl-totaal bekend                                          → Σnetto          vs excl
  3. factuur-btw-bedrag bekend én incl-totaal bekend             → Σnetto + btw    vs incl
  4. anders: NIET toetsbaar — nooit stil excl-vs-incl vergelijken; de reden benoemt wat ontbreekt.

Pure functie op Decimals (Code voor cijfers): geen DB, geen AI, geen ORM."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ROND_TOLERANTIE = Decimal("0.01")

# Redenen waarom er níét getoetst kon worden (leesbaar in tests/tijdlijn/meldingen).
REDEN_GEEN_REGELS = "geen_regels"
REDEN_NETTO_ONTBREEKT = "netto_ontbreekt"
REDEN_BTW_PER_REGEL_ONTBREEKT = "btw_per_regel_ontbreekt"
REDEN_GEEN_TOTAAL = "geen_totaal"


@dataclass(frozen=True)
class RegelsomToets:
    """Uitkomst van `toets_regelsom`. `basis` = "incl" of "excl" (welke totalen vergeleken zijn);
    None = niet toetsbaar, dan draagt `reden` waarom. `regelsom` is het opgetelde bedrag op die
    basis, `vergelijk` het totaal waartegen, `verschil` = |regelsom − vergelijk|."""

    basis: str | None
    regelsom: Decimal | None
    vergelijk: Decimal | None
    verschil: Decimal | None
    wijkt_af: bool | None
    reden: str | None
    # Hulpvelden voor leesbare meldingen: de netto-som en de bijgetelde btw (regel-btw óf factuur-btw).
    netto_som: Decimal | None = None
    btw_bijgeteld: Decimal | None = None
    # 1-gebaseerde regelnummers waarop de btw ontbreekt (alleen gevuld bij reden btw_per_regel_ontbreekt).
    regels_zonder_btw: tuple[int, ...] = ()

    @property
    def toetsbaar(self) -> bool:
        return self.basis is not None


def toets_regelsom(
    *,
    netto: list[Decimal | None],
    btw: list[Decimal | None],
    totaal_incl: Decimal | None,
    totaal_excl: Decimal | None,
    factuur_btw: Decimal | None,
    tolerantie: Decimal = ROND_TOLERANTIE,
) -> RegelsomToets:
    """Zie de moduledocstring voor de beslisboom. `netto`/`btw` zijn per regel (zelfde lengte);
    None = niet bekend/niet geparst. Negatieve regels (korting, rabat, creditregel) tellen gewoon
    mee — een korting van −56,44 verlaagt de som, precies zoals op de factuur."""
    if len(netto) != len(btw):
        raise ValueError("netto en btw moeten per regel gepaard zijn (zelfde lengte)")
    if not netto:
        return RegelsomToets(None, None, None, None, None, REDEN_GEEN_REGELS)
    if any(n is None for n in netto):
        return RegelsomToets(None, None, None, None, None, REDEN_NETTO_ONTBREEKT)

    netto_som = sum((n for n in netto if n is not None), Decimal(0))
    zonder_btw = tuple(i for i, b in enumerate(btw, start=1) if b is None)
    btw_compleet = not zonder_btw

    if btw_compleet and totaal_incl is not None:
        btw_som = sum((b for b in btw if b is not None), Decimal(0))
        return _uitkomst("incl", netto_som + btw_som, totaal_incl, tolerantie, netto_som, btw_som)
    if totaal_excl is not None:
        return _uitkomst("excl", netto_som, totaal_excl, tolerantie, netto_som, None)
    if factuur_btw is not None and totaal_incl is not None:
        return _uitkomst("incl", netto_som + factuur_btw, totaal_incl, tolerantie, netto_som, factuur_btw)
    if totaal_incl is not None:
        # Alleen een incl-totaal en geen btw per regel: Σnetto tegen incl zou een valse afwijking
        # geven (de Huvanco-bug) — expliciet niet toetsbaar, mét de regels die btw missen.
        return RegelsomToets(
            None,
            None,
            None,
            None,
            None,
            REDEN_BTW_PER_REGEL_ONTBREEKT,
            netto_som=netto_som,
            regels_zonder_btw=zonder_btw,
        )
    return RegelsomToets(None, None, None, None, None, REDEN_GEEN_TOTAAL, netto_som=netto_som)


def _uitkomst(
    basis: str,
    regelsom: Decimal,
    vergelijk: Decimal,
    tolerantie: Decimal,
    netto_som: Decimal,
    btw_bijgeteld: Decimal | None,
) -> RegelsomToets:
    verschil = abs(regelsom - vergelijk)
    return RegelsomToets(
        basis=basis,
        regelsom=regelsom,
        vergelijk=vergelijk,
        verschil=verschil,
        wijkt_af=verschil > tolerantie,
        reden=None,
        netto_som=netto_som,
        btw_bijgeteld=btw_bijgeteld,
    )
