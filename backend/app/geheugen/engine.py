from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from app.config import settings
from app.geheugen.models import ObservatieBron

# Voorstel-engine van het boekingsgeheugen: puur en deterministisch (kernprincipe "code voor
# cijfers") — geen DB, geen AI, geen klok-afhankelijkheid (vandaag reist als parameter mee).
# Default voorstel, nooit blind boeken (CLAUDE.md): elk veld draagt een confidence + oranje-vlag
# die de UI en de latere autoboek-gate letterlijk overnemen; de harde checks (waaronder de
# projectplicht) blijven onverkort blokkerend, een voorstel heft nooit een check op.


@dataclass(frozen=True)
class Observatie:
    """Engine-invoer, bewust los van het ORM-model (zelfde patroon als checks.CheckRegel)."""

    regel_sleutel: str | None
    gb_id: uuid.UUID
    btw_id: uuid.UUID | None
    project_id: uuid.UUID | None
    bron: str
    bron_datum: date
    # Blok 3 (10-09 avond, "recency wint"): identiteit van de BOEKING waaruit deze observatie komt (boekstuknummer of
    # document-id) — de regel "laatste drie mens-boekingen identiek" groepeert observaties per boeking (een gesplitste
    # boeking levert meerdere observaties). None = onbekend → conservatieve groepering op bron_datum (zie
    # `_recente_mens_consensus`), nooit één observatie = één boeking.
    boeking_sleutel: str | None = None


@dataclass(frozen=True)
class VeldVoorstel:
    waarde: uuid.UUID | None
    # winnend gewicht / totaal gewicht van de meegewogen stemmen (0.0 zonder voorstel).
    confidence: float
    # aantal observaties dat de winnende waarde steunt (ongewogen telling).
    telling: int
    oranje: bool
    # korte, omschrijving-vrije reden voor de oranje-vlag (UI-tekst is aan de frontend).
    reden: str | None = None
    # True zodra >=1 app-observatie de winnende waarde steunt. Peters ontwerp (2026-07-14):
    # uitsluitend rlz_seed = altijd oranje, ook bij hoge stem-confidence — vertrouwen wordt in
    # de app verdiend, niet uit de historie afgeleid.
    app_bevestigd: bool = False
    # Blok 3 (10-09 avond, besluit Peter "recency wint"): True = de waarde won via de recency-regel (laatste
    # RECENTE_BOEKINGEN mens-boekingen op dit niveau identiek) — groen én app-bevestigd, óók als oudere observaties
    # een andere waarde droegen. Die oudere afwijkende waarden staan in `eerder_ook` (historie-chip "eerder ook: …"),
    # ze tellen niet meer mee in de tie-break maar verdwijnen niet stil.
    recent_consensus: bool = False
    eerder_ook: tuple[uuid.UUID, ...] = ()


#: Aantal opeenvolgende identieke mens-boekingen waarna de recency-regel de stem beslist (besluit Peter 10-09 avond:
#: "zijn de laatste drie mens-boekingen op leveranciersniveau identiek, dan is die waarde groen en app-bevestigd").
RECENTE_BOEKINGEN = 3


@dataclass(frozen=True)
class GeheugenVoorstel:
    gb: VeldVoorstel
    btw: VeldVoorstel
    project: VeldVoorstel


_GEEN_VOORSTEL = VeldVoorstel(
    waarde=None, confidence=0.0, telling=0, oranje=True, reden="geen observaties", app_bevestigd=False
)


def _gewicht(
    observatie: Observatie, *, vandaag: date, halfwaardetijd_dagen: int, basisgewichten: dict[str, float]
) -> float:
    basis = basisgewichten.get(observatie.bron, 1.0)
    leeftijd_dagen = max((vandaag - observatie.bron_datum).days, 0)
    return basis * 0.5 ** (leeftijd_dagen / halfwaardetijd_dagen)


@dataclass(frozen=True)
class _Stem:
    waarde: uuid.UUID
    confidence: float
    telling: int
    app_telling: int
    gesplitst: bool
    # aandeel (gewogen) en ongewogen telling per waarde — voor een recency-winnaar die niet de gewogen winnaar is.
    aandeel: dict[uuid.UUID, float] = field(default_factory=dict)
    tellingen: dict[uuid.UUID, int] = field(default_factory=dict)


def _boeking_groep(observatie: Observatie) -> tuple[date, str]:
    """Sorteer-/groepeersleutel van de boeking waar een observatie bij hoort: (datum, boeking_sleutel). Zonder
    boeking_sleutel (oude rijen, tests) vormen alle observaties van één dag samen één boeking — conservatief: dat
    maakt de reeks hooguit KORTER (regel slaat later aan), nooit langer."""
    return (observatie.bron_datum, observatie.boeking_sleutel or f"datum:{observatie.bron_datum.isoformat()}")


