"""Autoboek-kandidaten-motor — PURE logica (mockup autoboek-kandidaten.html, besluit Peter 01-09;
aanleiding: de per-leverancier-opt-in schaalt niet over ~80 administraties als Peter zelf moet
zoeken). Het systeem nomineert deterministisch leveranciers waarvoor autoboeken verantwoord is;
AANZETTEN blijft een menselijk besluit (de bestaande opt-in is de enige schrijver).

Kwalificatie per (administratie, leverancier), zonder AI en zonder RLZ-calls:
1. ≥ N opeenvolgende MENS-boekingen waarbij het voorstel ONGEWIJZIGD is geboekt (N = Beheerder-
   instelling, default 5). "Ongewijzigd" = de door de mens geboekte waarden (GB, btw, project bij
   projectplicht) zijn per regel gelijk aan wat het boekingsgeheugen vóór die boeking voorstelde —
   herleid uit de boekingen zelf, chronologisch (zelfde engine `bepaal_voorstel`). Een afwijking is
   een correctie: de teller start opnieuw (ontwerpnotitie ⑦/"teller start opnieuw ná elke
   correctie"). Automatisch geboekte documenten tellen niet als bevestiging (geen mens erop).
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


def _voorstel_regels(
    observaties: list[Observatie], boeking: Boeking, *, project_verplicht: bool
) -> list[tuple[str, ...]]:
    """Per regel de afwijkende velden t.o.v. het geheugen-voorstel vóór deze boeking (leeg = ongewijzigd).
    Zonder enig voorstel (eerste boeking ooit, geen historie) is er niets bevestigd — telt als 'geen
    voorstel' (reeks start pas ná de tweede gelijke boeking)."""
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


def analyseer_reeks(
    boekingen: list[Boeking],
    *,
    seed_observaties: list[Observatie],
    project_verplicht: bool,
    vanaf: datetime | None = None,
) -> Reeks:
    """Loopt de boekingen chronologisch af en herleidt per boeking of het voorstel ongewijzigd is
    geboekt. De teller telt uitsluitend mens-boekingen; een automatisch geboekt document voegt zijn
    waarden wél toe aan het geheugen (dat doet de leerlus ook) maar bevestigt niets. `vanaf` telt de
    correcties ná dat moment apart (heroverwegen: "N correcties ná activatie")."""
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
    for boeking in sorted(boekingen, key=lambda b: b.geboekt_op):
        if any(is_buitenland_tarief(r.btw_naam) for r in boeking.regels):
            buitenland = True
        if boeking.automatisch:
            observaties.extend(_observaties_van(boeking))
            laatste = boeking
            continue
        mens += 1
        afwijkingen = _voorstel_regels(observaties, boeking, project_verplicht=project_verplicht)
        gewijzigd = sorted({v for velden in afwijkingen for v in velden if v != "geen_voorstel"})
        geen_voorstel = any("geen_voorstel" in velden for velden in afwijkingen)
        if gewijzigd:
            correcties += 1
            reeks = 0
            laatste_correctie = boeking.geboekt_op
            laatste_velden = tuple(gewijzigd)
            if vanaf is not None and boeking.geboekt_op > vanaf:
                for v in gewijzigd:
                    correcties_na[v] = correcties_na.get(v, 0) + 1
        elif geen_voorstel:
            reeks = 0  # eerste boeking zonder enige historie: niets bevestigd, wél de basis
        else:
            reeks += 1
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
    )


@dataclass(frozen=True)
class Kwalificatie:
    kwalificeert: bool
    redenen: tuple[str, ...]  # leesbare blokkades (leeg = kandidaat)
    chips: tuple[str, ...]  # onderbouwing (mockup: "12 op rij ongewijzigd", "geheugen bevestigd", …)


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
        redenen.append(f"{reeks.reeks_ongewijzigd} op rij ongewijzigd (drempel {drempel})")
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
        f"{reeks.reeks_ongewijzigd} op rij ongewijzigd",
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
