"""Werkopdrachten per project × periode (mockup planning-werkopdracht-transport.html, akkoord
Peter 31-08, migratie 0091 — BESLISSINGEN "PLANNING-UITBREIDING 31-08").

Ontwerp:
- Een werkopdracht is een GROEP (stabiel `groep_id`) met append-only VERSIES: wijzigen = een
  nieuwe rij met versie+1, de hoogste versie geldt, oudere versies zijn de historie in de
  popup. De DB-grant kent geen UPDATE/DELETE (migratie 0091) — niets wordt overschreven.
- Meerdere én overlappende werkopdrachten per project zijn geldig (montage + demontage).
- Dag-override: per (groep, datum) een afwijkende tekst — sparse, alleen die dag wint; de
  periode-tekst blijft de basis voor de overige dagen. Zelfde versiepatroon.
- De veld-app toont de geldende tekst alleen-lezen bij elke geplande dag binnen de periode;
  bewust GEEN pushmelding bij een tekstwijziging (besluit Peter 31-08).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Gebruiker
from app.db.session import scoped_session
from app.sync.models import ProjectCache
from app.uren.models import Werkopdracht, WerkopdrachtDag
from app.uren.service import (
    MODULE,
    NietGevonden,
    OngeldigeInvoer,
    _administratie_met_opt_in,
    _vereis_meerwerk_recht,
)


@dataclass(slots=True)
class DagOverrideData:
    datum: date
    tekst: str


@dataclass(slots=True)
class HistorieRegelData:
    tijdstip: datetime
    door_naam: str
    omschrijving: str


@dataclass(slots=True)
class WerkopdrachtData:
    groep_id: uuid.UUID
    project_id: uuid.UUID
    versie: int
    van: date
    tot_en_met: date
    tekst: str
    dag_overrides: list[DagOverrideData] = field(default_factory=list)
    historie: list[HistorieRegelData] = field(default_factory=list)


@dataclass(slots=True)
class DagTekstData:
    """Geldende opdrachttekst op één dag (veld-app + dagcel): override wint voor die dag."""

    groep_id: uuid.UUID
    tekst: str
    afwijkend: bool  # True = dag-override (mockup: "di afwijkend: …")


def _actuele_versies(
    session: Session, administratie_id: uuid.UUID, project_id: uuid.UUID | None = None
) -> list[Werkopdracht]:
    """Hoogste versie per groep (append-only: de laatste rij per groep is de geldende)."""
    stmt = select(Werkopdracht).where(Werkopdracht.administratie_id == administratie_id)
    if project_id is not None:
        stmt = stmt.where(Werkopdracht.project_id == project_id)
    per_groep: dict[uuid.UUID, Werkopdracht] = {}
    for rij in session.scalars(stmt.order_by(Werkopdracht.groep_id, Werkopdracht.versie)):
        per_groep[rij.groep_id] = rij
    return sorted(per_groep.values(), key=lambda w: (w.van, w.aangemaakt_op))


def _actuele_overrides(
    session: Session, administratie_id: uuid.UUID, groep_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, date], WerkopdrachtDag]:
    """Hoogste versie per (groep, datum)."""
    if not groep_ids:
        return {}
    resultaat: dict[tuple[uuid.UUID, date], WerkopdrachtDag] = {}
    for rij in session.scalars(
        select(WerkopdrachtDag)
        .where(WerkopdrachtDag.administratie_id == administratie_id, WerkopdrachtDag.groep_id.in_(groep_ids))
        .order_by(WerkopdrachtDag.groep_id, WerkopdrachtDag.datum, WerkopdrachtDag.versie)
    ):
        resultaat[(rij.groep_id, rij.datum)] = rij
    return resultaat


def _namen(session: Session, gebruiker_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not gebruiker_ids:
        return {}
    return {
        g.id: g.naam for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(gebruiker_ids)))
    }


def _historie(session: Session, administratie_id: uuid.UUID, groep_id: uuid.UUID) -> list[HistorieRegelData]:
    """Alle append-only rijen van de groep (versies + dag-overrides), chronologisch."""
    versies = list(
        session.scalars(
            select(Werkopdracht)
            .where(Werkopdracht.administratie_id == administratie_id, Werkopdracht.groep_id == groep_id)
            .order_by(Werkopdracht.versie)
        )
    )
    overrides = list(
        session.scalars(
            select(WerkopdrachtDag)
            .where(WerkopdrachtDag.administratie_id == administratie_id, WerkopdrachtDag.groep_id == groep_id)
            .order_by(WerkopdrachtDag.aangemaakt_op)
        )
    )
    namen = _namen(session, {r.aangemaakt_door for r in versies} | {r.aangemaakt_door for r in overrides})
    regels = [
        HistorieRegelData(
            tijdstip=v.aangemaakt_op,
            door_naam=namen.get(v.aangemaakt_door, "?"),
            omschrijving="aangemaakt" if v.versie == 1 else f"gewijzigd (versie {v.versie})",
        )
        for v in versies
    ] + [
        HistorieRegelData(
            tijdstip=o.aangemaakt_op,
            door_naam=namen.get(o.aangemaakt_door, "?"),
            omschrijving=(
                f"dag-override {o.datum.isoformat()} toegevoegd"
                if o.versie == 1
                else f"dag-override {o.datum.isoformat()} gewijzigd (versie {o.versie})"
            ),
        )
        for o in overrides
    ]
    return sorted(regels, key=lambda r: r.tijdstip)


def _data(
    session: Session, administratie_id: uuid.UUID, actueel: Werkopdracht, *, met_historie: bool = True
) -> WerkopdrachtData:
    overrides = _actuele_overrides(session, administratie_id, [actueel.groep_id])
    return WerkopdrachtData(
        groep_id=actueel.groep_id,
        project_id=actueel.project_id,
        versie=actueel.versie,
        van=actueel.van,
        tot_en_met=actueel.tot_en_met,
        tekst=actueel.tekst,
        dag_overrides=sorted(
            (DagOverrideData(datum=o.datum, tekst=o.tekst) for o in overrides.values()), key=lambda d: d.datum
        ),
        historie=_historie(session, administratie_id, actueel.groep_id) if met_historie else [],
    )


def _valideer(van: date, tot_en_met: date, tekst: str) -> str:
    tekst = tekst.strip()
    if not tekst:
        raise OngeldigeInvoer("De opdrachttekst mag niet leeg zijn")
    if van > tot_en_met:
        raise OngeldigeInvoer("De einddatum ligt vóór de begindatum")
    return tekst


def _actief_project(session: Session, administratie_id: uuid.UUID, project_id: uuid.UUID) -> ProjectCache:
    project = session.get(ProjectCache, (project_id, administratie_id))
    if project is None or project.verdwenen_uit_bron_op is not None:
        raise NietGevonden("Project niet gevonden in deze administratie")
    return project


def _actueel(session: Session, administratie_id: uuid.UUID, groep_id: uuid.UUID) -> Werkopdracht:
    rij = session.scalars(
        select(Werkopdracht)
        .where(Werkopdracht.administratie_id == administratie_id, Werkopdracht.groep_id == groep_id)
        .order_by(Werkopdracht.versie.desc())
        .limit(1)
    ).first()
    if rij is None:
        raise NietGevonden("Werkopdracht niet gevonden")
    return rij


def maak_werkopdracht(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    van: date,
    tot_en_met: date,
    tekst: str,
    actor_id: uuid.UUID,
) -> WerkopdrachtData:
    tekst = _valideer(van, tot_en_met, tekst)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        _actief_project(session, administratie_id, project_id)
        rij = Werkopdracht(
            administratie_id=administratie_id,
            project_id=project_id,
            groep_id=uuid.uuid4(),
            versie=1,
            van=van,
            tot_en_met=tot_en_met,
            tekst=tekst,
            aangemaakt_door=actor_id,
        )
        session.add(rij)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="werkopdracht",
            record_id=rij.groep_id,
            actie="werkopdracht_aangemaakt",
            correlatie_id=project_id,
            nieuwe_waarde={"van": van.isoformat(), "tot_en_met": tot_en_met.isoformat(), "tekst": tekst},
            administratie_id=administratie_id,
        )
        return _data(session, administratie_id, rij)


def wijzig_werkopdracht(
    *,
    administratie_id: uuid.UUID,
    groep_id: uuid.UUID,
    van: date,
    tot_en_met: date,
    tekst: str,
    actor_id: uuid.UUID,
) -> WerkopdrachtData:
    """Append-only: een nieuwe versie-rij; de oude blijft als historie staan."""
    tekst = _valideer(van, tot_en_met, tekst)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        huidig = _actueel(session, administratie_id, groep_id)
        if (huidig.van, huidig.tot_en_met, huidig.tekst) == (van, tot_en_met, tekst):
            return _data(session, administratie_id, huidig)  # idempotent — geen lege versie
        nieuw = Werkopdracht(
            administratie_id=administratie_id,
            project_id=huidig.project_id,
            groep_id=groep_id,
            versie=huidig.versie + 1,
            van=van,
            tot_en_met=tot_en_met,
            tekst=tekst,
            aangemaakt_door=actor_id,
        )
        session.add(nieuw)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="werkopdracht",
            record_id=groep_id,
            actie="werkopdracht_gewijzigd",
            correlatie_id=huidig.project_id,
            oude_waarde={
                "van": huidig.van.isoformat(),
                "tot_en_met": huidig.tot_en_met.isoformat(),
                "tekst": huidig.tekst,
            },
            nieuwe_waarde={"van": van.isoformat(), "tot_en_met": tot_en_met.isoformat(), "tekst": tekst},
            administratie_id=administratie_id,
        )
        return _data(session, administratie_id, nieuw)


def zet_dag_override(
    *,
    administratie_id: uuid.UUID,
    groep_id: uuid.UUID,
    datum: date,
    tekst: str,
    actor_id: uuid.UUID,
) -> WerkopdrachtData:
    """Afwijkende tekst voor één dag (sparse — alleen die dag wint). Append-only versies."""
    tekst = tekst.strip()
    if not tekst:
        raise OngeldigeInvoer("De afwijkende dagtekst mag niet leeg zijn")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        actueel = _actueel(session, administratie_id, groep_id)
        if not (actueel.van <= datum <= actueel.tot_en_met):
            raise OngeldigeInvoer("De dag valt buiten de periode van de werkopdracht")
        bestaand = _actuele_overrides(session, administratie_id, [groep_id]).get((groep_id, datum))
        if bestaand is not None and bestaand.tekst == tekst:
            return _data(session, administratie_id, actueel)  # idempotent
        rij = WerkopdrachtDag(
            administratie_id=administratie_id,
            groep_id=groep_id,
            datum=datum,
            versie=(bestaand.versie + 1) if bestaand is not None else 1,
            tekst=tekst,
            aangemaakt_door=actor_id,
        )
        session.add(rij)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="werkopdracht_dag",
            record_id=groep_id,
            actie="werkopdracht_dag_override_gezet",
            correlatie_id=actueel.project_id,
            oude_waarde={"datum": datum.isoformat(), "tekst": bestaand.tekst} if bestaand is not None else None,
            nieuwe_waarde={"datum": datum.isoformat(), "tekst": tekst},
            administratie_id=administratie_id,
        )
        return _data(session, administratie_id, actueel)


def werkopdrachten_project(
    *, administratie_id: uuid.UUID, project_id: uuid.UUID, actor_id: uuid.UUID
) -> list[WerkopdrachtData]:
    """Alle werkopdrachten van één project (actuele versie + historie + dag-overrides) — de popup."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        _actief_project(session, administratie_id, project_id)
        return [_data(session, administratie_id, w) for w in _actuele_versies(session, administratie_id, project_id)]


