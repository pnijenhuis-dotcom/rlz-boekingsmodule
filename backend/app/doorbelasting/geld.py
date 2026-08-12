"""Pure geldlogica van de doorbelasting — geen I/O, geen sessies, 1-op-1 unit-testbaar
(werkwijze: tests verplicht op geldlogica vóór al het andere).

Kernprincipes uit de goedgekeurde mockup (#verdeelmodal) en verkenning/16 §2:
- percentage-verdeling per bron-regel over doelentiteiten, som exact 100% (harde check);
- centen kloppend via de grootste-rest-methode: de som van de delen is altijd exact het
  regelbedrag — er raakt nooit een cent kwijt;
- provisie = provisie-% over het netto doorbelaste bedrag per doelentiteit, ná de verdeling,
  als losse regel (huidig Kempen-patroon, geverifieerd §2a + Rubicon-spiegel §2c);
- btw per regel = vlak tarief over het regelnetto (huidige praktijk 21%, onafhankelijk van
  het onderliggende inkooptarief — §2), afgerond per regel (ROUND_HALF_UP, zoals RLZ zelf
  optelt: geverifieerd 17,85 × 21% → 3,75).
"""

from __future__ import annotations

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
    """Btw per regel: netto × percentage/100, per regel afgerond (ROUND_HALF_UP) — zoals RLZ
    de regelbedragen zelf optelt (STAP-0: 17,85 → 3,75)."""
    return (netto * percentage / HONDERD).quantize(CENT, rounding=ROUND_HALF_UP)


def provisie_over(netto_totaal: Decimal, provisie_percentage: Decimal) -> Decimal:
    """Provisie per doelentiteit: provisie-% over het netto doorbelaste totaal ná de verdeling,
    als losse regel (nooit in de eenheidsprijs verwerkt — huidig patroon is leidend, de
    eenregel-variant van okt/dec 2025 is archief)."""
    return (netto_totaal * provisie_percentage / HONDERD).quantize(CENT, rounding=ROUND_HALF_UP)
