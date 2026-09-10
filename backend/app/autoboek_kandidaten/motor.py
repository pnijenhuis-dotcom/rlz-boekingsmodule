"""Autoboek-kandidaten-motor — PURE logica (mockup autoboek-kandidaten.html, besluit Peter 01-09;
aanleiding: de per-leverancier-opt-in schaalt niet over ~80 administraties als Peter zelf moet
zoeken). Het systeem nomineert deterministisch leveranciers waarvoor autoboeken verantwoord is;
AANZETTEN blijft een menselijk besluit (de bestaande opt-in is de enige schrijver).

Kwalificatie per (administratie, leverancier), zonder AI en zonder RLZ-calls:
1. ≥ N opeenvolgende IDENTIEKE MENS-boekingen (N = Beheerder-instelling, platformbreed 3 sinds blok A
   10-09). Telling herzien 10-09 avond (blok 3, besluit Peter "3× exact hetzelfde = drie identieke
   boekingen"): de reeks is de langste staart van opeenvolgende mens-boekingen waarvan de vergelijkbare
   velden (GB, btw, project bij projectplicht — per regel, op leveranciersniveau) onderling gelijk zijn;
   de eerste boeking van een reeks telt als 1, een afwijkende boeking start een nieuwe reeks (en telt
   zelf als 1). Tot 10-09 telde de motor "ongewijzigd t.o.v. het geheugen-voorstel" — de eerste boeking
   was referentiepunt en telde niet, zodat "3 op rij" in feite vier boekingen vroeg. Het VOORSTEL blijft
   wél de maat voor CORRECTIES (heroverwegen: mens wijkt af van wat het systeem zou boeken) en de service
   toetst dat het actuele geheugen-voorstel gelijk is aan de reeks-waarden (`Reeks.reeks_waarden`) —
   nooit activeren op een reeks die het geheugen nog niet zelf voorstelt. Automatisch geboekte
   documenten tellen niet als bevestiging (geen mens erop) en breken de reeks niet.
2. Het ACTUELE geheugen-voorstel is volledig app-bevestigd en groen (zelfde poort als het
   autoboek-pad, app/documenten/autoboeken.py::_geheugen_veld_geblokkeerd) — dit toetst de service
   met `voorstel_voor`; de motor krijgt de uitkomst als invoer.
3. Geen open vraag, geen afwijzing en geen duplicaatsignaal op een niet-afgerond document van
   deze leverancier; geen veldwerker-koppeling (dat pad heeft zijn eigen opt-in).

Heroverwegen (advies-only, zet NOOIT zelf uit): voor een actieve opt-in de signalen ná activatie —
mens-correctie (GB/btw/project gewijzigd t.o.v. het voorstel), vraag of afwijzing, correctie op een
automatisch geboekt document (tegenboeking/herboeking), buitenland-tarief (Labo-Derva-les)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from app.documenten.checks import is_buitenland_tarief
from app.geheugen.engine import Observatie, bepaal_voorstel
from app.geheugen.models import ObservatieBron
from app.geheugen.normalisatie import normaliseer_regel_sleutel


@dataclass(frozen=True)
class GeboekteRegel:
    gb_id: uuid.UUID | None
    btw_id: uuid.UUID | None
    project_id: uuid.UUID | None
    omschrijving: str | None = None
    btw_naam: str | None = None


@dataclass(frozen=True)
class Boeking:
    """Eén GEBOEKT-overgang van een inkoopfactuur van deze leverancier, chronologisch te verwerken."""

    document_id: uuid.UUID
    geboekt_op: datetime
    factuurdatum: date | None
    totaalbedrag: Decimal | None
    regels: tuple[GeboekteRegel, ...]
    automatisch: bool = False
    regels_samenvoegen: bool = True


@dataclass(frozen=True)
class Gebeurtenis:
    """Vraag/afwijzing/tegenboeking op een document van deze leverancier (voor teller + heroverwegen)."""

    soort: str  # 'vraag' | 'afwijzing' | 'correctie_automatisch'
    tijdstip: datetime
    document_id: uuid.UUID


@dataclass(frozen=True)
class Reeks:
    """Uitkomst van de reeks-analyse (chronologisch)."""

    reeks_ongewijzigd: int
    correcties: int
    laatste_correctie: datetime | None
    laatste_correctie_velden: tuple[str, ...]
    mens_boekingen: int
    laatste_factuur_datum: date | None
    laatste_factuur_bedrag: Decimal | None
    laatste_document_id: uuid.UUID | None
    bedrag_vast: bool | None
    buitenland: bool
    correcties_na: dict[str, int] = field(default_factory=dict)
    #: Handtekening van de reeks (blok 3 10-09): de vergelijkbare velden per regel van de laatste mens-boeking —
    #: tuples (regel_sleutel | None, gb_id, btw_id, project_id | None). Leeg zonder mens-boeking in de reeks.
    reeks_waarden: frozenset[tuple[str | None, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]] = frozenset()


def _voorstel_regels(
    observaties: list[Observatie], boeking: Boeking, *, project_verplicht: bool
) -> list[tuple[str, ...]]:
    """Per regel de afwijkende velden t.o.v. het geheugen-voorstel vóór deze boeking (leeg = ongewijzigd).
    Sinds 10-09 (blok 3) alleen nog de maat voor CORRECTIES (heroverwegen), niet voor de reeks-teller.
    Zonder enig voorstel (eerste boeking ooit, geen historie) is er niets om van af te wijken — 'geen_voorstel'."""
    afwijkingen: list[tuple[str, ...]] = []
    gesplitst = not boeking.regels_samenvoegen and len(boeking.regels) > 1
    for regel in boeking.regels:
        sleutel = normaliseer_regel_sleutel(regel.omschrijving) if gesplitst else None
        voorstel = bepaal_voorstel(observaties, regel_sleutel=sleutel, vandaag=boeking.geboekt_op.date())
        velden: list[str] = []
        if voorstel.gb.waarde is None:
            velden.append("geen_voorstel")
        else:
            if regel.gb_id != voorstel.gb.waarde:
                velden.append("grootboek")
            if voorstel.btw.waarde is not None and regel.btw_id != voorstel.btw.waarde:
                velden.append("btw")
            if voorstel.btw.waarde is None and regel.btw_id is not None and observaties:
                # Geheugen kende wél de leverancier maar geen btw → de mens koos zelf: geen bevestiging.
                velden.append("btw")
            if project_verplicht and regel.project_id != voorstel.project.waarde:
                velden.append("project")
        afwijkingen.append(tuple(velden))
    return afwijkingen


def _observaties_van(boeking: Boeking) -> list[Observatie]:
    gesplitst = not boeking.regels_samenvoegen and len(boeking.regels) > 1
    uit: list[Observatie] = []
    for regel in boeking.regels:
        if regel.gb_id is None:
            continue
        uit.append(
            Observatie(
                regel_sleutel=normaliseer_regel_sleutel(regel.omschrijving) if gesplitst else None,
                gb_id=regel.gb_id,
                btw_id=regel.btw_id,
                project_id=regel.project_id,
                bron=ObservatieBron.APP.value,
                bron_datum=boeking.geboekt_op.date(),
            )
        )
    return uit


Handtekening = frozenset[tuple[str | None, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]]


def _handtekening(boeking: Boeking, *, project_verplicht: bool) -> Handtekening:
    """De vergelijkbare velden van een boeking op leveranciersniveau: per regel (regel_sleutel, GB, btw, project).
    Regelteksten tellen niet — de regel_sleutel komt alleen mee als de leverancier regels gesplitst boekt
    (`regels_samenvoegen=False`), precies zoals het geheugen dan per regel-sleutel voorstelt; het project telt
    alleen bij projectplicht. Volgorde en aantal gelijke regels zijn irrelevant (set)."""
    gesplitst = not boeking.regels_samenvoegen and len(boeking.regels) > 1
    return frozenset(
        (
            normaliseer_regel_sleutel(regel.omschrijving) if gesplitst else None,
            regel.gb_id,
            regel.btw_id,
            regel.project_id if project_verplicht else None,
        )
        for regel in boeking.regels
    )


def analyseer_reeks(
    boekingen: list[Boeking],
    *,
    seed_observaties: list[Observatie],
    project_verplicht: bool,
    vanaf: datetime | None = None,
    reeks_vanaf: datetime | None = None,
) -> Reeks:
    """Loopt de boekingen chronologisch af en bepaalt de reeks identieke mens-boekingen.

    DEFINITIE (besluit Peter 10-09 avond, blok 3 — "3× exact hetzelfde" = drie identieke mens-boekingen):
    - `reeks_ongewijzigd` = de lengte van de langste STAART van opeenvolgende mens-boekingen waarvan de
      vergelijkbare velden onderling gelijk zijn (`_handtekening`: per regel GB, btw, project bij projectplicht;
      regel-sleutel alleen bij gesplitst boeken). De eerste boeking van een reeks telt als 1; een afwijkende
      boeking start een nieuwe reeks en telt zelf als 1. Drie identieke boekingen = 3 (tot 10-09: 2, omdat de
      eerste boeking referentiepunt was en niet telde).
    - Automatisch geboekte documenten tellen niet (geen mens erop) en breken de reeks niet: ze voegen hun
      waarden wél toe aan het geheugen (dat doet de leerlus ook) en aan de laatste-document-velden.
    - `reeks_vanaf` (blok A bundel 10-09: reset ná storno/correctie van een automatische boeking) = boekingen
      op of vóór dat moment voeden alleen nog het geheugen — de reeks en de mens-teller starten bij 0 en tellen
      uitsluitend boekingen erná ("leert 0/N").
    - `correcties`, `laatste_correctie(_velden)` en `correcties_na` blijven gemeten t.o.v. het geheugen-
      VOORSTEL vóór de boeking (`_voorstel_regels`): dát is wat het autoboek-pad zou boeken, dus een afwijking
      dáárvan is de correctie die heroverwegen moet zien. `vanaf` telt de correcties ná dat moment apart
      ("N correcties ná activatie").
    - `reeks_waarden` = de handtekening van de reeks; de service toetst daarmee dat het actuele geheugen-
      voorstel dezelfde waarden voorstelt (kwalificatiecriterium "geheugen bevestigd" blijft onverkort)."""
    observaties = list(seed_observaties)
    reeks = 0
    correcties = 0
    mens = 0
    laatste_correctie: datetime | None = None
    laatste_velden: tuple[str, ...] = ()
    correcties_na: dict[str, int] = {}
    buitenland = False
    bedragen: list[Decimal] = []
    laatste: Boeking | None = None
    vorige_handtekening: Handtekening | None = None
    for boeking in sorted(boekingen, key=lambda b: b.geboekt_op):
        if any(is_buitenland_tarief(r.btw_naam) for r in boeking.regels):
            buitenland = True
        if boeking.automatisch or (reeks_vanaf is not None and boeking.geboekt_op <= reeks_vanaf):
            observaties.extend(_observaties_van(boeking))
            laatste = boeking
            continue
        mens += 1
        afwijkingen = _voorstel_regels(observaties, boeking, project_verplicht=project_verplicht)
        gewijzigd = sorted({v for velden in afwijkingen for v in velden if v != "geen_voorstel"})
        if gewijzigd:
            correcties += 1
            laatste_correctie = boeking.geboekt_op
            laatste_velden = tuple(gewijzigd)
            if vanaf is not None and boeking.geboekt_op > vanaf:
                for v in gewijzigd:
                    correcties_na[v] = correcties_na.get(v, 0) + 1
        handtekening = _handtekening(boeking, project_verplicht=project_verplicht)
        if vorige_handtekening is not None and handtekening == vorige_handtekening:
            reeks += 1
        else:
            reeks = 1  # eerste boeking van een (nieuwe) reeks telt zelf mee
        vorige_handtekening = handtekening
        if boeking.totaalbedrag is not None:
            bedragen.append(boeking.totaalbedrag)
        observaties.extend(_observaties_van(boeking))
        laatste = boeking
    recente = bedragen[-max(reeks, 2) :] if bedragen else []
    bedrag_vast = (len(set(recente)) == 1) if len(recente) >= 2 else None
    return Reeks(
        reeks_ongewijzigd=reeks,
        correcties=correcties,
        laatste_correctie=laatste_correctie,
        laatste_correctie_velden=laatste_velden,
        mens_boekingen=mens,
        laatste_factuur_datum=laatste.factuurdatum if laatste else None,
        laatste_factuur_bedrag=laatste.totaalbedrag if laatste else None,
        laatste_document_id=laatste.document_id if laatste else None,
        bedrag_vast=bedrag_vast,
        buitenland=buitenland,
        correcties_na=correcties_na,
        reeks_waarden=vorige_handtekening or frozenset(),
    )


def reeks_tekst(n: int) -> str:
    """Leesbare telling (blok 3 10-09): "3 identieke boekingen" / "1 identieke boeking" / "0 identieke boekingen"."""
    return f"{n} identieke boeking{'' if n == 1 else 'en'}"


@dataclass(frozen=True)
class Kwalificatie:
    kwalificeert: bool
    redenen: tuple[str, ...]  # leesbare blokkades (leeg = kandidaat)
    chips: tuple[str, ...]  # onderbouwing (mockup: "12 identieke boekingen", "geheugen bevestigd", …)


def kwalificeer(
    reeks: Reeks,
    *,
    drempel: int,
    geheugen_bevestigd: bool,
    geheugen_reden: str | None,
    open_vragen: int,
    afgewezen: int,
    duplicaatsignalen: int,
    veldwerker_gekoppeld: bool,
) -> Kwalificatie:
    """Deterministische poort (ontwerpnotitie ②): élke reden is leesbaar — de bulk-aanzet-actie hertoetst
    hiermee live en slaat een rij die niet meer kwalificeert over mét deze reden."""
    redenen: list[str] = []
    if reeks.reeks_ongewijzigd < drempel:
        redenen.append(f"{reeks_tekst(reeks.reeks_ongewijzigd)} (drempel {drempel})")
    if not geheugen_bevestigd:
        redenen.append(f"geheugen niet volledig app-bevestigd ({geheugen_reden or 'oranje'})")
    if open_vragen:
        redenen.append(f"{open_vragen} open vraag{'' if open_vragen == 1 else 'en'}")
    if afgewezen:
        redenen.append(f"{afgewezen} afgewezen document{'' if afgewezen == 1 else 'en'}")
    if duplicaatsignalen:
        redenen.append(f"{duplicaatsignalen} duplicaatsigna{'al' if duplicaatsignalen == 1 else 'len'}")
    if veldwerker_gekoppeld:
        redenen.append("crediteur gekoppeld aan een veldwerker — autoboeken loopt via de urenmatch-opt-in")
    chips = [
        reeks_tekst(reeks.reeks_ongewijzigd),
        "geheugen bevestigd" if geheugen_bevestigd else "geheugen nog oranje",
        f"{open_vragen} vragen / {reeks.correcties} correcties",
    ]
    if reeks.bedrag_vast is True:
        chips.append("vast maandbedrag")
    elif reeks.bedrag_vast is False:
        chips.append("bedrag wisselt")
    if reeks.buitenland:
        chips.append("buitenland-tarief")
    return Kwalificatie(kwalificeert=not redenen, redenen=tuple(redenen), chips=tuple(chips))


_VELD_LABEL = {"grootboek": "GB-code", "btw": "btw-tarief", "project": "project"}


def heroverweeg_signalen(
    reeks: Reeks,
    *,
    gebeurtenissen: list[Gebeurtenis],
    actief_sinds: datetime | None,
) -> tuple[str, ...]:
    """Advies-only signalen voor een ACTIEVE opt-in (ontwerpnotitie ⑤): alleen wat ná de activatie
    gebeurde telt; zonder activatiemoment = geen signalen (nooit gokken)."""
    if actief_sinds is None:
        return ()
    signalen: list[str] = []
    totaal = sum(reeks.correcties_na.values())
    if totaal:
        signalen.append(f"{totaal} correctie{'' if totaal == 1 else 's'} ná activatie")
        if reeks.laatste_correctie is not None and reeks.laatste_correctie > actief_sinds:
            for veld in reeks.laatste_correctie_velden:
                signalen.append(f"{_VELD_LABEL.get(veld, veld)} gewijzigd door mens ({reeks.laatste_correctie:%d %b})")
    for g in sorted(gebeurtenissen, key=lambda x: x.tijdstip):
        if g.tijdstip <= actief_sinds:
            continue
        if g.soort == "vraag":
            signalen.append(f"vraag gesteld ({g.tijdstip:%d %b})")
        elif g.soort == "afwijzing":
            signalen.append(f"afgewezen ({g.tijdstip:%d %b})")
        elif g.soort == "correctie_automatisch":
            signalen.append(f"correctie op automatisch geboekt document ({g.tijdstip:%d %b})")
    if reeks.buitenland:
        signalen.append("buitenland-signaal")
    # Dedupliceren mét behoud van volgorde.
    gezien: set[str] = set()
    uit = []
    for s in signalen:
        if s not in gezien:
            gezien.add(s)
            uit.append(s)
    return tuple(uit)
