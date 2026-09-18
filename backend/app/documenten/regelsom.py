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


# ---- cent-fix aan de bron (reconciliatie-nazorg 15-09) --------------------------------------------

#: Grens waarbinnen een verschil tussen Σ(netto + btw) van de regels en het factuurtotaal een btw-cent-afronding is
#: (RLZ rekent btw per regel, de factuur per totaal — Kempen Facilities: Lusso/Booking Experts 2–3 ct). Zelfde grens
#: als de automatische acceptatie in de reconciliatie (`app/documenten/reconciliatie.py::AFRONDING_TOLERANTIE`).
CENT_TOLERANTIE = Decimal("0.05")


@dataclass(frozen=True)
class CentCorrectie:
    """Uitkomst van `corrigeer_btw_centen`: `btw` = de btw per regel zoals die naar het pakket gaat; `regel` = de
    (0-gebaseerde) regel die het centverschil droeg, `verschil` = totaal − Σ regels vóór correctie (getekend). None/0
    = niets gecorrigeerd."""

    btw: tuple[Decimal | None, ...]
    regel: int | None
    verschil: Decimal

    @property
    def gecorrigeerd(self) -> bool:
        return self.regel is not None


def corrigeer_btw_centen(
    *,
    netto: list[Decimal | None],
    btw: list[Decimal | None],
    totaal_incl: Decimal | None,
    tolerantie: Decimal = CENT_TOLERANTIE,
) -> CentCorrectie:
    """Cent-fix aan de bron (nazorg 15-09, punt 2): als Σ(netto + btw) van de regels 1–5 cent afwijkt van het
    factuurtotaal, gaat het verschil in de LAATSTE btw-dragende regel (btw ≠ 0), zodat het documenttotaal in het pakket
    cent-exact gelijk is aan de factuur. Een regel zonder btw (verlegd/vrijgesteld, None) telt als 0 mee in de som,
    blijft None en draagt nooit het verschil. Bewust NIET bij: geen totaal, een regel zonder netto, een verschil >
    tolerantie
    (echte afwijking — blokkeert al in de checks) of geen enkele btw-dragende regel (verlegd-factuur: niets te
    verschuiven). Pure functie op Decimals; de aanroeper (RLZ-adapter) verandert de regels in de module níét — alleen
    wat naar het pakket gaat."""
    if len(netto) != len(btw):
        raise ValueError("netto en btw moeten per regel gepaard zijn (zelfde lengte)")
    ongewijzigd = CentCorrectie(btw=tuple(btw), regel=None, verschil=Decimal("0"))
    if totaal_incl is None or not netto or any(n is None for n in netto):
        return ongewijzigd
    # Een regel zonder btw (None = verlegd/vrijgesteld) telt als 0 in de som, blijft None en is nooit de drager.
    som = sum((n + (b or Decimal(0)) for n, b in zip(netto, btw, strict=True) if n is not None), Decimal(0))
    verschil = (totaal_incl - som).quantize(Decimal("0.01"))
    if verschil == 0 or abs(verschil) > tolerantie:
        return CentCorrectie(btw=tuple(btw), regel=None, verschil=verschil)
    dragers = [i for i, b in enumerate(btw) if b is not None and b != 0]
    if not dragers:
        return CentCorrectie(btw=tuple(btw), regel=None, verschil=verschil)
    laatste = dragers[-1]
    nieuw = list(btw)
    nieuw[laatste] = (btw[laatste] or Decimal(0)) + verschil  # type: ignore[operator]
    return CentCorrectie(btw=tuple(nieuw), regel=laatste, verschil=verschil)


# ---- btw volgt het tarief (opdracht Peter 18-09, casus Rituals 88-186308) -----------------------------------------
#
# "Nul % btw invullen is auto btw-bedrag op nul zetten" (Peter 18-09): het btw-bedrag van een regel volgt ALTIJD het
# gekozen tarief. 0 %/geen btw op een regel die uit de factuur wél btw draagt = btw in de kosten (niet aftrekbaar —
# representatie, relatiegeschenken, BUA): netto := netto + factuur-btw, btw := 0,00; terug naar 21 % splitst het bruto
# weer. Eén bron voor backend (check "Btw-bedrag past bij tarief", prefill BUA-stap) én frontend (regelsom.ts spiegelt
# deze functies één-op-één). Pure Decimal-functies, cent-exact, ROUND_HALF_UP — geen DB, geen LLM.

from decimal import ROUND_HALF_UP  # noqa: E402  (bewust ná de moduledocstring-sectie hierboven)

CENT = Decimal("0.01")
#: Marge voor "btw past bij tarief": 1 cent per samengevoegde factuurregel (RLZ rekent btw per regel, de factuur per
#: totaal), minimaal 1 en maximaal 5 cent (regel 3, opdracht 18-09).
MARGE_MIN_REGELS = 1
MARGE_MAX_REGELS = 5


def _cent(bedrag: Decimal) -> Decimal:
    return bedrag.quantize(CENT, rounding=ROUND_HALF_UP)


def btw_uit_tarief(netto: Decimal, percentage: Decimal) -> Decimal:
    """netto × percentage (fractie: 0.21), afgerond op de cent (ROUND_HALF_UP)."""
    return _cent(netto * percentage)


def marge_voor(samengevoegd_n: int) -> Decimal:
    """De toegestane afwijking tussen tarief × netto en het btw-bedrag: 1 cent × het aantal samengevoegde factuur-
    regels (min 1, max 5)."""
    n = max(MARGE_MIN_REGELS, min(int(samengevoegd_n or 1), MARGE_MAX_REGELS))
    return CENT * n


def btw_past_bij_tarief(netto: Decimal, btw: Decimal, percentage: Decimal, *, samengevoegd_n: int = 1) -> bool:
    """|btw − netto × percentage| ≤ marge(samengevoegd_n)."""
    return abs(btw - btw_uit_tarief(netto, percentage)) <= marge_voor(samengevoegd_n)


def zet_btw_in_kosten(netto: Decimal, btw: Decimal) -> tuple[Decimal, Decimal]:
    """0 %/geen btw op een regel mét factuur-btw: de niet-aftrekbare btw gaat in de kosten → (netto + btw, 0,00)."""
    return _cent(netto + btw), Decimal("0.00")


def splits_bruto(bruto: Decimal, percentage: Decimal) -> tuple[Decimal, Decimal]:
    """Bruto terug in (netto, btw) bij een tarief: netto = bruto / (1 + p) op de cent, btw = de rest — zo sluit
    netto + btw altijd cent-exact op het bruto (21 → 0 → 21 geeft de oorspronkelijke splitsing terug)."""
    if percentage == 0:
        return _cent(bruto), Decimal("0.00")
    netto = _cent(bruto / (1 + percentage))
    return netto, _cent(bruto - netto)


def bruto_uit_netto(netto: Decimal, percentage: Decimal) -> Decimal:
    return _cent(netto + btw_uit_tarief(netto, percentage))


def verklarende_percentages(
    netto: Decimal, btw: Decimal, kandidaten: list[Decimal], *, samengevoegd_n: int = 1
) -> list[Decimal]:
    """Welke van de kandidaat-percentages verklaren het btw-bedrag binnen de marge? Voor de actie "Zet N %":
    precies één treffer = deterministisch, anders geen actie (meerdere/geen kandidaten → alleen 'btw in kosten')."""
    gezien: list[Decimal] = []
    for p in kandidaten:
        if p is None or p in gezien:
            continue
        if btw_past_bij_tarief(netto, btw, p, samengevoegd_n=samengevoegd_n):
            gezien.append(p)
    return gezien
