from __future__ import annotations

import uuid
from dataclasses import dataclass
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
    )


def _veld_voorstel(stem: _Stem | None, *, extra_oranje_reden: str | None = None) -> VeldVoorstel:
    if stem is None:
        return _GEEN_VOORSTEL
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

    regel_subset = (
        [o for o in observaties if o.regel_sleutel == regel_sleutel] if regel_sleutel is not None else []
    )

    # GB en project: leverancier-niveau primair, regel-niveau verfijnt bij een split.
    def gb_of_project(veld: str) -> VeldVoorstel:
        leverancier_stem = _stem(stemmen(observaties, veld))
        if leverancier_stem is not None and leverancier_stem.gesplitst and regel_subset:
            regel_stem = _stem(stemmen(regel_subset, veld))
            if regel_stem is not None:
                return _veld_voorstel(regel_stem)
        return _veld_voorstel(leverancier_stem)

    # btw: regel-niveau eerst, leverancier-fallback — fallback altijd oranje.
    btw_regel_stem = _stem(stemmen(regel_subset, "btw_id")) if regel_subset else None
    if btw_regel_stem is not None:
        btw = _veld_voorstel(btw_regel_stem)
    else:
        btw_leverancier_stem = _stem(stemmen(observaties, "btw_id"))
        extra = "leverancier-fallback" if btw_leverancier_stem is not None and regel_sleutel is not None else None
        btw = _veld_voorstel(btw_leverancier_stem, extra_oranje_reden=extra)

    return GeheugenVoorstel(gb=gb_of_project("gb_id"), btw=btw, project=gb_of_project("project_id"))