def werkopdrachten_voor_grid(
    session: Session, *, administratie_id: uuid.UUID, maandag: date, zondag: date
) -> tuple[dict[uuid.UUID, list[WerkopdrachtData]], dict[tuple[uuid.UUID, date], list[DagTekstData]]]:
    """Voeding van het kantoor-weekgrid (in de bestaande planning-sessie): per project de
    actuele werkopdrachten die de week raken (chip in de rijkop) en per (project, datum) de
    dag-overrides binnen de week (blok in de dagcel)."""
    actuele = [w for w in _actuele_versies(session, administratie_id) if w.van <= zondag and w.tot_en_met >= maandag]
    overrides = _actuele_overrides(session, administratie_id, [w.groep_id for w in actuele])
    per_project: dict[uuid.UUID, list[WerkopdrachtData]] = {}
    for w in actuele:
        per_project.setdefault(w.project_id, []).append(
            WerkopdrachtData(
                groep_id=w.groep_id,
                project_id=w.project_id,
                versie=w.versie,
                van=w.van,
                tot_en_met=w.tot_en_met,
                tekst=w.tekst,
            )
        )
    per_dag: dict[tuple[uuid.UUID, date], list[DagTekstData]] = {}
    groep_project = {w.groep_id: w.project_id for w in actuele}
    for (groep_id, datum), o in overrides.items():
        if maandag <= datum <= zondag and groep_id in groep_project:
            per_dag.setdefault((groep_project[groep_id], datum), []).append(
                DagTekstData(groep_id=groep_id, tekst=o.tekst, afwijkend=True)
            )
    return per_project, per_dag


def teksten_voor_dag(
    session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID, datum: date
) -> list[DagTekstData]:
    """Geldende opdrachtteksten op één (project, dag) — de veld-app: override wint per groep."""
    actuele = [
        w
        for w in _actuele_versies(session, administratie_id, project_id)
        if w.van <= datum <= w.tot_en_met
    ]
    overrides = _actuele_overrides(session, administratie_id, [w.groep_id for w in actuele])
    resultaat: list[DagTekstData] = []
    for w in actuele:
        o = overrides.get((w.groep_id, datum))
        if o is not None:
            resultaat.append(DagTekstData(groep_id=w.groep_id, tekst=o.tekst, afwijkend=True))
        else:
            resultaat.append(DagTekstData(groep_id=w.groep_id, tekst=w.tekst, afwijkend=False))
    return resultaat
