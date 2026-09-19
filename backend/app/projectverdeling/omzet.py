"""Omzetstand per project (ontwerpnotitie ①②): geboekte VERKOOP-regels uit de projectcijfers-cache
(`project_regel_cache`, soort 'verkoop', documentdatum in de kalendermaand) — RLZ/Odoo blijft de bron, dit is
de eigen datalaag die de cijfers-sync vult. Alleen ACTIEVE projecten (`is_actief` = bron-spiegel ÉN module-status
≠ `afgesloten` (0160, opdracht 19-09), niet verdwenen), alleen omzet > 0, het interne overhead-project (OVH)
uitgesloten. Een project dat alleen op zijn NAAM "afgesloten" zegt maar actief staat, blijft in de sleutel —
nooit stil uitsluiten op naam (opdracht 19-09: dat is een LET-OP "afsluiten?", geen filter). Geen RLZ-calls."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.projecten.models import CijfersSyncRunStatus, ProjectCijfersSyncRun, ProjectRegelCache, ProjectRegelSoort
from app.projectverdeling.data import Omzetstand, Periode, als_periode, periode_eind
from app.sync.models import PROJECT_STATUS_AFGESLOTEN, ProjectCache

# Herkenning van het interne overhead-project (CLAUDE.md "Projecten": overhead → intern OVH-project; mockup
# index.html: "OVH · Overhead / algemene kosten (intern)"). Er bestaat geen aparte markering in de RLZ-
# projectdata, dus deterministisch op de NAAM: eerste token "OVH" (met of zonder scheidingsteken) óf het woord
# "overhead". Beslispunt Peter: expliciete markering per administratie als dit te grof blijkt.
_OVH_TOKENS = frozenset({"OVH", "OVH.", "OVH:", "OVH·", "OVH-", "OVERHEAD"})


def is_ovh_project(naam: str | None) -> bool:
    if not naam:
        return False
    tokens = naam.replace("·", " ").replace("-", " ").replace(":", " ").split()
    if not tokens:
        return False
    if tokens[0].upper() in _OVH_TOKENS:
        return True
    return "OVERHEAD" in naam.upper()


def naam_zegt_afgesloten(naam: str | None) -> bool:
    """Opdracht 19-09: de RLZ-naamconventie van Universal zet "Afgesloten " vóór de naam van een afgerond project
    ("Afgesloten 26012 Tilburg (van Kasteren)"). Deterministisch op het eerste woord, hoofdletterongevoelig. Wordt
    NOOIT als filter gebruikt — alleen als signaal "naam zegt afgesloten, status actief — afsluiten?"."""
    if not naam:
        return False
    eerste = naam.strip().split(maxsplit=1)
    return bool(eerste) and eerste[0].lower().rstrip(":-·") == "afgesloten"


@dataclass(frozen=True)
class OmzetSelectie:
    standen: list[Omzetstand]  # alleen projecten mét omzet > 0, OVH uit, actief én niet afgesloten
    cache_leeg: bool  # géén enkele verkoopregel in de cache voor deze administratie → sync nog nooit gedraaid
    #: Opdracht 19-09: projecten die WÉL in de sleutel zitten maar op naam "afgesloten" zeggen (status actief) — het
    #: signaal voor de LET-OP "afsluiten?" (reconciliatieblok `projecten`); geen filter.
    naam_afgesloten_actief: list[Omzetstand] = field(default_factory=list)


def omzet_per_project(
    session: Session, *, administratie_id: uuid.UUID, periode: Periode | date, vandaag: date | None = None
) -> OmzetSelectie:
    """Σ netto van de verkoopregels per project in [start, eind), gefilterd op actieve (bron-spiegel `is_actief` ÉN
    module-status ≠ afgesloten), niet-OVH projecten.
    Maand: [eerste dag, volgende maand); jaar (D4 07-09, notitie ⑩): [1 januari, min(1 januari volgend jaar,
    eerste dag van de lopende maand)) — alleen AFGESLOTEN maanden, dezelfde uitsluitingen. `cache_leeg`
    onderscheidt "geen omzet in de periode" van "de cijfers-sync heeft nog nooit gedraaid" (lege stand = actie:
    knop naar de cijfers-sync)."""
    periode = als_periode(periode)
    assert periode is not None
    eind = periode_eind(periode, vandaag)
    rijen = session.execute(
        select(ProjectRegelCache.project_id, func.sum(ProjectRegelCache.netto_bedrag), ProjectCache.naam)
        .join(
            ProjectCache,
            (ProjectCache.id == ProjectRegelCache.project_id)
            & (ProjectCache.administratie_id == ProjectRegelCache.administratie_id),
        )
        .where(
            ProjectRegelCache.administratie_id == administratie_id,
            ProjectRegelCache.soort == ProjectRegelSoort.VERKOOP.value,
            ProjectRegelCache.verdwenen_uit_bron_op.is_(None),
            ProjectRegelCache.datum >= periode.start,
            ProjectRegelCache.datum < eind,
            ProjectCache.is_actief.is_(True),
            ProjectCache.status != PROJECT_STATUS_AFGESLOTEN,
            ProjectCache.verdwenen_uit_bron_op.is_(None),
        )
        .group_by(ProjectRegelCache.project_id, ProjectCache.naam)
        .order_by(ProjectCache.naam)
    ).all()
    standen = [
        Omzetstand(project_id=pid, omzet=omzet, project_naam=naam)
        for pid, omzet, naam in rijen
        if omzet is not None and omzet > 0 and not is_ovh_project(naam)
    ]
    cache_leeg = False
    if not standen:
        aantal = session.scalar(
            select(func.count())
            .select_from(ProjectRegelCache)
            .where(
                ProjectRegelCache.administratie_id == administratie_id,
                ProjectRegelCache.soort == ProjectRegelSoort.VERKOOP.value,
            )
        )
        cache_leeg = not aantal
    return OmzetSelectie(
        standen=standen,
        cache_leeg=cache_leeg,
        naam_afgesloten_actief=[s for s in standen if naam_zegt_afgesloten(s.project_naam)],
    )


def actieve_projecten_met_afgesloten_naam(session: Session, *, administratie_id: uuid.UUID) -> list[ProjectCache]:
    """Opdracht 19-09: projecten die op naam "afgesloten" zeggen maar nog actief staan (bron `is_actief` én module-
    status lopend) — de bron voor de LET-OP "naam zegt afgesloten, status actief — afsluiten?" (blok `projecten`).
    Universal 19-09: 94 zulke namen, 8 nog actief. Nooit een filter: de sleutel neemt ze mee tot een mens afsluit."""
    rijen = session.scalars(
        select(ProjectCache)
        .where(
            ProjectCache.administratie_id == administratie_id,
            ProjectCache.verdwenen_uit_bron_op.is_(None),
            ProjectCache.is_actief.is_(True),
            ProjectCache.status != PROJECT_STATUS_AFGESLOTEN,
        )
        .order_by(ProjectCache.naam)
    )
    return [p for p in rijen if naam_zegt_afgesloten(p.naam)]


def laatste_cijfers_sync(session: Session, *, administratie_id: uuid.UUID) -> datetime | None:
    """Moment van de laatste geslaagde projectcijfers-sync — de hercontrole rekent buiten de maandcadans alleen
    door als er sindsdien verse cijfers zijn."""
    return session.scalar(
        select(func.max(ProjectCijfersSyncRun.beeindigd_op)).where(
            ProjectCijfersSyncRun.administratie_id == administratie_id,
            ProjectCijfersSyncRun.status == CijfersSyncRunStatus.KLAAR.value,
        )
    )


def projectnamen(session: Session, *, administratie_id: uuid.UUID, project_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not project_ids:
        return {}
    rijen = session.execute(
        select(ProjectCache.id, ProjectCache.naam).where(
            ProjectCache.administratie_id == administratie_id, ProjectCache.id.in_(project_ids)
        )
    ).all()
    return {pid: naam for pid, naam in rijen if naam}
