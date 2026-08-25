"""Kantoor-projectenmodule — invoerkant (mockup projecten-invoer.html, akkoord Peter 22-08):
projectenlijst met compleetheids-badges, projectdetail (specs, documenten, staffels,
leverancier-werknummers), nieuw project via de bestaande RLZ-projectmotor-bouwstenen
(klant-loze top-level PUT, 50-tekens-poort, IsActive true, project_cache-upsert — géén
tweede motor) en de schrijfpaden voor project_specificatie / project_staffel /
project_document / leverancier_werknummer (alles geaudit).

Toegang (opdracht 22-08 + mockup-keuze 4): lezen = elke kantoorrol (router-breed
vereis_kantoorrol) mét klantscope; WIJZIGEN = Beheerder of Boekhouding+Projecten
(server-side hier afgedwongen, nooit alleen de client-knop)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import DetacheerderKoppeling, Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.documenten.rlz_ids import _NAMESPACE  # type: ignore[attr-defined]
from app.documenten.storage import standaard_opslag
from app.projecten.models import LeverancierWerknummer, ProjectOntledingRegel
from app.projecten.motor import ProjectAanmakenMislukt, ProjectNaamConflict, _upsert_project_cache
from app.projecten.naamconventie import OngeldigeProjectnaam, vorm_projectnaam
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import ProjectCache, VendorCache
from app.uren.models import (
    MeerwerkEenheid,
    ProjectDocument,
    ProjectPrijsafspraak,
    ProjectSpecificatie,
    ProjectStaffel,
    UrenProjectToewijzing,
    VeldwerkerCrediteur,
    Weekstaat,
)
from app.uren.overzichten import _gebouwd_m2

_SCHRIJF_ROLLEN = (GebruikerRol.BEHEERDER, GebruikerRol.BOEKHOUDING_PROJECTEN)

_DOCUMENT_SOORTEN = ("contract", "offerte")
_EENHEDEN = tuple(e.value for e in MeerwerkEenheid)

_NUMMER_PATROON = re.compile(r"^(\d{3,5})\b")


class ProjectenFout(Exception):
    """Basis voor domeinfouten in de kantoor-projectenmodule."""


class GeenSchrijfrecht(ProjectenFout):
    """Wijzigen is voorbehouden aan Beheerder en Boekhouding+Projecten (mockup-keuze 4)."""


class OngeldigeInvoer(ProjectenFout):
    pass


class ProjectNietGevonden(ProjectenFout):
    pass


def rlz_steiger_project_id(administratie_id: uuid.UUID, projectnummer: str) -> uuid.UUID:
    """Deterministisch client-GUID voor een vanuit de projectenmodule aangemaakt RLZ-project —
    functie van administratie + projectnummer (de stabiele identiteit in de naamconventie
    "26xxx Plaats (Opdrachtgever)"): twee keer klikken op hetzelfde nummer raakt hetzelfde
    RLZ-project, nooit een duplicaat (zelfde vorm als rlz_pand_project_id)."""
    genormaliseerd = " ".join(projectnummer.split()).lower()
    return uuid.uuid5(_NAMESPACE, f"steigerproject:{administratie_id}:{genormaliseerd}")


def _vereis_schrijfrol(session: Session, actor_id: uuid.UUID) -> None:
    actor = session.get(Gebruiker, actor_id)
    if actor is None or actor.rol not in _SCHRIJF_ROLLEN:
        raise GeenSchrijfrecht("Projectgegevens wijzigen is voorbehouden aan Beheerder en Boekhouding+Projecten")


def _vereis_project(session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID) -> ProjectCache:
    project = session.get(ProjectCache, (project_id, administratie_id))
    if project is None or project.verdwenen_uit_bron_op is not None:
        raise ProjectNietGevonden(f"Onbekend project: {project_id}")
    return project


# --- lijst -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectLijstRij:
    project_id: uuid.UUID
    naam: str | None
    is_actief: bool
    opdrachtgever: str | None
    werknummer_opdrachtgever: str | None
    specs_status: str  # 'compleet' | 'onvolledig' | 'geen'
    documenten: dict[str, int]  # soort → aantal
    staffels: int
    gebouwd_m2: Decimal
    contract_m2: Decimal | None
    doorlopende_huur: bool
    heeft_activiteit: bool  # uren-/meerwerk-activiteit (voedt de "zonder specs"-teller)


def _specs_status(spec: ProjectSpecificatie | None) -> str:
    if spec is None:
        return "geen"
    kern = (spec.opdrachtgever, spec.contract_m2, spec.looptijd_tot)
    if all(v is not None and v != "" for v in kern):
        return "compleet"
    if any(v is not None and v != "" for v in kern):
        return "onvolledig"
    return "geen"


def projecten_lijst(
    *, administratie_id: uuid.UUID, zoek: str = "", alleen_actief: bool = True
) -> list[ProjectLijstRij]:
    term = zoek.strip().lower()
    with scoped_session(administratie_id) as session:
        query = select(ProjectCache).where(
            ProjectCache.administratie_id == administratie_id,
            ProjectCache.verdwenen_uit_bron_op.is_(None),
        )
        if alleen_actief:
            query = query.where(ProjectCache.is_actief.is_(True))
        projecten = list(session.scalars(query.order_by(ProjectCache.naam)))
        project_ids = [p.id for p in projecten]

        specs = {
            s.project_id: s
            for s in session.scalars(
                select(ProjectSpecificatie).where(
                    ProjectSpecificatie.administratie_id == administratie_id,
                    ProjectSpecificatie.project_id.in_(project_ids),
                )
            )
        }
        documenten: dict[uuid.UUID, dict[str, int]] = {}
        for project_id, soort, aantal in session.execute(
            select(ProjectDocument.project_id, ProjectDocument.soort, func.count())
            .where(ProjectDocument.administratie_id == administratie_id)
            .group_by(ProjectDocument.project_id, ProjectDocument.soort)
        ):
            documenten.setdefault(project_id, {})[soort] = aantal
        staffels = dict(
            session.execute(
                select(ProjectStaffel.project_id, func.count())
                .where(ProjectStaffel.administratie_id == administratie_id)
                .group_by(ProjectStaffel.project_id)
            ).all()
        )
        # Activiteit = een weekstaat óf een uren-projectkoppeling (de "zonder specs"-teller telt
        # alleen projecten waar het veld echt op werkt — mockup-keuze 5).
        activiteit = set(
            session.scalars(
                select(Weekstaat.project_id.distinct()).where(Weekstaat.administratie_id == administratie_id)
            )
        ) | set(
            session.scalars(
                select(UrenProjectToewijzing.project_id.distinct()).where(
                    UrenProjectToewijzing.administratie_id == administratie_id
                )
            )
        )

        rijen: list[ProjectLijstRij] = []
        for project in projecten:
            spec = specs.get(project.id)
            doorzoekbaar = " ".join(
                filter(
                    None,
                    (
                        project.naam,
                        spec.opdrachtgever if spec else None,
                        spec.werknummer_opdrachtgever if spec else None,
                    ),
                )
            ).lower()
            if term and term not in doorzoekbaar:
                continue
            rijen.append(
                ProjectLijstRij(
                    project_id=project.id,
                    naam=project.naam,
                    is_actief=bool(project.is_actief),
                    opdrachtgever=spec.opdrachtgever if spec else None,
                    werknummer_opdrachtgever=spec.werknummer_opdrachtgever if spec else None,
                    specs_status=_specs_status(spec),
                    documenten=documenten.get(project.id, {}),
                    staffels=staffels.get(project.id, 0),
                    gebouwd_m2=_gebouwd_m2(session, administratie_id, project.id),
                    contract_m2=spec.contract_m2 if spec else None,
                    doorlopende_huur=bool(spec and spec.doorlopende_huur_omschrijving),
                    heeft_activiteit=project.id in activiteit,
                )
            )
        return rijen


# --- detail + schrijfpaden ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectDocumentInfo:
    id: uuid.UUID
    soort: str
    titel: str
    versie_omschrijving: str | None
    bestandsnaam: str
    aangemaakt_op: datetime
    ontleed: bool  # er bestaan ontleding-regels voor dit document


@dataclass(frozen=True)
class StaffelInfo:
    id: uuid.UUID
    omschrijving: str
    eenheid: str
    prijs_per_eenheid: Decimal
    verrekenbaar: bool
    bron: str | None
    aangemaakt_op: datetime


@dataclass(frozen=True)
class WerknummerInfo:
    id: uuid.UUID
    vendor_id: uuid.UUID
    leverancier_naam: str | None
    werknummer: str
    bron: str
    bevestigd: bool
    aangemaakt_op: datetime


@dataclass(frozen=True)
class OntledingRegelInfo:
    id: uuid.UUID
    project_document_id: uuid.UUID
    soort: str
    omschrijving: str
    citaat: str | None
    waarde: dict | None
    zekerheid: Decimal | None
    status: str


@dataclass(frozen=True)
class PrijsafspraakInfo:
    """Projectafspraak per veldwerker (B1): tarief + eenheid + ISO-week-venster; `standaard_tarief` =
    het koppeling-tarief dat anders zou gelden (ZZP: veldwerker_crediteur.uurtarief; via bureau:
    detacheerder_koppeling.uurtarief) — de mockup-kolom "Standaard (koppeling)"."""

    id: uuid.UUID
    gebruiker_id: uuid.UUID
    veldwerker_naam: str | None
    via_bureau_naam: str | None
    eenheid: str
    tarief: Decimal
    geldig_vanaf_jaar: int | None
    geldig_vanaf_week: int | None
    geldig_tm_jaar: int | None
    geldig_tm_week: int | None
    toelichting: str | None
    standaard_tarief: Decimal | None
    aangemaakt_op: datetime
    aangemaakt_door_naam: str | None
    ingetrokken_op: datetime | None
    ingetrokken_reden: str | None


@dataclass(frozen=True)
class VeldwerkerKeuze:
    """ZZP'er gekoppeld aan dit project — kandidaat voor een prijsafspraak."""

    gebruiker_id: uuid.UUID
    naam: str
    via_bureau_naam: str | None
    standaard_tarief: Decimal | None


