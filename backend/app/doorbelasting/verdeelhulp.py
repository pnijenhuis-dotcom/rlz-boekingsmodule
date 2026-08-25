"""Verdeelhulp — herbruikbare, pure verdeelmotor (besluit Peter 25-08, deel 2 punt 2b/2d).

Verdeelt een centenbedrag over doelen naar GEWICHT (m² of gelijk) met de grootste-rest-methode:
de som van de delen is altijd exact het bedrag, er raakt nooit een cent kwijt. Dit is de
gewichts-generalisatie van `geld.verdeel_grootste_rest` (die werkt op percentages die exact op
100 sommen). Eerste afnemer: de multi-project-verdeling binnen een doelentiteit van de
Kempen-doorbelasting (`service.sla_verdeling_op`). Bewust los van doorbelasting-modellen en
zonder I/O, zodat dezelfde bouwsteen straks de gewone regel-splitsing zonder doorbelasting kan
dragen (parkeerpost 2d — de UI daarvoor is een latere stap).

Regels:
- twee verdeelbases, of/of: 'm2' (gewicht = contract-/pand-m² per doel; ontbrekend of 0 = fout,
  nooit gokken) en 'gelijk' (elk doel gewicht 1);
- aandelen (fractie per doel, som 1) worden op 6 decimalen vastgelegd voor herleidbaarheid; de
  centen komen uit grootste-rest over de exacte gewichten, niet uit de afgeronde aandelen.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Verdeelbasis = Literal["m2", "gelijk"]
VERDEELBASES: tuple[Verdeelbasis, ...] = ("m2", "gelijk")

_CENT = Decimal("0.01")
_AANDEEL = Decimal("0.000001")


class VerdeelFout(ValueError):
    """Ongeldige verdeelinvoer (geen doelen, ontbrekend gewicht bij m², onbekende basis)."""


@dataclass(frozen=True)
class VerdeelDoel:
    """Eén doel om over te verdelen: `sleutel` = de identiteit (bv. project-id), `gewicht` =
    de m² (basis 'm2'); bij basis 'gelijk' wordt het gewicht genegeerd."""

    sleutel: str
    gewicht: Decimal | None = None
    naam: str | None = None


@dataclass(frozen=True)
class VerdeelDeel:
    sleutel: str
    aandeel: Decimal  # fractie, 6 decimalen, som ≈ 1
    bedrag: Decimal  # centen, som exact het te verdelen bedrag
    gewicht: Decimal  # het gebruikte gewicht (m² of 1)


def verdeel_naar_gewicht(bedrag: Decimal, gewichten: list[Decimal]) -> list[Decimal]:
    """Grootste-rest over willekeurige positieve gewichten; werkt op centen en ook voor
    negatieve bedragen (creditnota's): restcenten naar de grootste absolute rest, tie-break =
    eerste index (stabiel)."""
    if not gewichten:
        raise VerdeelFout("Geen doelen om over te verdelen")
    if any(g is None or g <= 0 for g in gewichten):
        raise VerdeelFout("Elk gewicht moet groter dan 0 zijn")
    totaal_gewicht = sum(gewichten, Decimal(0))
    centen = int((bedrag / _CENT).to_integral_value(rounding=ROUND_HALF_UP))
    ruw = [Decimal(centen) * g / totaal_gewicht for g in gewichten]
    vloer = [int(r.to_integral_value(rounding="ROUND_FLOOR")) if centen >= 0 else int(r.to_integral_value(rounding="ROUND_CEILING")) for r in ruw]
    rest = centen - sum(vloer)
    resten = sorted(range(len(ruw)), key=lambda i: (-(abs(ruw[i] - vloer[i])), i))
    stap = 1 if rest > 0 else -1
    for i in resten[: abs(rest)]:
        vloer[i] += stap
    delen = [Decimal(c) * _CENT for c in vloer]
    assert sum(delen, Decimal(0)) == Decimal(centen) * _CENT
    return delen


def verdeel_over_doelen(bedrag: Decimal, doelen: list[VerdeelDoel], basis: Verdeelbasis) -> list[VerdeelDeel]:
    """Verdeelt `bedrag` over `doelen` volgens `basis`. Basis 'm2': elk doel moet een gewicht > 0
    hebben — ontbrekende m² worden bij naam benoemd (nooit stil gokken). Eén doel = 100%."""
    if basis not in VERDEELBASES:
        raise VerdeelFout(f"Onbekende verdeelbasis '{basis}' — kies 'm2' of 'gelijk'")
    if not doelen:
        raise VerdeelFout("Geen doelen om over te verdelen")
    if len({d.sleutel for d in doelen}) != len(doelen):
        raise VerdeelFout("Dubbel doel in de verdeling")
    if basis == "m2":
        ontbrekend = [d.naam or d.sleutel for d in doelen if d.gewicht is None or d.gewicht <= 0]
        if ontbrekend:
            raise VerdeelFout(
                "Geen (contract-)m² bekend voor: " + ", ".join(ontbrekend) + " — vul de projectspecificatie aan of kies 'gelijk per object'"
            )
        gewichten = [d.gewicht for d in doelen]  # type: ignore[misc]
    else:
        gewichten = [Decimal(1) for _ in doelen]
    totaal = sum(gewichten, Decimal(0))
    delen = verdeel_naar_gewicht(bedrag, gewichten)
    return [
        VerdeelDeel(
            sleutel=d.sleutel,
            aandeel=(g / totaal).quantize(_AANDEEL, rounding=ROUND_HALF_UP),
            bedrag=deel,
            gewicht=g,
        )
        for d, g, deel in zip(doelen, gewichten, delen, strict=True)
    ]
