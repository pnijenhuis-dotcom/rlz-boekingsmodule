"""Herberekening van een LOPENDE accorderingsronde bij een configuratiewijziging (bundel 09-09 blok 2; besluit
Peter 08-09, herziet "GECOMBINEERDE RUN 01-09" blok A beslispunt 2 "lopende rondes vervallen").

Puur en deterministisch — geen database, geen tijd. De servicelaag (`service._herbereken_open_rondes`) leest de
bevroren stappen van een open ronde en de nieuwe lagen, roept `herbereken` aan en schrijft de uitkomst weg.

Regels (opdracht 2a):
- Een gegeven akkoord blijft geldig als die accordeur in de nieuwe configuratie in DEZELFDE of een EERDERE laag
  staat (positie in de volgorde, niet het ruwe volgnummer) én die laag voor dit documentbedrag nog van toepassing
  is (drempel opnieuw geëvalueerd: onbekend bedrag = vereist, fail-closed — zelfde regel als bij het aanbieden).
- Een laag die door een drempelwijziging niet meer geldt voor dit bedrag vraagt niets; het akkoord van die
  accordeur telt wél mee als hij in een andere passende laag staat.
- Ontbrekende/nieuwe lagen worden opnieuw aangevraagd (stap zonder besluit); een nog onbesliste oude stap van
  dezelfde accordeur wordt hergebruikt (zijn plek in de wachtrij/melding blijft).
- De ronde VERVALT alleen als er akkoorden gegeven waren en géén daarvan meer past, of als er geen lagen
  overblijven (toggle uit). Zonder gegeven akkoord is er niets te verliezen: herberekenen, nooit vervallen.
- Zijn ná herberekening álle vereiste lagen gedekt → `alles_akkoord` (de servicelaag draait dan de bestaande
  afrondingsroute, exact zoals bij een laatste akkoord).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

AKKOORD = "akkoord"


@dataclass(frozen=True)
class StapStand:
    """De bevroren stap zoals die nu op de ronde staat (invoer)."""

    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    bedrag_drempel: Decimal | None
    vereist: bool
    besluit: str | None


@dataclass(frozen=True)
class LaagSpec:
    """Eén laag uit de nieuwe configuratie."""

    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    bedrag_drempel: Decimal | None


@dataclass(frozen=True)
class NieuweStap:
    """Eén stap van de herberekende ronde. `bron_index` wijst naar de oude stap die deze stap voortzet (akkoord
    behouden of onbesliste stap hergebruikt); None = nieuw aan te maken."""

    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    bedrag_drempel: Decimal | None
    vereist: bool
    bron_index: int | None
    akkoord_behouden: bool


@dataclass(frozen=True)
class Herberekening:
    stappen: tuple[NieuweStap, ...]
    # Indices (in de invoer) van oude stappen die niet voortgezet worden — akkoord vervallen of laag verdwenen.
    vervallen_indices: tuple[int, ...]
    akkoorden_gegeven: int
    akkoorden_behouden: int
    # Volgnummers van vereiste lagen zonder (behouden) akkoord — die worden opnieuw aangevraagd.
    opnieuw_aangevraagd: tuple[int, ...]
    alles_akkoord: bool
    ronde_vervalt: bool

    @property
    def akkoorden_vervallen(self) -> int:
        return self.akkoorden_gegeven - self.akkoorden_behouden


def is_vereist(bedrag_drempel: Decimal | None, totaalbedrag: Decimal | None) -> bool:
    """Drempelregel — identiek aan het aanbieden: laag geldt alleen bóven het bedrag; onbekend bedrag = vereist."""
    return bedrag_drempel is None or totaalbedrag is None or abs(totaalbedrag) > bedrag_drempel


def herbereken(
    oude_stappen: Sequence[StapStand],
    nieuwe_lagen: Sequence[LaagSpec],
    totaalbedrag: Decimal | None,
) -> Herberekening:
    oude_volgorde = sorted(range(len(oude_stappen)), key=lambda i: oude_stappen[i].volgnummer)
    # "Dezelfde of een eerdere laag" = positie in de reeks VEREISTE lagen (wat de accordeur ervaart), niet het
    # ruwe volgnummer en niet-vereiste lagen tellen niet mee in de volgorde.
    oude_rang = {index: rang for rang, index in enumerate(i for i in oude_volgorde if oude_stappen[i].vereist)}
    gebruikt: set[int] = set()
    stappen: list[NieuweStap] = []
    nieuwe_rang = -1

    for laag in sorted(nieuwe_lagen, key=lambda spec: spec.volgnummer):
        vereist = is_vereist(laag.bedrag_drempel, totaalbedrag)
        bron: int | None = None
        behouden = False
        if vereist:
            nieuwe_rang += 1
            # Akkoord behouden: zelfde accordeur, akkoord gegeven, nieuwe positie gelijk aan of vóór de oude.
            for index in oude_volgorde:
                oud = oude_stappen[index]
                if (
                    index not in gebruikt
                    and oud.accordeur_gebruiker_id == laag.accordeur_gebruiker_id
                    and oud.besluit == AKKOORD
                    and index in oude_rang
                    and oude_rang[index] >= nieuwe_rang
                ):
                    bron = index
                    behouden = True
                    break
        if bron is None:
            # Onbesliste stap van dezelfde accordeur hergebruiken (positie/drempel volgen de nieuwe laag).
            for index in oude_volgorde:
                oud = oude_stappen[index]
                if (
                    index not in gebruikt
                    and oud.accordeur_gebruiker_id == laag.accordeur_gebruiker_id
                    and oud.besluit is None
                ):
                    bron = index
                    break
        if bron is not None:
            gebruikt.add(bron)
        stappen.append(
            NieuweStap(
                volgnummer=laag.volgnummer,
                accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
                bedrag_drempel=laag.bedrag_drempel,
                vereist=vereist,
                bron_index=bron,
                akkoord_behouden=behouden,
            )
        )

    vervallen_indices = tuple(i for i in range(len(oude_stappen)) if i not in gebruikt)
    akkoorden_gegeven = sum(1 for s in oude_stappen if s.besluit == AKKOORD)
    akkoorden_behouden = sum(1 for s in stappen if s.akkoord_behouden)
    opnieuw = tuple(s.volgnummer for s in stappen if s.vereist and not s.akkoord_behouden)
    ronde_vervalt = not nieuwe_lagen or (akkoorden_gegeven > 0 and akkoorden_behouden == 0)
    return Herberekening(
        stappen=tuple(stappen),
        vervallen_indices=vervallen_indices,
        akkoorden_gegeven=akkoorden_gegeven,
        akkoorden_behouden=akkoorden_behouden,
        opnieuw_aangevraagd=opnieuw,
        alles_akkoord=not ronde_vervalt and not opnieuw,
        ronde_vervalt=ronde_vervalt,
    )