@dataclass(frozen=True)
class ProjectDetail:
    project_id: uuid.UUID
    naam: str | None
    is_actief: bool
    specificatie: ProjectSpecificatie | None
    documenten: list[ProjectDocumentInfo]
    staffels: list[StaffelInfo]
    werknummers: list[WerknummerInfo]
    ontleding: list[OntledingRegelInfo]
    gebouwd_m2: Decimal
    prijsafspraken: list[PrijsafspraakInfo] = field(default_factory=list)
    veldwerkers: list[VeldwerkerKeuze] = field(default_factory=list)


def _standaard_tarief(
    session: Session, *, administratie_id: uuid.UUID, zzper_id: uuid.UUID
) -> tuple[Decimal | None, str | None]:
    """(koppeling-tarief, bureau-naam): eigen ZZP-koppeling wint; anders het bureau-tarief van de
    (eerste) detacheerder-koppeling — dezelfde volgorde als de factuurmatch-leden."""
    eigen = session.scalars(
        select(VeldwerkerCrediteur).where(
            VeldwerkerCrediteur.administratie_id == administratie_id, VeldwerkerCrediteur.gebruiker_id == zzper_id
        )
    ).first()
    # De lees-policy op platform.detacheerder_koppeling is actor-gebonden (0057: eigen rijen +
    # systeem-actor) — voor de weergave "via <bureau>" lezen we als systeem-actor, net als de
    # factuurmatch-motor (de uitkomst mag niet van de toevallige kijker afhangen).
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as platform_sessie:
        bureau = platform_sessie.scalars(
            select(DetacheerderKoppeling).where(DetacheerderKoppeling.zzper_gebruiker_id == zzper_id)
        ).first()
        bureau_naam = None
        bureau_tarief = None
        if bureau is not None:
            b = platform_sessie.get(Gebruiker, bureau.detacheerder_gebruiker_id)
            bureau_naam = b.naam if b else None
            bureau_tarief = bureau.uurtarief
    if eigen is not None and eigen.uurtarief is not None:
        return eigen.uurtarief, bureau_naam
    if bureau_tarief is not None:
        return bureau_tarief, bureau_naam
    return None, bureau_naam