def _recente_mens_consensus(
    observaties: list[Observatie], veld: str, *, n: int = RECENTE_BOEKINGEN
) -> tuple[uuid.UUID | None, tuple[uuid.UUID, ...]]:
    """Recency-regel (blok 3, 10-09 avond): zijn de laatste `n` MENS-boekingen (bron app) met een waarde voor `veld`
    onderling identiek — binnen elke boeking één waarde, over de boekingen dezelfde — dan is die waarde de consensus.
    Retourneert (consensus | None, eerder_ook): `eerder_ook` = de andere waarden die in de (volledige) historie van dit
    veld voorkomen, deterministisch gesorteerd — voor de historie-chip, nooit voor de tie-break. Minder dan `n`
    mens-boekingen, een gesplitste boeking of een afwijking in de staart = geen consensus (None, ()). Automatische
    boekingen komen hier nooit binnen: de leerlus legt ze sinds 10-09 niet meer als observatie vast (geen mens erop)."""
    per_boeking: dict[tuple[date, str], set[uuid.UUID]] = {}
    for o in observaties:
        waarde = getattr(o, veld)
        if waarde is None or o.bron != ObservatieBron.APP.value:
            continue
        per_boeking.setdefault(_boeking_groep(o), set()).add(waarde)
    if len(per_boeking) < n:
        return None, ()
    staart = [per_boeking[k] for k in sorted(per_boeking)[-n:]]
    if any(len(waarden) != 1 for waarden in staart):
        return None, ()
    kandidaten = {next(iter(w)) for w in staart}
    if len(kandidaten) != 1:
        return None, ()
    consensus = next(iter(kandidaten))
    eerder = {getattr(o, veld) for o in observaties} - {None, consensus}
    return consensus, tuple(sorted(eerder, key=str))


def _stem(
    kandidaten: list[tuple[uuid.UUID, float, str]],
) -> _Stem | None:
    """Gewogen meerderheid over (waarde, gewicht, bron)-stemmen. Deterministisch bij gelijke
    gewichten: tiebreak op de laagste UUID-string, zodat twee runs nooit verschillend kiezen."""
    if not kandidaten:
        return None
    totaal = sum(gewicht for _, gewicht, _ in kandidaten)
    per_waarde: dict[uuid.UUID, float] = {}
    telling: dict[uuid.UUID, int] = {}
    app_telling: dict[uuid.UUID, int] = {}
    for waarde, gewicht, bron in kandidaten:
        per_waarde[waarde] = per_waarde.get(waarde, 0.0) + gewicht
        telling[waarde] = telling.get(waarde, 0) + 1
        if bron == ObservatieBron.APP.value:
            app_telling[waarde] = app_telling.get(waarde, 0) + 1
    winnaar = min(per_waarde, key=lambda w: (-per_waarde[w], str(w)))
    return _Stem(
        waarde=winnaar,
        confidence=per_waarde[winnaar] / totaal if totaal > 0 else 0.0,
        telling=telling[winnaar],
        app_telling=app_telling.get(winnaar, 0),
        gesplitst=len(per_waarde) > 1,
        aandeel={w: (g / totaal if totaal > 0 else 0.0) for w, g in per_waarde.items()},
        tellingen=dict(telling),
    )


def _veld_voorstel(
    stem: _Stem | None,
    *,
    extra_oranje_reden: str | None = None,
    consensus: tuple[uuid.UUID | None, tuple[uuid.UUID, ...]] = (None, ()),
) -> VeldVoorstel:
    if stem is None:
        return _GEEN_VOORSTEL
    recent, eerder_ook = consensus
    if recent is not None:
        # Recency wint (blok 3, 10-09 avond): de laatste RECENTE_BOEKINGEN mens-boekingen zijn identiek → deze waarde
        # is groen en app-bevestigd; een oudere afwijkende waarde maakt de stem niet meer "gesplitst" (ze blijft
        # zichtbaar in `eerder_ook`). Alleen de btw-leverancier-fallback blijft oranje — die regel gaat over het
        # NIVEAU, niet over de stem (0%-onderscheid is aangifte-kritisch).
        return VeldVoorstel(
            waarde=recent,
            confidence=stem.aandeel.get(recent, 0.0),
            telling=stem.tellingen.get(recent, 0),
            oranje=bool(extra_oranje_reden),
            reden=extra_oranje_reden or None,
            app_bevestigd=True,
            recent_consensus=True,
            eerder_ook=eerder_ook,
        )
    redenen: list[str] = []
    if extra_oranje_reden:
        redenen.append(extra_oranje_reden)
    if stem.gesplitst:
        # gesplitste stem is voor élk veld reden tot oranje — de winnaar is een meerderheid,
        # geen consensus.
        redenen.append("gesplitste stem")
    app_bevestigd = stem.app_telling >= 1
    if not app_bevestigd:
        # Peters ontwerp (2026-07-14): uitsluitend rlz_seed blijft oranje — óók bij een hoge,
        # eenduidige stem-confidence. De eerste app-bevestiging van deze waarde haalt 'm uit
        # oranje. (Verving de oude, zwakkere regel "oranje tot ≥2 consistente observaties".)
        redenen.append("alleen rlz-historie, nog geen app-bevestiging")
    return VeldVoorstel(
        waarde=stem.waarde,
        confidence=stem.confidence,
        telling=stem.telling,
        oranje=bool(redenen),
        reden="; ".join(redenen) or None,
        app_bevestigd=app_bevestigd,
    )


