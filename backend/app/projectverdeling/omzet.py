"""Omzetstand per project (ontwerpnotitie ①②): geboekte VERKOOP-regels uit de projectcijfers-cache
(`project_regel_cache`, soort 'verkoop', documentdatum in de kalendermaand) — RLZ/Odoo blijft de bron, dit is
de eigen datalaag die de cijfers-sync vult. Alleen ACTIEVE projecten (`is_actief`, niet verdwenen), alleen
omzet > 0, het interne overhead-project (OVH) uitgesloten. Geen RLZ-calls."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.projecten.models import CijfersSyncRunStatus, ProjectCijfersSyncRun, ProjectRegelCache, ProjectRegelSoort
from app.projectverdeling.data import Omzetstand, periode_eind
from app.sync.models import ProjectCache

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


@dataclass(frozen=True)
class OmzetSelectie:
    standen: list[Omzetstand]  # alleen projecten mét omzet > 0, OVH uit, actief
    cache_leeg: bool  # géén enkele verkoopregel in de cache voor deze administratie → sync nog nooit gedraaid


def omzet_per_project(session: Session, *, administratie_id: uuid.UUID, periode: date) -> OmzetSelectie:
    """Σ netto van de verkoopregels per project in [periode, volgende maand), gefilterd op actieve, niet-OVH
    projecten. `cache_leeg` onderscheidt "geen omzet die maand" van "de cijfers-sync heeft nog nooit gedraaid"
    (lege stand = actie: knop naar de cijfers-sync)."""
    eind = periode_eind(periode)
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
            ProjectRegelCache.datum >= periode,
            ProjectRegelCache.datum < eind,
            ProjectCache.is_actief.is_(True),
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
    return OmzetSelectie(standen=standen, cache_leeg=cache_leeg)


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