def _prijsafspraak_info(session: Session, a: ProjectPrijsafspraak, namen: dict[uuid.UUID, str]) -> PrijsafspraakInfo:
    standaard, bureau_naam = _standaard_tarief(session, administratie_id=a.administratie_id, zzper_id=a.gebruiker_id)
    return PrijsafspraakInfo(
        id=a.id,
        gebruiker_id=a.gebruiker_id,
        veldwerker_naam=namen.get(a.gebruiker_id),
        via_bureau_naam=bureau_naam,
        eenheid=a.eenheid,
        tarief=a.tarief,
        geldig_vanaf_jaar=a.geldig_vanaf_jaar,
        geldig_vanaf_week=a.geldig_vanaf_week,
        geldig_tm_jaar=a.geldig_tm_jaar,
        geldig_tm_week=a.geldig_tm_week,
        toelichting=a.toelichting,
        standaard_tarief=standaard,
        aangemaakt_op=a.aangemaakt_op,
        aangemaakt_door_naam=namen.get(a.aangemaakt_door),
        ingetrokken_op=a.ingetrokken_op,
        ingetrokken_reden=a.ingetrokken_reden,
    )


def project_detail(*, administratie_id: uuid.UUID, project_id: uuid.UUID) -> ProjectDetail:
    with scoped_session(administratie_id) as session:
        project = _vereis_project(session, administratie_id=administratie_id, project_id=project_id)
        spec = session.get(ProjectSpecificatie, (project_id, administratie_id))
        ontleding_rijen = list(
            session.scalars(
                select(ProjectOntledingRegel)
                .where(
                    ProjectOntledingRegel.administratie_id == administratie_id,
                    ProjectOntledingRegel.project_id == project_id,
                )
                .order_by(ProjectOntledingRegel.aangemaakt_op, ProjectOntledingRegel.omschrijving)
            )
        )
        ontleed_docs = {r.project_document_id for r in ontleding_rijen}
        documenten = [
            ProjectDocumentInfo(
                id=d.id,
                soort=d.soort,
                titel=d.titel,
                versie_omschrijving=d.versie_omschrijving,
                bestandsnaam=d.bestandsnaam,
                aangemaakt_op=d.aangemaakt_op,
                ontleed=d.id in ontleed_docs,
            )
            for d in session.scalars(
                select(ProjectDocument)
                .where(
                    ProjectDocument.administratie_id == administratie_id,
                    ProjectDocument.project_id == project_id,
                )
                .order_by(ProjectDocument.aangemaakt_op.desc())
            )
        ]
        staffels = [
            StaffelInfo(
                id=s.id,
                omschrijving=s.omschrijving,
                eenheid=s.eenheid,
                prijs_per_eenheid=s.prijs_per_eenheid,
                verrekenbaar=s.verrekenbaar,
                bron=s.bron,
                aangemaakt_op=s.aangemaakt_op,
            )
            for s in session.scalars(
                select(ProjectStaffel)
                .where(
                    ProjectStaffel.administratie_id == administratie_id,
                    ProjectStaffel.project_id == project_id,
                )
                .order_by(ProjectStaffel.aangemaakt_op)
            )
        ]
        werknummer_rijen = list(
            session.scalars(
                select(LeverancierWerknummer)
                .where(
                    LeverancierWerknummer.administratie_id == administratie_id,
                    LeverancierWerknummer.project_id == project_id,
                )
                .order_by(LeverancierWerknummer.aangemaakt_op)
            )
        )
        vendor_namen = dict(
            session.execute(
                select(VendorCache.id, VendorCache.naam).where(
                    VendorCache.administratie_id == administratie_id,
                    VendorCache.id.in_([w.vendor_id for w in werknummer_rijen]),
                )
            ).all()
        )
        werknummers = [
            WerknummerInfo(
                id=w.id,
                vendor_id=w.vendor_id,
                leverancier_naam=vendor_namen.get(w.vendor_id),
                werknummer=w.werknummer,
                bron=w.bron,
                bevestigd=w.bevestigd,
                aangemaakt_op=w.aangemaakt_op,
            )
            for w in werknummer_rijen
        ]
        ontleding = [
            OntledingRegelInfo(
                id=r.id,
                project_document_id=r.project_document_id,
                soort=r.soort,
                omschrijving=r.omschrijving,
                citaat=r.citaat,
                waarde=r.waarde,
                zekerheid=r.zekerheid,
                status=r.status,
            )
            for r in ontleding_rijen
        ]
        # Detached kopie van de spec-velden (de sessie sluit hierna).
        spec_kopie = None
        if spec is not None:
            session.expunge(spec)
            spec_kopie = spec
        afspraken = session.scalars(
            select(ProjectPrijsafspraak)
            .where(
                ProjectPrijsafspraak.administratie_id == administratie_id, ProjectPrijsafspraak.project_id == project_id
            )
            .order_by(ProjectPrijsafspraak.ingetrokken_op.is_not(None), ProjectPrijsafspraak.aangemaakt_op.desc())
        ).all()
        toewijzingen = session.scalars(
            select(UrenProjectToewijzing).where(
                UrenProjectToewijzing.administratie_id == administratie_id,
                UrenProjectToewijzing.project_id == project_id,
            )
        ).all()
        gebruiker_ids = (
            {a.gebruiker_id for a in afspraken}
            | {a.aangemaakt_door for a in afspraken}
            | {t.gebruiker_id for t in toewijzingen}
        )
        gebruikers = (
            {g.id: g for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(gebruiker_ids)))}
            if gebruiker_ids
            else {}
        )
        namen = {gid: g.naam for gid, g in gebruikers.items()}
        prijsafspraken = [_prijsafspraak_info(session, a, namen) for a in afspraken]
        veldwerkers: list[VeldwerkerKeuze] = []
        for t in toewijzingen:
            g = gebruikers.get(t.gebruiker_id)
            if g is None or g.rol != GebruikerRol.ZZPER:
                continue
            standaard, bureau_naam = _standaard_tarief(session, administratie_id=administratie_id, zzper_id=g.id)
            veldwerkers.append(
                VeldwerkerKeuze(gebruiker_id=g.id, naam=g.naam, via_bureau_naam=bureau_naam, standaard_tarief=standaard)
            )
        veldwerkers.sort(key=lambda v: v.naam)
        return ProjectDetail(
            project_id=project_id,
            naam=project.naam,
            is_actief=bool(project.is_actief),
            specificatie=spec_kopie,
            documenten=documenten,
            staffels=staffels,
            werknummers=werknummers,
            ontleding=ontleding,
            prijsafspraken=prijsafspraken,
            veldwerkers=veldwerkers,
            gebouwd_m2=_gebouwd_m2(session, administratie_id, project_id),
        )