def bepaal_voorstel(
    observaties: list[Observatie],
    *,
    regel_sleutel: str | None = None,
    vandaag: date,
    halfwaardetijd_dagen: int | None = None,
    gewicht_app: float | None = None,
    gewicht_rlz_seed: float | None = None,
) -> GeheugenVoorstel:
    """Gewogen meerderheid per veld over de observaties van één (administratie, crediteur):

    - gewicht = basisgewicht(bron) × 0.5^(leeftijd/halfwaardetijd) — app > rlz_seed
      (CLAUDE.md: correcties wegen zwaarder), recenter weegt zwaarder.
    - GB/project: leverancier-niveau primair; bij een gesplitste leverancier-stem verfijnt het
      regel-niveau (observaties met dezelfde regel_sleutel), mits dat niveau stemmen heeft.
    - btw: regel-niveau eerst, leverancier-niveau als fallback — fallback en gesplitste stem
      zijn ALTIJD oranje (0%-onderscheid is aangifte-kritisch, zie CLAUDE.md).
    - RECENCY WINT (blok 3 vervolgrun 10-09 avond, besluit Peter): zijn de laatste RECENTE_BOEKINGEN mens-boekingen
      (bron app, gegroepeerd per boeking) op het gewogen niveau identiek, dan is die waarde groen + app-bevestigd —
      oudere afwijkende waarden tellen niet meer mee in de tie-break, ze reizen als `eerder_ook` mee (historie-chip).
      B, A, A, A → groen A; A, A, B → oranje (gesplitst); A, B, A, A → oranje; A, B, A, A, A → groen A. Seed-only
      blijft oranje (de regel telt alleen mens-boekingen). Automatische boekingen tellen niet en breken niet: de
      leerlus legt ze niet meer vast (`leerlus.leg_boeking_vast(automatisch=True)` = geen observatie).
    - oranje zolang de winnende waarde geen enkele app-observatie heeft (uitsluitend rlz_seed),
      óók bij een eenduidige stem met hoge confidence — voorstellen vanaf 1 observatie mag,
      vertrouwen wordt in de app verdiend (Peters ontwerp, 2026-07-14). `app_bevestigd` reist
      per veld mee in de response."""
    halfwaardetijd = halfwaardetijd_dagen or settings.boekingsgeheugen_halfwaardetijd_dagen
    basisgewichten = {
        ObservatieBron.APP.value: gewicht_app if gewicht_app is not None else settings.boekingsgeheugen_gewicht_app,
        ObservatieBron.RLZ_SEED.value: (
            gewicht_rlz_seed if gewicht_rlz_seed is not None else settings.boekingsgeheugen_gewicht_rlz_seed
        ),
    }

    def stemmen(bron_observaties: list[Observatie], veld: str) -> list[tuple[uuid.UUID, float, str]]:
        resultaat = []
        for observatie in bron_observaties:
            waarde = getattr(observatie, veld)
            if waarde is None:
                continue
            gewicht = _gewicht(
                observatie, vandaag=vandaag, halfwaardetijd_dagen=halfwaardetijd, basisgewichten=basisgewichten
            )
            resultaat.append((waarde, gewicht, observatie.bron))
        return resultaat

    regel_subset = [o for o in observaties if o.regel_sleutel == regel_sleutel] if regel_sleutel is not None else []

    # GB en project: leverancier-niveau primair; recency-consensus (blok 3, 10-09 avond) op dat niveau gaat vóór
    # de gewogen stem én vóór de regel-verfijning; zonder consensus verfijnt het regel-niveau bij een split.
    def gb_of_project(veld: str) -> VeldVoorstel:
        leverancier_stem = _stem(stemmen(observaties, veld))
        consensus = _recente_mens_consensus(observaties, veld)
        if consensus[0] is not None:
            return _veld_voorstel(leverancier_stem, consensus=consensus)
        if leverancier_stem is not None and leverancier_stem.gesplitst and regel_subset:
            regel_stem = _stem(stemmen(regel_subset, veld))
            if regel_stem is not None:
                return _veld_voorstel(regel_stem, consensus=_recente_mens_consensus(regel_subset, veld))
        return _veld_voorstel(leverancier_stem)

    # btw: regel-niveau eerst, leverancier-fallback — fallback altijd oranje (ook mét recency-consensus).
    btw_regel_stem = _stem(stemmen(regel_subset, "btw_id")) if regel_subset else None
    if btw_regel_stem is not None:
        btw = _veld_voorstel(btw_regel_stem, consensus=_recente_mens_consensus(regel_subset, "btw_id"))
    else:
        btw_leverancier_stem = _stem(stemmen(observaties, "btw_id"))
        extra = "leverancier-fallback" if btw_leverancier_stem is not None and regel_sleutel is not None else None
        btw = _veld_voorstel(
            btw_leverancier_stem,
            extra_oranje_reden=extra,
            consensus=_recente_mens_consensus(observaties, "btw_id"),
        )

    return GeheugenVoorstel(gb=gb_of_project("gb_id"), btw=btw, project=gb_of_project("project_id"))
