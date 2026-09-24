"""Pure geldlogica van de doorbelasting — geen I/O, geen sessies, 1-op-1 unit-testbaar
(werkwijze: tests verplicht op geldlogica vóór al het andere).

Kernprincipes uit de goedgekeurde mockup (#verdeelmodal) en verkenning/16 §2:
- percentage-verdeling per bron-regel over doelentiteiten, som exact 100% (harde check);
- centen kloppend via de grootste-rest-methode: de som van de delen is altijd exact het
  regelbedrag — er raakt nooit een cent kwijt;
- provisie = provisie-% over het netto doorbelaste bedrag per doelentiteit, ná de verdeling,
  als losse regel (huidig Kempen-patroon, geverifieerd §2a + Rubicon-spiegel §2c);
- btw in de RLZ-VORM (STAP-0 24-09, `verkenning/stap0-doorbelasting-btw-rekenregel-24-09.tsv`, 166/166
  productiedocumenten — 85 doorbelastingsverkopen, 49 spiegels, 32 gewone inkoopfacturen waarvan 15 mét
  twee tarieven, 10 exacte-halve-gevallen, 6 creditregels): RLZ negeert de meegegeven `TaxAmount` per regel
  en rekent zélf — de DOCUMENT-btw per tarief = ROUND_HALF_UP(Σ netto van de regels mét dat tarief × tarief),
  élke regel krijgt ROUND_HALF_UP(netto × tarief) behalve de GROOTSTE regel (|netto|; bij gelijke grootte de
  eerste) van dat tarief, die het verschil draagt zodat Σ regel-btw == document-btw. De motor boekt en
  registreert sinds 24-09 exact zo (`btw_rlz_vorm`), zodat module, RLZ-record, factuur-PDF en webhook
  cent-exact samenvallen. De oude per-regel-afronding (`btw_over`, 17,85 × 21 % → 3,75) blijft bestaan
  voor één losse regel — daar valt de RLZ-vorm ermee samen.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HONDERD = Decimal("100")


def verdeel_grootste_rest(bedrag: Decimal, percentages: list[Decimal]) -> list[Decimal]:
    """Verdeel `bedrag` over `percentages` (som moet 100 zijn) met de grootste-rest-methode:
    elk deel eerst naar beneden op hele centen, de resterende centen één voor één naar de
    grootste afgekapte rest. Garandeert som(delen) == bedrag, ongeacht afronding."""
    if not percentages:
        raise ValueError("verdeel_grootste_rest: lege percentagelijst")
    if sum(percentages) != HONDERD:
        raise ValueError(f"verdeel_grootste_rest: percentages sommen tot {sum(percentages)}, niet 100")
    centen_totaal = int((bedrag / CENT).to_integral_value(rounding="ROUND_HALF_UP"))
    ruw = [(centen_totaal * pct / HONDERD) for pct in percentages]
    vloer = [int(r) for r in ruw]  # afkappen richting nul (bedragen kunnen negatief zijn bij credit)
    rest = centen_totaal - sum(vloer)
    # verdeel de restcenten (positief óf negatief) naar de grootste absolute rest; bij gelijke
    # rest wint de eerste regel (stabiel/deterministisch)
    richting = 1 if rest >= 0 else -1
    resten = sorted(range(len(ruw)), key=lambda i: (-(abs(ruw[i] - vloer[i])), i))
    for i in range(abs(rest)):
        vloer[resten[i % len(vloer)]] += richting
    delen = [Decimal(c) * CENT for c in vloer]
    assert sum(delen) == (Decimal(centen_totaal) * CENT)
    return delen


def btw_over(netto: Decimal, percentage: Decimal) -> Decimal:
    """Btw over één bedrag: netto × percentage/100, afgerond op de cent (ROUND_HALF_UP) — voor één losse
    regel identiek aan wat RLZ vastlegt (STAP-0 §2c 17,85 → 3,75; STAP-0 24-09 half-up op 10 exacte halven).
    Voor een document mét meerdere regels is dit NIET de documentbtw: gebruik `btw_rlz_vorm`."""
    return (netto * percentage / HONDERD).quantize(CENT, rounding=ROUND_HALF_UP)


def btw_rlz_vorm(nettos: Sequence[Decimal], percentage: Decimal) -> tuple[Decimal, list[Decimal]]:
    """Btw van een document in de RLZ-vorm voor regels die ÉÉN tarief delen (de doorbelasting boekt vlak):
    (document-btw, btw per regel). Document-btw = ROUND_HALF_UP(Σ netto × pct); per regel ROUND_HALF_UP(netto ×
    pct), behalve de grootste regel (|netto|, bij gelijk de eerste) die het verschil draagt — exact de bewezen
    RLZ-rekenregel (STAP-0 24-09, 166/166). Garandeert Σ regel-btw == document-btw; één regel = `btw_over`."""
    if not nettos:
        raise ValueError("btw_rlz_vorm: geen regels")
    totaal = btw_over(sum(nettos, Decimal(0)), percentage)
    per_regel = [btw_over(n, percentage) for n in nettos]
    verschil = totaal - sum(per_regel, Decimal(0))
    if verschil != 0:
        grootste = max(range(len(nettos)), key=lambda i: (abs(nettos[i]), -i))
        per_regel[grootste] += verschil
    assert sum(per_regel, Decimal(0)) == totaal
    return totaal, per_regel


def btw_rlz_vorm_per_tarief(regels: Sequence[tuple[Decimal, Decimal]]) -> tuple[Decimal, list[Decimal]]:
    """Algemene vorm: regels als (netto, percentage) mét mogelijk verschillende tarieven — per tarief-groep
    `btw_rlz_vorm`, document-btw = Σ per tarief (STAP-0 24-09: 15 inkoopfacturen 21 + 9 %, 15/15). Voor de
    doorbelasting (één vlak tarief) valt dit samen met `btw_rlz_vorm`."""
    if not regels:
        raise ValueError("btw_rlz_vorm_per_tarief: geen regels")
    per_regel: list[Decimal | None] = [None] * len(regels)
    totaal = Decimal(0)
    for pct in dict.fromkeys(p for _, p in regels):
        idx = [i for i, (_, p) in enumerate(regels) if p == pct]
        groep_totaal, groep = btw_rlz_vorm([regels[i][0] for i in idx], pct)
        totaal += groep_totaal
        for i, b in zip(idx, groep, strict=True):
            per_regel[i] = b
    uit = [b for b in per_regel if b is not None]
    assert len(uit) == len(regels) and sum(uit, Decimal(0)) == totaal
    return totaal, uit


def provisie_over(netto_totaal: Decimal, provisie_percentage: Decimal) -> Decimal:
    """Provisie per doelentiteit: provisie-% over het netto doorbelaste totaal ná de verdeling,
    als losse regel (nooit in de eenheidsprijs verwerkt — huidig patroon is leidend, de
    eenregel-variant van okt/dec 2025 is archief)."""
    return (netto_totaal * provisie_percentage / HONDERD).quantize(CENT, rounding=ROUND_HALF_UP)