def zet_specificatie(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    opdrachtgever: str | None = None,
    werknummer_opdrachtgever: str | None = None,
    soort_werk: str | None = None,
    contract_m2: Decimal | None = None,
    looptijd_van: date | None = None,
    looptijd_tot: date | None = None,
    huurtijd_omschrijving: str | None = None,
    doorlopende_huur_omschrijving: str | None = None,
) -> None:
    """Upsert van de projectspecificatie (mockup specs-grid) — voedt de uitvoerder-app, de
    planning (looptijd) en de projectsignalen."""
    if looptijd_van is not None and looptijd_tot is not None and looptijd_tot < looptijd_van:
        raise OngeldigeInvoer("Looptijd-einde ligt vóór de start")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        _vereis_project(session, administratie_id=administratie_id, project_id=project_id)
        spec = session.get(ProjectSpecificatie, (project_id, administratie_id))
        if spec is None:
            spec = ProjectSpecificatie(
                project_id=project_id, administratie_id=administratie_id, bijgewerkt_door=actor_id
            )
            session.add(spec)
        nieuwe = {
            "opdrachtgever": opdrachtgever,
            "werknummer_opdrachtgever": werknummer_opdrachtgever,
            "soort_werk": soort_werk,
            "contract_m2": str(contract_m2) if contract_m2 is not None else None,
            "looptijd_van": looptijd_van.isoformat() if looptijd_van else None,
            "looptijd_tot": looptijd_tot.isoformat() if looptijd_tot else None,
            "huurtijd_omschrijving": huurtijd_omschrijving,
            "doorlopende_huur_omschrijving": doorlopende_huur_omschrijving,
        }
        spec.opdrachtgever = opdrachtgever
        spec.werknummer_opdrachtgever = werknummer_opdrachtgever
        spec.soort_werk = soort_werk
        spec.contract_m2 = contract_m2
        spec.looptijd_van = looptijd_van
        spec.looptijd_tot = looptijd_tot
        spec.huurtijd_omschrijving = huurtijd_omschrijving
        spec.doorlopende_huur_omschrijving = doorlopende_huur_omschrijving
        spec.bijgewerkt_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_specificatie",
            record_id=project_id,
            actie="project_specificatie_bijgewerkt",
            correlatie_id=project_id,
            nieuwe_waarde=nieuwe,
            administratie_id=administratie_id,
        )


def voeg_staffel_toe(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    omschrijving: str,
    eenheid: str,
    prijs_per_eenheid: Decimal,
    verrekenbaar: bool = True,
    bron: str | None = None,
) -> uuid.UUID:
    if not omschrijving.strip():
        raise OngeldigeInvoer("Omschrijving is verplicht")
    if eenheid not in _EENHEDEN:
        raise OngeldigeInvoer(f"Eenheid moet één van {', '.join(_EENHEDEN)} zijn")
    if prijs_per_eenheid < 0:
        raise OngeldigeInvoer("Prijs kan niet negatief zijn")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        _vereis_project(session, administratie_id=administratie_id, project_id=project_id)
        staffel = ProjectStaffel(
            administratie_id=administratie_id,
            project_id=project_id,
            omschrijving=omschrijving.strip(),
            eenheid=eenheid,
            prijs_per_eenheid=prijs_per_eenheid,
            verrekenbaar=verrekenbaar,
            bron=bron,
            aangemaakt_door=actor_id,
        )
        session.add(staffel)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_staffel",
            record_id=staffel.id,
            actie="project_staffel_toegevoegd",
            correlatie_id=project_id,
            nieuwe_waarde={
                "omschrijving": staffel.omschrijving,
                "eenheid": eenheid,
                "prijs_per_eenheid": str(prijs_per_eenheid),
                "verrekenbaar": verrekenbaar,
                "bron": bron,
            },
            administratie_id=administratie_id,
        )
        return staffel.id


def wijzig_staffel(
    *,
    administratie_id: uuid.UUID,
    staffel_id: uuid.UUID,
    actor_id: uuid.UUID,
    omschrijving: str,
    eenheid: str,
    prijs_per_eenheid: Decimal,
    verrekenbaar: bool,
    bron: str | None = None,
) -> None:
    if eenheid not in _EENHEDEN:
        raise OngeldigeInvoer(f"Eenheid moet één van {', '.join(_EENHEDEN)} zijn")
    if prijs_per_eenheid < 0:
        raise OngeldigeInvoer("Prijs kan niet negatief zijn")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        staffel = session.get(ProjectStaffel, staffel_id)
        if staffel is None or staffel.administratie_id != administratie_id:
            raise ProjectNietGevonden("Onbekende staffelregel")
        oude = {
            "omschrijving": staffel.omschrijving,
            "eenheid": staffel.eenheid,
            "prijs_per_eenheid": str(staffel.prijs_per_eenheid),
            "verrekenbaar": staffel.verrekenbaar,
        }
        staffel.omschrijving = omschrijving.strip() or staffel.omschrijving
        staffel.eenheid = eenheid
        staffel.prijs_per_eenheid = prijs_per_eenheid
        staffel.verrekenbaar = verrekenbaar
        if bron is not None:
            staffel.bron = bron
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_staffel",
            record_id=staffel_id,
            actie="project_staffel_gewijzigd",
            correlatie_id=staffel.project_id,
            oude_waarde=oude,
            nieuwe_waarde={
                "omschrijving": staffel.omschrijving,
                "eenheid": eenheid,
                "prijs_per_eenheid": str(prijs_per_eenheid),
                "verrekenbaar": verrekenbaar,
            },
            administratie_id=administratie_id,
        )


def upload_project_document(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    soort: str,
    titel: str,
    bestandsnaam: str,
    inhoud: bytes,
    versie_omschrijving: str | None = None,
) -> uuid.UUID:
    """Contract-/offerte-upload (patroon meld_meerwerk-foto: standaard_opslag + rij). Vervangen
    = nieuwe rij; nooit verwijderen (geen DELETE-grant op project_document)."""
    if soort not in _DOCUMENT_SOORTEN:
        raise OngeldigeInvoer("Soort moet 'contract' of 'offerte' zijn")
    if not inhoud:
        raise OngeldigeInvoer("Leeg bestand")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        _vereis_project(session, administratie_id=administratie_id, project_id=project_id)
        document = ProjectDocument(
            administratie_id=administratie_id,
            project_id=project_id,
            soort=soort,
            titel=titel.strip() or bestandsnaam,
            versie_omschrijving=versie_omschrijving,
            opslag_pad="",  # gevuld ná flush (pad draagt het id)
            bestandsnaam=bestandsnaam,
            geupload_door=actor_id,
        )
        session.add(document)
        session.flush()
        pad = f"projectdocument/{administratie_id}/{project_id}/{document.id}/{bestandsnaam}"
        standaard_opslag().opslaan(pad=pad, inhoud=inhoud)
        document.opslag_pad = pad
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_document",
            record_id=document.id,
            actie="project_document_geupload",
            correlatie_id=project_id,
            nieuwe_waarde={"soort": soort, "titel": document.titel, "bestandsnaam": bestandsnaam},
            administratie_id=administratie_id,
        )
        return document.id


def voeg_werknummer_toe(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    vendor_id: uuid.UUID,
    werknummer: str,
    bron: str = "handmatig",
    bevestigd: bool = True,
) -> uuid.UUID:
    """Leverancier-werknummer ↔ project-mapping (praktijkles: eerste keer bevestigen, daarna
    automatisch). Handmatige invoer is meteen bevestigd; een voorstel-rij (bron 'factuur',
    t.z.t. door het leren uit facturen) wacht op bevestig_werknummer."""
    schoon = " ".join(werknummer.split())
    if not schoon:
        raise OngeldigeInvoer("Werknummer is verplicht")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        _vereis_project(session, administratie_id=administratie_id, project_id=project_id)
        bestaand = session.scalars(
            select(LeverancierWerknummer).where(
                LeverancierWerknummer.administratie_id == administratie_id,
                LeverancierWerknummer.vendor_id == vendor_id,
                LeverancierWerknummer.werknummer == schoon,
            )
        ).one_or_none()
        if bestaand is not None:
            raise OngeldigeInvoer("Deze leverancier heeft dit werknummer al gekoppeld")
        rij = LeverancierWerknummer(
            administratie_id=administratie_id,
            project_id=project_id,
            vendor_id=vendor_id,
            werknummer=schoon,
            bron=bron,
            bevestigd=bevestigd,
            aangemaakt_door=actor_id,
            bevestigd_door=actor_id if bevestigd else None,
            bevestigd_op=datetime.now(UTC) if bevestigd else None,
        )
        session.add(rij)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_werknummer",
            record_id=rij.id,
            actie="werknummer_gekoppeld",
            correlatie_id=project_id,
            nieuwe_waarde={"vendor_id": str(vendor_id), "werknummer": schoon, "bron": bron, "bevestigd": bevestigd},
            administratie_id=administratie_id,
        )
        return rij.id


def bevestig_werknummer(*, administratie_id: uuid.UUID, werknummer_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        rij = session.get(LeverancierWerknummer, werknummer_id)
        if rij is None or rij.administratie_id != administratie_id:
            raise ProjectNietGevonden("Onbekende werknummer-koppeling")
        if rij.bevestigd:
            return
        rij.bevestigd = True
        rij.bevestigd_door = actor_id
        rij.bevestigd_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_werknummer",
            record_id=werknummer_id,
            actie="werknummer_bevestigd",
            correlatie_id=rij.project_id,
            nieuwe_waarde={"vendor_id": str(rij.vendor_id), "werknummer": rij.werknummer},
            administratie_id=administratie_id,
        )


# --- nieuw project (via de bestaande RLZ-projectmotor-bouwstenen) --------------------------------


@dataclass(frozen=True)
class NieuwProjectResultaat:
    rlz_project_id: uuid.UUID
    projectnaam: str
    bestond_al: bool


def volgende_projectnummer(*, administratie_id: uuid.UUID, vandaag: date | None = None) -> str:
    """Voorstel voor het volgende vrije nummer in de Universal-naamconventie "26xxx …": het
    hoogste bestaande nummer met de jaar-prefix + 1, anders {jj}001. Puur een voorstel —
    de mens kan overschrijven."""
    vandaag = vandaag or date.today()
    prefix = f"{vandaag.year % 100:02d}"
    hoogste = 0
    with scoped_session(administratie_id) as session:
        for naam in session.scalars(
            select(ProjectCache.naam).where(
                ProjectCache.administratie_id == administratie_id,
                ProjectCache.verdwenen_uit_bron_op.is_(None),
            )
        ):
            if not naam:
                continue
            match = _NUMMER_PATROON.match(naam.strip())
            if match and match.group(1).startswith(prefix):
                hoogste = max(hoogste, int(match.group(1)))
    if hoogste == 0:
        return f"{prefix}001"
    return str(hoogste + 1)


def maak_project_aan(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    projectnummer: str,
    plaats: str,
    opdrachtgever: str,
    startdatum: date | None = None,
    client: RlzClient | None = None,
) -> NieuwProjectResultaat:
    """Nieuw project conform de klant-naamconventie ("26127 Tilburg (Heijmans)") via exact de
    bestaande motor-bouwstenen (app/projecten/motor.py — géén tweede motor): 50-tekens-poort,
    lookup-vóór-PUT (RLZ-naam wint), naamgenoot-conflict, klant-loze top-level PUT mét
    IsActive true, terugleesverificatie, project_cache-upsert, audit. De opdrachtgever landt
    meteen in de projectspecificatie (voedt de lijst-badges en de uitvoerder-app)."""
    nummer = " ".join(projectnummer.split())
    if not nummer or not nummer.isdigit():
        raise OngeldigeInvoer("Projectnummer is verplicht (alleen cijfers, bv. 26127)")
    if not plaats.strip() or not opdrachtgever.strip():
        raise OngeldigeInvoer("Plaats en opdrachtgever zijn verplicht")
    try:
        naam = vorm_projectnaam(f"{nummer} {plaats.strip()} ({opdrachtgever.strip()})")
    except OngeldigeProjectnaam as exc:
        raise OngeldigeInvoer(str(exc)) from exc

    with scoped_session(administratie_id) as session:
        _vereis_schrijfrol(session, actor_id)

    project_id = rlz_steiger_project_id(administratie_id, nummer)
    eigen_client = client is None
    if client is None:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    try:
        try:
            bestaand = client.get_project(project_id)
        except RlzApiError as exc:
            raise ProjectAanmakenMislukt(f"RLZ-lookup mislukt ({exc.status_code}) — niets aangemaakt") from exc
        if bestaand is not None:
            # PUT is create-or-update: nooit een herhaal-PUT op een bestaand project (zou de
            # RLZ-staat muteren) — cache verversen, RLZ-naam wint (motor-patroon).
            with scoped_session(administratie_id, actor_id=actor_id) as session:
                _upsert_project_cache(administratie_id=administratie_id, project_id=project_id, record=bestaand)
            resultaat = NieuwProjectResultaat(
                rlz_project_id=project_id, projectnaam=bestaand.get("Name") or naam, bestond_al=True
            )
        else:
            naamgenoten = client.find_projects_by_name(name=naam)
            if any(_als_uuid_veilig(p.get("id")) != project_id for p in naamgenoten):
                raise ProjectNaamConflict(naam, _als_uuid_veilig(naamgenoten[0].get("id")) or project_id)
            client.put_project(project_id, name=naam, is_active=True)
            record = client.get_project(project_id)
            if record is None:
                raise ProjectAanmakenMislukt("RLZ bevestigde de aanmaak niet (teruglezen gaf niets)")
            _upsert_project_cache(administratie_id=administratie_id, project_id=project_id, record=record)
            resultaat = NieuwProjectResultaat(
                rlz_project_id=project_id, projectnaam=record.get("Name") or naam, bestond_al=False
            )
    finally:
        if eigen_client:
            client.close()

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        spec = session.get(ProjectSpecificatie, (project_id, administratie_id))
        if spec is None:
            session.add(
                ProjectSpecificatie(
                    project_id=project_id,
                    administratie_id=administratie_id,
                    opdrachtgever=opdrachtgever.strip(),
                    looptijd_van=startdatum,
                    bijgewerkt_door=actor_id,
                )
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_cache",
            record_id=project_id,
            actie="project_aangemaakt_in_rlz" if not resultaat.bestond_al else "project_bestond_al",
            correlatie_id=project_id,
            nieuwe_waarde={"naam": resultaat.projectnaam, "nummer": nummer, "bron": "projectenmodule"},
            administratie_id=administratie_id,
        )
    return resultaat


def _als_uuid_veilig(waarde: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(waarde))
    except (ValueError, TypeError):
        return None


# --- prijsafspraken per veldwerker (steigerbouw-run B1, migratie 0073) -----------------------------

_PRIJSAFSPRAAK_EENHEDEN = ("uur", "m2")


def _venster(vanaf: tuple[int, int] | None, tm: tuple[int, int] | None) -> None:
    for w in (vanaf, tm):
        if w is not None and not (1 <= w[1] <= 53):
            raise OngeldigeInvoer("Weeknummer moet tussen 1 en 53 liggen")
    if vanaf is not None and tm is not None and vanaf > tm:
        raise OngeldigeInvoer("De vanaf-week ligt ná de t/m-week")


def _overlapt(a: ProjectPrijsafspraak, vanaf: tuple[int, int] | None, tm: tuple[int, int] | None) -> bool:
    a_vanaf = (a.geldig_vanaf_jaar, a.geldig_vanaf_week) if a.geldig_vanaf_jaar is not None else None
    a_tm = (a.geldig_tm_jaar, a.geldig_tm_week) if a.geldig_tm_jaar is not None else None
    start = max(x for x in (a_vanaf, vanaf) if x is not None) if (a_vanaf or vanaf) else None
    eind = min(x for x in (a_tm, tm) if x is not None) if (a_tm or tm) else None
    return start is None or eind is None or start <= eind


def voeg_prijsafspraak_toe(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    eenheid: str,
    tarief: Decimal,
    geldig_vanaf: tuple[int, int] | None = None,
    geldig_tm: tuple[int, int] | None = None,
    toelichting: str | None = None,
) -> uuid.UUID:
    """Projectafspraak (B1): per (project × ZZP'er) tarief + eenheid + ISO-week-venster; overlap met
    een actieve afspraak voor dezelfde combinatie = zichtbare fout (de resolutie moet eenduidig
    zijn — nooit gokken). Schrijven = Beheerder + Boekhouding+Projecten, geaudit."""
    if eenheid not in _PRIJSAFSPRAAK_EENHEDEN:
        raise OngeldigeInvoer("Eenheid moet 'uur' of 'm2' zijn")
    if tarief < 0:
        raise OngeldigeInvoer("Tarief kan niet negatief zijn")
    _venster(geldig_vanaf, geldig_tm)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        _vereis_project(session, administratie_id=administratie_id, project_id=project_id)
        veldwerker = session.get(Gebruiker, gebruiker_id)
        if veldwerker is None or veldwerker.rol != GebruikerRol.ZZPER:
            raise OngeldigeInvoer("Een prijsafspraak hoort bij een ZZP'er (ook als die via een bureau factureert)")
        actieve = session.scalars(
            select(ProjectPrijsafspraak).where(
                ProjectPrijsafspraak.administratie_id == administratie_id,
                ProjectPrijsafspraak.project_id == project_id,
                ProjectPrijsafspraak.gebruiker_id == gebruiker_id,
                ProjectPrijsafspraak.ingetrokken_op.is_(None),
            )
        ).all()
        for a in actieve:
            if _overlapt(a, geldig_vanaf, geldig_tm):
                raise OngeldigeInvoer(
                    "Er bestaat al een actieve prijsafspraak voor deze veldwerker in (een deel van) dit venster — "
                    "trek die eerst in"
                )
        afspraak = ProjectPrijsafspraak(
            administratie_id=administratie_id,
            project_id=project_id,
            gebruiker_id=gebruiker_id,
            eenheid=eenheid,
            tarief=tarief,
            geldig_vanaf_jaar=geldig_vanaf[0] if geldig_vanaf else None,
            geldig_vanaf_week=geldig_vanaf[1] if geldig_vanaf else None,
            geldig_tm_jaar=geldig_tm[0] if geldig_tm else None,
            geldig_tm_week=geldig_tm[1] if geldig_tm else None,
            toelichting=(toelichting or "").strip() or None,
            aangemaakt_door=actor_id,
        )
        session.add(afspraak)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_prijsafspraak",
            record_id=afspraak.id,
            actie="project_prijsafspraak_toegevoegd",
            correlatie_id=project_id,
            nieuwe_waarde={
                "gebruiker_id": str(gebruiker_id),
                "eenheid": eenheid,
                "tarief": str(tarief),
                "geldig_vanaf": list(geldig_vanaf) if geldig_vanaf else None,
                "geldig_tm": list(geldig_tm) if geldig_tm else None,
                "toelichting": afspraak.toelichting,
            },
            administratie_id=administratie_id,
        )
        return afspraak.id


def trek_prijsafspraak_in(
    *, administratie_id: uuid.UUID, afspraak_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> None:
    """Append-only: intrekken mét verplichte reden (wijzigen = intrekken + nieuwe afspraak).
    Lopende matches herberekenen op de eerstvolgende trigger — de audit toont oud→nieuw."""
    reden = (reden or "").strip()
    if not reden:
        raise OngeldigeInvoer("Intrekken vereist een reden")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        a = session.get(ProjectPrijsafspraak, afspraak_id)
        if a is None or a.administratie_id != administratie_id:
            raise ProjectNietGevonden("Onbekende prijsafspraak")
        if a.ingetrokken_op is not None:
            return  # idempotent
        a.ingetrokken_op = datetime.now(UTC)
        a.ingetrokken_door = actor_id
        a.ingetrokken_reden = reden
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_prijsafspraak",
            record_id=afspraak_id,
            actie="project_prijsafspraak_ingetrokken",
            correlatie_id=a.project_id,
            oude_waarde={"actief": True, "eenheid": a.eenheid, "tarief": str(a.tarief)},
            nieuwe_waarde={"actief": False, "reden": reden},
            administratie_id=administratie_id,
        )
