"""Uren & meerwerk — geldlogica/statusmachine (BOUW GO Peter 2026-08-21, migratie 0056).

Weekstaat-statusmachine (KEURING OP WEEKNIVEAU, besluit 21-08; HYBRIDE sinds besluit 22-08 —
afkeuren kan per dagregel een correctievoorstel meegeven, zie keur_week_af):

    concept ──(week indienen)──> ingediend ──(week akkoord)──> goedgekeurd
       ▲                            │  ▲                            │
       │                (week afkeuren, reden verplicht)   (nieuwe afkeuring,
       │                            ▼  │                    reden verplicht)
       └──(dagen muteerbaar)── corrigeren <────────────────────────┘

- Dagen (uren + optionele m² + opmerking) zijn uitsluitend muteerbaar in concept/corrigeren;
  ingediend is bevroren (de uitvoerder keurt geen bewegend doel), goedgekeurd is de GETEKENDE
  urenstaat en onmuteerbaar — wijzigen kan alleen doordat de uitvoerder opnieuw afkeurt.
- Een week zonder dagregels mag ingediend worden (mockup: "laat leeg en dien in — telt als
  0 uur op dit project"). De indien-deadline (ma 09:00) is een zichtbare afspraak in de app,
  bewust GEEN harde blokkade — te late uren moeten het systeem in kunnen, nooit erbuiten.
- Idempotentie: het herhalen van een al-verwerkt besluit (indienen op ingediend, akkoord op
  goedgekeurd, afkeuren op corrigeren) geeft de huidige stand terug i.p.v. een fout — zelfde
  patroon als accordering._herhaald_besluit (verzendrij/dubbeltik-vangnet in de app).
- Detacheerder (besluit 21-08): mag dagen zetten en indienen NAMENS een gekoppelde ZZP'er
  (platform.detacheerder_koppeling); elke invoer draagt de werkelijke invuller
  (`ingevuld_door`/`ingediend_door`) — "ingevuld door X namens Y" in audit én keurscherm.

Meerwerk-statusmachine: gemeld → goedgekeurd (prijs door een MENS bevestigd — de
contract-toets uit project_staffel is alleen een voorstel) → doorbelast (verkoopfactuur-
referentie verplicht) / gemeld → afgewezen (eigen rekening, reden verplicht). Niets
verdwijnt stil: afgewezen blijft zichtbaar, het 2-weken-bewakingssignaal telt goedgekeurd
meerwerk dat te lang niet op een verkoopfactuur staat.

Alle functies dwingen zelf af: opt-in per administratie (uren_meerwerk_ingeschakeld),
rol + koppeling (ZZP'er/detacheerder ↔ project resp. uitvoerder-keurrecht) en kantoor-rol +
module-recht "meerwerk_urenstaten" voor de beoordeel-acties — nooit alleen in de router."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.auth.rollen import is_kantoorrol
from app.db.audit import record_audit_event
from app.db.models import (
    Administratie,
    DetacheerderKoppeling,
    Gebruiker,
    GebruikerModuleRol,
    GebruikerRol,
)
from app.db.session import scoped_session
from app.sync.models import ProjectCache
from app.uren.models import (
    Meerwerk,
    MeerwerkEenheid,
    MeerwerkStatus,
    ProjectStaffel,
    UrenProjectToewijzing,
    Weekstaat,
    WeekstaatCorrectie,
    WeekstaatDag,
    WeekstaatStatus,
)

logger = logging.getLogger(__name__)

MODULE = "boekhouding"
MEERWERK_URENSTATEN_RECHT = "meerwerk_urenstaten"
BEWAKING_DAGEN = 14  # 2-weken-signaal: goedgekeurd maar nog niet doorbelast


# --- fouten ---------------------------------------------------------------------------------


class UrenFout(Exception):
    """Basis voor domeinfouten in de uren-&-meerwerk-module."""


class ModuleUitgeschakeld(UrenFout):
    """De administratie heeft de opt-in uren_meerwerk_ingeschakeld niet aan."""


class GeenToegang(UrenFout):
    """Rol-/koppelingscheck faalde (geen toewijzing, geen keurrecht, geen namens-koppeling,
    geen kantoor-rol of geen module-recht)."""


class NietGevonden(UrenFout):
    pass


class OngeldigeInvoer(UrenFout):
    pass


class RedenVerplicht(UrenFout):
    pass


class WeekstaatBevroren(UrenFout):
    """Dagen muteren kan alleen in concept/corrigeren — ingediend/goedgekeurd is bevroren."""


class OngeldigeOvergang(UrenFout):
    pass


# --- data ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DagData:
    id: uuid.UUID
    datum: date
    uren: Decimal
    m2: Decimal | None
    opmerking: str | None
    ingevuld_door: uuid.UUID
    ingevuld_door_naam: str | None
    namens: bool  # ingevuld door iemand anders dan de ZZP'er zelf (detacheerder)
    # Correctievoorstel van de laatste afkeuring (hybride keuring, besluit 22-08) — de UI
    # toont ze alleen in status `corrigeren`.
    voorstel_uren: Decimal | None
    voorstel_m2: Decimal | None
    voorstel_opmerking: str | None


@dataclass(frozen=True)
class DagCorrectieInvoer:
    """Correctievoorstel van de keurder bij het afkeuren, per bestaande dagregel (besluit
    22-08): voorgestelde uren en/of m² + opmerking — minstens één veld gevuld."""

    datum: date
    uren: Decimal | None = None
    m2: Decimal | None = None
    opmerking: str | None = None


@dataclass(frozen=True)
class WeekstaatData:
    id: uuid.UUID
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    gebruiker_naam: str | None
    project_id: uuid.UUID
    project_naam: str | None
    jaar: int
    weeknummer: int
    status: str
    totaal_uren: Decimal
    totaal_m2: Decimal
    dagen: list[DagData]
    ingediend_op: datetime | None
    ingediend_door: uuid.UUID | None
    ingediend_door_naam: str | None
    ingediend_namens: bool
    goedgekeurd_op: datetime | None
    goedgekeurd_door_naam: str | None
    afgekeurd_op: datetime | None
    afgekeurd_door_naam: str | None
    afkeur_reden: str | None


@dataclass(frozen=True)
class MeerwerkData:
    id: uuid.UUID
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None
    omschrijving: str
    aantal: Decimal
    eenheid: str
    datum_uitgevoerd: date
    in_opdracht_van: str | None
    heeft_foto: bool
    foto_bestandsnaam: str | None
    gemeld_door: uuid.UUID
    gemeld_door_naam: str | None
    gemeld_op: datetime
    status: str
    prijs_per_eenheid: Decimal | None
    bedrag: Decimal | None
    facturatie_notitie: str | None
    beoordeeld_op: datetime | None
    beoordeeld_door_naam: str | None
    afwijs_reden: str | None
    doorbelast_op: datetime | None
    verkoopfactuur_referentie: str | None
    vraag_tekst: str | None
    vraag_gesteld_op: datetime | None
    vraag_antwoord: str | None
    vraag_beantwoord_op: datetime | None


@dataclass(frozen=True)
class StaffelRegelData:
    id: uuid.UUID
    omschrijving: str
    eenheid: str
    prijs_per_eenheid: Decimal
    verrekenbaar: bool
    bron: str | None


# --- helpers ---------------------------------------------------------------------------------


def week_grenzen(jaar: int, weeknummer: int) -> tuple[date, date]:
    """Maandag t/m zondag van een ISO-week; OngeldigeInvoer bij een niet-bestaande week."""
    try:
        maandag = date.fromisocalendar(jaar, weeknummer, 1)
    except ValueError as exc:
        raise OngeldigeInvoer(f"Week {weeknummer} bestaat niet in {jaar}") from exc
    return maandag, maandag + timedelta(days=6)


def _administratie_met_opt_in(session, administratie_id: uuid.UUID) -> Administratie:
    administratie = session.get(Administratie, administratie_id)
    if administratie is None:
        raise NietGevonden("Onbekende administratie")
    if not administratie.uren_meerwerk_ingeschakeld:
        raise ModuleUitgeschakeld("Uren & meerwerk is niet ingeschakeld voor deze administratie")
    return administratie


def _gebruiker(session, gebruiker_id: uuid.UUID) -> Gebruiker:
    gebruiker = session.get(Gebruiker, gebruiker_id)
    if gebruiker is None:
        raise NietGevonden("Onbekende gebruiker")
    return gebruiker


def _namen(session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    echte = {i for i in ids if i is not None}
    if not echte:
        return {}
    rijen = session.scalars(select(Gebruiker).where(Gebruiker.id.in_(echte))).all()
    return {g.id: g.naam for g in rijen}


def _project(session, administratie_id: uuid.UUID, project_id: uuid.UUID) -> ProjectCache:
    project = session.get(ProjectCache, (project_id, administratie_id))
    if project is None:
        raise NietGevonden("Onbekend project voor deze administratie")
    return project


def _heeft_toewijzing(session, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID, project_id: uuid.UUID) -> bool:
    return (
        session.get(UrenProjectToewijzing, (administratie_id, gebruiker_id, project_id)) is not None
    )


def _vereis_invuller(session, *, zzper: Gebruiker, actor_id: uuid.UUID) -> Gebruiker:
    """De actor mag de weekstaat van `zzper` bewerken/indienen: de ZZP'er zelf, of een
    detacheerder die door het kantoor aan deze ZZP'er gekoppeld is (besluit 21-08)."""
    if zzper.rol != GebruikerRol.ZZPER:
        raise OngeldigeInvoer("Weekstaten horen bij een gebruiker met de rol ZZP'er")
    if actor_id == zzper.id:
        return zzper
    actor = _gebruiker(session, actor_id)
    if actor.rol != GebruikerRol.DETACHEERDER:
        raise GeenToegang("Alleen de ZZP'er zelf of een gekoppelde detacheerder mag dit")
    koppeling = session.get(DetacheerderKoppeling, (actor_id, zzper.id))
    if koppeling is None:
        raise GeenToegang("Deze detacheerder is niet aan deze ZZP'er gekoppeld")
    return actor


def _vereis_keurrecht(session, *, administratie_id: uuid.UUID, actor_id: uuid.UUID, project_id: uuid.UUID) -> Gebruiker:
    actor = _gebruiker(session, actor_id)
    if actor.rol != GebruikerRol.UITVOERDER:
        raise GeenToegang("Alleen een uitvoerder keurt weekstaten")
    if not _heeft_toewijzing(session, administratie_id, actor_id, project_id):
        raise GeenToegang("Deze uitvoerder is niet aan dit project gekoppeld")
    return actor


def heeft_meerwerk_urenstaten_recht(*, gebruiker_id: uuid.UUID, rol: GebruikerRol) -> bool:
    """Module-recht 'Meerwerk & urenstaten' (0019-patroon): Beheerder heeft het altijd, andere
    kantoor-rollen alleen met een gebruiker_module_rol-rij (module 'boekhouding'); externe
    app-rollen nooit — hun toegang loopt via koppelingen, niet via dit kantoor-recht."""
    if rol == GebruikerRol.BEHEERDER:
        return True
    if not is_kantoorrol(rol):
        return False
    with scoped_session(None, actor_id=gebruiker_id) as session:
        rij = session.get(GebruikerModuleRol, (gebruiker_id, MODULE))
        return rij is not None and rij.rol == MEERWERK_URENSTATEN_RECHT


def _vereis_meerwerk_recht(session, actor_id: uuid.UUID) -> Gebruiker:
    """Kantoor-beoordeelacties: kantoorrol + module-recht, in de service afgedwongen (niet
    alleen in de router). NB de module-recht-query loopt buiten deze sessie (eigen
    platform-scope) — bewust, de recht-tabel is platform-breed."""
    actor = _gebruiker(session, actor_id)
    if not heeft_meerwerk_urenstaten_recht(gebruiker_id=actor_id, rol=actor.rol):
        raise GeenToegang("Vereist het module-recht 'Meerwerk & urenstaten'")
    return actor


def _dag_data(dag: WeekstaatDag, *, zzper_id: uuid.UUID, namen: dict[uuid.UUID, str]) -> DagData:
    return DagData(
        id=dag.id,
        datum=dag.datum,
        uren=dag.uren,
        m2=dag.m2,
        opmerking=dag.opmerking,
        ingevuld_door=dag.ingevuld_door,
        ingevuld_door_naam=namen.get(dag.ingevuld_door),
        namens=dag.ingevuld_door != zzper_id,
        voorstel_uren=dag.voorstel_uren,
        voorstel_m2=dag.voorstel_m2,
        voorstel_opmerking=dag.voorstel_opmerking,
    )


def _weekstaat_data(session, staat: Weekstaat) -> WeekstaatData:
    dagen = list(
        session.scalars(
            select(WeekstaatDag).where(WeekstaatDag.weekstaat_id == staat.id).order_by(WeekstaatDag.datum)
        )
    )
    namen = _namen(
        session,
        {staat.gebruiker_id, staat.ingediend_door, staat.goedgekeurd_door, staat.afgekeurd_door}
        | {d.ingevuld_door for d in dagen},
    )
    project = session.get(ProjectCache, (staat.project_id, staat.administratie_id))
    return WeekstaatData(
        id=staat.id,
        administratie_id=staat.administratie_id,
        gebruiker_id=staat.gebruiker_id,
        gebruiker_naam=namen.get(staat.gebruiker_id),
        project_id=staat.project_id,
        project_naam=project.naam if project else None,
        jaar=staat.jaar,
        weeknummer=staat.weeknummer,
        status=staat.status,
        totaal_uren=sum((d.uren for d in dagen), Decimal("0")),
        totaal_m2=sum((d.m2 for d in dagen if d.m2 is not None), Decimal("0")),
        dagen=[_dag_data(d, zzper_id=staat.gebruiker_id, namen=namen) for d in dagen],
        ingediend_op=staat.ingediend_op,
        ingediend_door=staat.ingediend_door,
        ingediend_door_naam=namen.get(staat.ingediend_door) if staat.ingediend_door else None,
        ingediend_namens=staat.ingediend_door is not None and staat.ingediend_door != staat.gebruiker_id,
        goedgekeurd_op=staat.goedgekeurd_op,
        goedgekeurd_door_naam=namen.get(staat.goedgekeurd_door) if staat.goedgekeurd_door else None,
        afgekeurd_op=staat.afgekeurd_op,
        afgekeurd_door_naam=namen.get(staat.afgekeurd_door) if staat.afgekeurd_door else None,
        afkeur_reden=staat.afkeur_reden,
    )


def _haal_of_maak_weekstaat(
    session,
    *,
    administratie_id: uuid.UUID,
    zzper_id: uuid.UUID,
    project_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
) -> Weekstaat:
    week_grenzen(jaar, weeknummer)  # valideert dat de week bestaat
    staat = session.scalars(
        select(Weekstaat).where(
            Weekstaat.administratie_id == administratie_id,
            Weekstaat.gebruiker_id == zzper_id,
            Weekstaat.project_id == project_id,
            Weekstaat.jaar == jaar,
            Weekstaat.weeknummer == weeknummer,
        )
    ).one_or_none()
    if staat is None:
        staat = Weekstaat(
            administratie_id=administratie_id,
            gebruiker_id=zzper_id,
            project_id=project_id,
            jaar=jaar,
            weeknummer=weeknummer,
        )
        session.add(staat)
        session.flush()
    return staat


# --- weekstaat: invullen & indienen (ZZP'er / detacheerder namens) ---------------------------


def zet_dag(
    *,
    administratie_id: uuid.UUID,
    zzper_id: uuid.UUID,
    project_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
    datum: date,
    uren: Decimal,
    m2: Decimal | None = None,
    opmerking: str | None = None,
    actor_id: uuid.UUID,
) -> WeekstaatData:
    """Dagregel zetten/bijwerken (upsert op datum). Alleen in concept/corrigeren; de datum
    moet binnen de ISO-week vallen; uren 0–24, m² ≥ 0 (optioneel)."""
    if uren < 0 or uren > 24:
        raise OngeldigeInvoer("Uren moeten tussen 0 en 24 liggen")
    if m2 is not None and m2 < 0:
        raise OngeldigeInvoer("m² kan niet negatief zijn")
    maandag, zondag = week_grenzen(jaar, weeknummer)
    if not (maandag <= datum <= zondag):
        raise OngeldigeInvoer(f"Datum {datum} valt buiten week {weeknummer} van {jaar}")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _project(session, administratie_id, project_id)
        zzper = _gebruiker(session, zzper_id)
        _vereis_invuller(session, zzper=zzper, actor_id=actor_id)
        if not _heeft_toewijzing(session, administratie_id, zzper_id, project_id):
            raise GeenToegang("Deze ZZP'er is niet aan dit project gekoppeld")

        staat = _haal_of_maak_weekstaat(
            session,
            administratie_id=administratie_id,
            zzper_id=zzper_id,
            project_id=project_id,
            jaar=jaar,
            weeknummer=weeknummer,
        )
        if staat.status not in (WeekstaatStatus.CONCEPT.value, WeekstaatStatus.CORRIGEREN.value):
            raise WeekstaatBevroren(
                "Deze week is al ingediend of goedgekeurd — wijzigen kan alleen na een afkeuring"
            )

        dag = session.scalars(
            select(WeekstaatDag).where(WeekstaatDag.weekstaat_id == staat.id, WeekstaatDag.datum == datum)
        ).one_or_none()
        oude_waarde = None
        if dag is None:
            dag = WeekstaatDag(
                weekstaat_id=staat.id,
                administratie_id=administratie_id,
                datum=datum,
                uren=uren,
                m2=m2,
                opmerking=opmerking,
                ingevuld_door=actor_id,
            )
            session.add(dag)
            session.flush()
        else:
            oude_waarde = {"uren": str(dag.uren), "m2": str(dag.m2) if dag.m2 is not None else None}
            dag.uren = uren
            dag.m2 = m2
            dag.opmerking = opmerking
            dag.ingevuld_door = actor_id

        nieuwe_waarde = {
            "datum": datum.isoformat(),
            "uren": str(uren),
            "m2": str(m2) if m2 is not None else None,
            "ingevuld_door": str(actor_id),
        }
        if actor_id != zzper_id:
            nieuwe_waarde["namens_gebruiker_id"] = str(zzper_id)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="weekstaat_dag",
            record_id=dag.id,
            actie="weekstaat_dag_gezet",
            correlatie_id=staat.id,
            oude_waarde=oude_waarde,
            nieuwe_waarde=nieuwe_waarde,
            administratie_id=administratie_id,
        )
        return _weekstaat_data(session, staat)


def dien_week_in(
    *,
    administratie_id: uuid.UUID,
    zzper_id: uuid.UUID,
    project_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
    actor_id: uuid.UUID,
) -> WeekstaatData:
    """concept/corrigeren → ingediend. Een lege week mag (telt als 0 uur op dit project).
    Idempotent: opnieuw indienen op een al-ingediende week geeft de huidige stand terug."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _project(session, administratie_id, project_id)
        zzper = _gebruiker(session, zzper_id)
        _vereis_invuller(session, zzper=zzper, actor_id=actor_id)
        if not _heeft_toewijzing(session, administratie_id, zzper_id, project_id):
            raise GeenToegang("Deze ZZP'er is niet aan dit project gekoppeld")

        staat = _haal_of_maak_weekstaat(
            session,
            administratie_id=administratie_id,
            zzper_id=zzper_id,
            project_id=project_id,
            jaar=jaar,
            weeknummer=weeknummer,
        )
        if staat.status == WeekstaatStatus.INGEDIEND.value:
            return _weekstaat_data(session, staat)  # herhaald besluit — geen fout
        if staat.status == WeekstaatStatus.GOEDGEKEURD.value:
            raise OngeldigeOvergang("Deze week is al goedgekeurd (getekende urenstaat)")

        staat.status = WeekstaatStatus.INGEDIEND.value
        staat.ingediend_op = datetime.now(UTC)
        staat.ingediend_door = actor_id
        nieuwe_waarde = {"status": staat.status, "ingediend_door": str(actor_id)}
        if actor_id != zzper_id:
            nieuwe_waarde["namens_gebruiker_id"] = str(zzper_id)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="weekstaat",
            record_id=staat.id,
            actie="weekstaat_ingediend",
            correlatie_id=staat.id,
            nieuwe_waarde=nieuwe_waarde,
            administratie_id=administratie_id,
        )
        return _weekstaat_data(session, staat)


# --- weekstaat: keuren (uitvoerder, WEEKNIVEAU) -----------------------------------------------


def _weekstaat(session, weekstaat_id: uuid.UUID) -> Weekstaat:
    staat = session.get(Weekstaat, weekstaat_id)
    if staat is None:
        raise NietGevonden("Onbekende weekstaat")
    return staat


def keur_week_goed(*, administratie_id: uuid.UUID, weekstaat_id: uuid.UUID, actor_id: uuid.UUID) -> WeekstaatData:
    """ingediend → goedgekeurd (de getekende urenstaat). Alleen een uitvoerder met een
    toewijzing op het project; idempotent op een al-goedgekeurde week."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        staat = _weekstaat(session, weekstaat_id)
        _vereis_keurrecht(session, administratie_id=administratie_id, actor_id=actor_id, project_id=staat.project_id)
        if staat.status == WeekstaatStatus.GOEDGEKEURD.value:
            return _weekstaat_data(session, staat)  # herhaald besluit
        if staat.status != WeekstaatStatus.INGEDIEND.value:
            raise OngeldigeOvergang("Alleen een ingediende week kan goedgekeurd worden")

        staat.status = WeekstaatStatus.GOEDGEKEURD.value
        staat.goedgekeurd_op = datetime.now(UTC)
        staat.goedgekeurd_door = actor_id
        # Afwijkings-logging (besluit 22-08): vul op de nog open correctie-registraties van
        # deze staat het definitieve goedgekeurde totaal aan — dé toetsbron (factuurmatch-lijn).
        goedgekeurd_totaal = session.execute(
            select(func.coalesce(func.sum(WeekstaatDag.uren), 0)).where(WeekstaatDag.weekstaat_id == staat.id)
        ).scalar_one()
        open_correcties = session.scalars(
            select(WeekstaatCorrectie).where(
                WeekstaatCorrectie.weekstaat_id == staat.id,
                WeekstaatCorrectie.goedgekeurd_uren.is_(None),
            )
        ).all()
        for correctie in open_correcties:
            correctie.goedgekeurd_uren = goedgekeurd_totaal
            correctie.goedgekeurd_op = staat.goedgekeurd_op
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="weekstaat",
            record_id=staat.id,
            actie="weekstaat_goedgekeurd",
            correlatie_id=staat.id,
            nieuwe_waarde={"status": staat.status},
            administratie_id=administratie_id,
        )
        zzper_id = staat.gebruiker_id
        data = _weekstaat_data(session, staat)

    # Factuurmatch (fase 2): een nieuwe getekende staat kan een bestaande match laten
    # verschuiven (afwijking → match, of andersom) — post-commit herberekenen voor alle open
    # matches waarin deze ZZP'er meetelt (zelfde hook-vorm als _na_extractie_hook; een fout is
    # een gelogde waarschuwing, nooit een blokkade van de keuring).
    from app.uren import factuurmatch_pipeline  # lokaal: houdt de importgraaf klein

    try:
        factuurmatch_pipeline.herbereken_voor_veldwerker(administratie_id=administratie_id, gebruiker_id=zzper_id)
    except Exception:  # noqa: BLE001 — de match is signalering, nooit een blokkade
        logger.exception("Factuurmatch-herberekening na weekstaat-goedkeuring mislukt (staat %s)", weekstaat_id)

    return data


def keur_week_af(
    *,
    administratie_id: uuid.UUID,
    weekstaat_id: uuid.UUID,
    actor_id: uuid.UUID,
    reden: str,
    correcties: list[DagCorrectieInvoer] | None = None,
) -> WeekstaatData:
    """ingediend/goedgekeurd → corrigeren, reden VERPLICHT — de hele week gaat terug naar de
    ZZP'er (keuring op weekniveau, besluit 21-08). Afkeuren van een al-goedgekeurde week is de
    enige weg om een getekende urenstaat weer open te breken; de goedgekeurd-velden gaan dan
    leeg (de staat is niet langer getekend — de historie staat in audit_event).

    HYBRIDE (besluit 22-08): `correcties` = optionele correctievoorstellen per bestaande
    dagregel (voorgestelde uren en/of m² + opmerking). De keurder wijzigt nooit zelf de
    uren/m² van de ZZP'er — de voorstellen landen in de voorstel-velden, de ZZP'er ziet ze
    letterlijk in zijn corrigeer-scherm en dient zelf opnieuw in. Elke afkeuring mét
    voorstel wordt geregistreerd in weekstaat_correctie (afwijkings-logging, kantoor-only)."""
    reden = (reden or "").strip()
    if not reden:
        raise RedenVerplicht("Afkeuren vereist een reden — die gaat naar de ZZP'er")
    correcties = correcties or []
    for correctie in correcties:
        if correctie.uren is None and correctie.m2 is None and not (correctie.opmerking or "").strip():
            raise OngeldigeInvoer(f"Correctievoorstel voor {correctie.datum} is leeg")
        if correctie.uren is not None and not (0 <= correctie.uren <= 24):
            raise OngeldigeInvoer("Voorgestelde uren moeten tussen 0 en 24 liggen")
        if correctie.m2 is not None and correctie.m2 < 0:
            raise OngeldigeInvoer("Voorgestelde m² kan niet negatief zijn")
    if len({c.datum for c in correcties}) != len(correcties):
        raise OngeldigeInvoer("Meerdere correctievoorstellen voor dezelfde dag")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        staat = _weekstaat(session, weekstaat_id)
        _vereis_keurrecht(session, administratie_id=administratie_id, actor_id=actor_id, project_id=staat.project_id)
        if staat.status == WeekstaatStatus.CORRIGEREN.value and staat.afkeur_reden == reden:
            return _weekstaat_data(session, staat)  # herhaald besluit (dubbeltik/verzendrij)
        if staat.status not in (WeekstaatStatus.INGEDIEND.value, WeekstaatStatus.GOEDGEKEURD.value):
            raise OngeldigeOvergang("Alleen een ingediende of goedgekeurde week kan afgekeurd worden")
        # Factuurmatch (fase 2, dubbeltelling-preventie): een staat die al met een geboekte
        # factuur verrekend is, is boekhoudkundig afgehandeld — openbreken zou de match onder
        # de boeking uit trekken. Correctie loopt dan via storno van de factuur (die de
        # verrekening niet automatisch terugdraait — kantoorbeoordeling), nooit hierlangs.
        if staat.verrekend_met_document_id is not None:
            raise OngeldigeOvergang(
                "Deze week is al verrekend met een geboekte factuur — afkeuren kan niet meer"
            )

        # Correctievoorstellen horen bij bestaande dagregels (per dagregel, besluit 22-08).
        dagen = list(session.scalars(select(WeekstaatDag).where(WeekstaatDag.weekstaat_id == staat.id)))
        dag_per_datum = {d.datum: d for d in dagen}
        for correctie in correcties:
            if correctie.datum not in dag_per_datum:
                raise OngeldigeInvoer(
                    f"Geen ingevulde dagregel op {correctie.datum} — een voorstel hoort bij een dag"
                )

        oude_status = staat.status
        staat.status = WeekstaatStatus.CORRIGEREN.value
        staat.afgekeurd_op = datetime.now(UTC)
        staat.afgekeurd_door = actor_id
        staat.afkeur_reden = reden
        staat.goedgekeurd_op = None
        staat.goedgekeurd_door = None

        # Voorstellen van de LAATSTE afkeuring zijn leidend: eerst alles leeg, dan de nieuwe
        # set zetten — een stale voorstel van een eerdere ronde blijft nooit hangen.
        for dag in dagen:
            dag.voorstel_uren = None
            dag.voorstel_m2 = None
            dag.voorstel_opmerking = None
        correcties_audit: list[dict] = []
        for correctie in correcties:
            dag = dag_per_datum[correctie.datum]
            dag.voorstel_uren = correctie.uren
            dag.voorstel_m2 = correctie.m2
            dag.voorstel_opmerking = (correctie.opmerking or "").strip() or None
            correcties_audit.append(
                {
                    "datum": correctie.datum.isoformat(),
                    "ingediend_uren": str(dag.uren),
                    "ingediend_m2": str(dag.m2) if dag.m2 is not None else None,
                    "voorstel_uren": str(correctie.uren) if correctie.uren is not None else None,
                    "voorstel_m2": str(correctie.m2) if correctie.m2 is not None else None,
                    "voorstel_opmerking": dag.voorstel_opmerking,
                }
            )

        # Afwijkings-logging (besluit 22-08): alleen bij een afkeuring MÉT voorstel valt er
        # een delta te meten — ingediend totaal vs. het totaal mét voorstellen toegepast.
        if correcties:
            ingediend_totaal = sum((d.uren for d in dagen), Decimal("0"))
            voorstel_per_datum = {c.datum: c.uren for c in correcties}
            voorgesteld_totaal = sum(
                (voorstel_per_datum.get(d.datum) if voorstel_per_datum.get(d.datum) is not None else d.uren
                 for d in dagen),
                Decimal("0"),
            )
            session.add(
                WeekstaatCorrectie(
                    administratie_id=administratie_id,
                    weekstaat_id=staat.id,
                    zzper_gebruiker_id=staat.gebruiker_id,
                    afgekeurd_door=actor_id,
                    afgekeurd_op=staat.afgekeurd_op,
                    ingediend_uren=ingediend_totaal,
                    voorgesteld_uren=voorgesteld_totaal,
                    delta_uren=ingediend_totaal - voorgesteld_totaal,
                    details={"dagen": correcties_audit},
                )
            )

        nieuwe_waarde: dict = {"status": staat.status, "reden": reden}
        if correcties_audit:
            nieuwe_waarde["correctievoorstellen"] = correcties_audit
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="weekstaat",
            record_id=staat.id,
            actie="weekstaat_afgekeurd",
            correlatie_id=staat.id,
            oude_waarde={"status": oude_status},
            nieuwe_waarde=nieuwe_waarde,
            administratie_id=administratie_id,
        )
        return _weekstaat_data(session, staat)


def weekstaat_detail(*, administratie_id: uuid.UUID, weekstaat_id: uuid.UUID) -> WeekstaatData:
    with scoped_session(administratie_id) as session:
        return _weekstaat_data(session, _weekstaat(session, weekstaat_id))


# --- meerwerk: melden (uitvoerder) ------------------------------------------------------------


def _meerwerk_data(session, m: Meerwerk) -> MeerwerkData:
    namen = _namen(session, {m.gemeld_door, m.beoordeeld_door})
    project = session.get(ProjectCache, (m.project_id, m.administratie_id))
    return MeerwerkData(
        id=m.id,
        administratie_id=m.administratie_id,
        project_id=m.project_id,
        project_naam=project.naam if project else None,
        omschrijving=m.omschrijving,
        aantal=m.aantal,
        eenheid=m.eenheid,
        datum_uitgevoerd=m.datum_uitgevoerd,
        in_opdracht_van=m.in_opdracht_van,
        heeft_foto=m.foto_opslag_pad is not None,
        foto_bestandsnaam=m.foto_bestandsnaam,
        gemeld_door=m.gemeld_door,
        gemeld_door_naam=namen.get(m.gemeld_door),
        gemeld_op=m.gemeld_op,
        status=m.status,
        prijs_per_eenheid=m.prijs_per_eenheid,
        bedrag=m.bedrag,
        facturatie_notitie=m.facturatie_notitie,
        beoordeeld_op=m.beoordeeld_op,
        beoordeeld_door_naam=namen.get(m.beoordeeld_door) if m.beoordeeld_door else None,
        afwijs_reden=m.afwijs_reden,
        doorbelast_op=m.doorbelast_op,
        verkoopfactuur_referentie=m.verkoopfactuur_referentie,
        vraag_tekst=m.vraag_tekst,
        vraag_gesteld_op=m.vraag_gesteld_op,
        vraag_antwoord=m.vraag_antwoord,
        vraag_beantwoord_op=m.vraag_beantwoord_op,
    )


def meld_meerwerk(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    omschrijving: str,
    aantal: Decimal,
    eenheid: str,
    datum_uitgevoerd: date,
    in_opdracht_van: str | None = None,
    foto: tuple[str, str, bytes] | None = None,
) -> MeerwerkData:
    """Melding door een uitvoerder met toewijzing op het project — zonder prijzen (de
    kantoorkant prijst). `foto` = (bestandsnaam, content_type, inhoud), opgeslagen via de
    DocumentOpslag-interface (zelfde als document-PDF's)."""
    omschrijving = (omschrijving or "").strip()
    if not omschrijving:
        raise OngeldigeInvoer("Omschrijving is verplicht — beschrijf het meerwerk voluit")
    if aantal <= 0:
        raise OngeldigeInvoer("Aantal moet groter dan 0 zijn")
    if eenheid not in {e.value for e in MeerwerkEenheid}:
        raise OngeldigeInvoer(f"Onbekende eenheid: {eenheid!r}")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _project(session, administratie_id, project_id)
        actor = _gebruiker(session, actor_id)
        if actor.rol != GebruikerRol.UITVOERDER:
            raise GeenToegang("Alleen een uitvoerder meldt meerwerk")
        if not _heeft_toewijzing(session, administratie_id, actor_id, project_id):
            raise GeenToegang("Deze uitvoerder is niet aan dit project gekoppeld")

        melding = Meerwerk(
            administratie_id=administratie_id,
            project_id=project_id,
            omschrijving=omschrijving,
            aantal=aantal,
            eenheid=eenheid,
            datum_uitgevoerd=datum_uitgevoerd,
            in_opdracht_van=(in_opdracht_van or "").strip() or None,
            gemeld_door=actor_id,
        )
        session.add(melding)
        session.flush()

        if foto is not None:
            from app.documenten.storage import standaard_opslag

            bestandsnaam, content_type, inhoud = foto
            if not inhoud:
                raise OngeldigeInvoer("Lege foto")
            pad = f"meerwerk/{administratie_id}/{melding.id}/{bestandsnaam}"
            standaard_opslag().opslaan(pad=pad, inhoud=inhoud)
            melding.foto_opslag_pad = pad
            melding.foto_bestandsnaam = bestandsnaam
            melding.foto_content_type = content_type

        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="meerwerk",
            record_id=melding.id,
            actie="meerwerk_gemeld",
            correlatie_id=melding.id,
            nieuwe_waarde={
                "project_id": str(project_id),
                "omschrijving": omschrijving,
                "aantal": str(aantal),
                "eenheid": eenheid,
            },
            administratie_id=administratie_id,
        )
        return _meerwerk_data(session, melding)


# --- meerwerk: beoordelen (kantoor, module-recht) ---------------------------------------------


def _meerwerk(session, meerwerk_id: uuid.UUID) -> Meerwerk:
    melding = session.get(Meerwerk, meerwerk_id)
    if melding is None:
        raise NietGevonden("Onbekende meerwerkmelding")
    return melding


def keur_meerwerk_goed(
    *,
    administratie_id: uuid.UUID,
    meerwerk_id: uuid.UUID,
    actor_id: uuid.UUID,
    prijs_per_eenheid: Decimal,
    bedrag: Decimal,
    facturatie_notitie: str | None = None,
) -> MeerwerkData:
    """gemeld → goedgekeurd (nog doorbelasten). De MENS bevestigt prijs én bedrag — de
    contract-toets (staffel) is alleen een voorstel; de app rekent nooit zelf door naar een
    boeking. Vanaf hier bewaakt het 2-weken-signaal tot het item op een verkoopfactuur staat."""
    if prijs_per_eenheid < 0 or bedrag < 0:
        raise OngeldigeInvoer("Prijs en bedrag kunnen niet negatief zijn")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        melding = _meerwerk(session, meerwerk_id)
        if melding.status == MeerwerkStatus.GOEDGEKEURD.value:
            return _meerwerk_data(session, melding)  # herhaald besluit
        if melding.status != MeerwerkStatus.GEMELD.value:
            raise OngeldigeOvergang("Alleen een gemelde melding kan goedgekeurd worden")

        melding.status = MeerwerkStatus.GOEDGEKEURD.value
        melding.prijs_per_eenheid = prijs_per_eenheid
        melding.bedrag = bedrag
        melding.facturatie_notitie = (facturatie_notitie or "").strip() or None
        melding.beoordeeld_door = actor_id
        melding.beoordeeld_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="meerwerk",
            record_id=melding.id,
            actie="meerwerk_goedgekeurd",
            correlatie_id=melding.id,
            nieuwe_waarde={
                "status": melding.status,
                "prijs_per_eenheid": str(prijs_per_eenheid),
                "bedrag": str(bedrag),
            },
            administratie_id=administratie_id,
        )
        return _meerwerk_data(session, melding)


def wijs_meerwerk_af(
    *, administratie_id: uuid.UUID, meerwerk_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> MeerwerkData:
    """gemeld → afgewezen (eigen rekening) — reden VERPLICHT, blijft zichtbaar in de lijst."""
    reden = (reden or "").strip()
    if not reden:
        raise RedenVerplicht("Afwijzen vereist een verplichte reden")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        melding = _meerwerk(session, meerwerk_id)
        if melding.status == MeerwerkStatus.AFGEWEZEN.value and melding.afwijs_reden == reden:
            return _meerwerk_data(session, melding)  # herhaald besluit
        if melding.status != MeerwerkStatus.GEMELD.value:
            raise OngeldigeOvergang("Alleen een gemelde melding kan afgewezen worden")

        melding.status = MeerwerkStatus.AFGEWEZEN.value
        melding.afwijs_reden = reden
        melding.beoordeeld_door = actor_id
        melding.beoordeeld_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="meerwerk",
            record_id=melding.id,
            actie="meerwerk_afgewezen",
            correlatie_id=melding.id,
            nieuwe_waarde={"status": melding.status, "reden": reden},
            administratie_id=administratie_id,
        )
        return _meerwerk_data(session, melding)


def markeer_doorbelast(
    *, administratie_id: uuid.UUID, meerwerk_id: uuid.UUID, actor_id: uuid.UUID, verkoopfactuur_referentie: str
) -> MeerwerkData:
    """goedgekeurd → doorbelast — de verkoopfactuur-referentie is verplicht (zichtbaar in de
    lijst als 'doorbelast · VF-…'); dit sluit de 2-weken-bewaking voor dit item."""
    referentie = (verkoopfactuur_referentie or "").strip()
    if not referentie:
        raise OngeldigeInvoer("De verkoopfactuur-referentie is verplicht bij doorbelasten")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        melding = _meerwerk(session, meerwerk_id)
        if (
            melding.status == MeerwerkStatus.DOORBELAST.value
            and melding.verkoopfactuur_referentie == referentie
        ):
            return _meerwerk_data(session, melding)  # herhaald besluit
        if melding.status != MeerwerkStatus.GOEDGEKEURD.value:
            raise OngeldigeOvergang("Alleen goedgekeurd meerwerk kan doorbelast gemarkeerd worden")

        melding.status = MeerwerkStatus.DOORBELAST.value
        melding.verkoopfactuur_referentie = referentie
        melding.doorbelast_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="meerwerk",
            record_id=melding.id,
            actie="meerwerk_doorbelast",
            correlatie_id=melding.id,
            nieuwe_waarde={"status": melding.status, "verkoopfactuur_referentie": referentie},
            administratie_id=administratie_id,
        )
        return _meerwerk_data(session, melding)


def stel_vraag(
    *, administratie_id: uuid.UUID, meerwerk_id: uuid.UUID, actor_id: uuid.UUID, tekst: str
) -> MeerwerkData:
    """Lichte kantoor→uitvoerder-vraag uit het beoordeel-paneel; de status blijft `gemeld`."""
    tekst = (tekst or "").strip()
    if not tekst:
        raise OngeldigeInvoer("Een vraag zonder tekst kan niet gesteld worden")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        melding = _meerwerk(session, meerwerk_id)
        if melding.status != MeerwerkStatus.GEMELD.value:
            raise OngeldigeOvergang("Een vraag stellen kan alleen bij een gemelde melding")
        melding.vraag_tekst = tekst
        melding.vraag_gesteld_door = actor_id
        melding.vraag_gesteld_op = datetime.now(UTC)
        melding.vraag_antwoord = None
        melding.vraag_beantwoord_op = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="meerwerk",
            record_id=melding.id,
            actie="meerwerk_vraag_gesteld",
            correlatie_id=melding.id,
            nieuwe_waarde={"vraag": tekst},
            administratie_id=administratie_id,
        )
        return _meerwerk_data(session, melding)


def beantwoord_vraag(
    *, administratie_id: uuid.UUID, meerwerk_id: uuid.UUID, actor_id: uuid.UUID, tekst: str
) -> MeerwerkData:
    tekst = (tekst or "").strip()
    if not tekst:
        raise OngeldigeInvoer("Een leeg antwoord kan niet opgeslagen worden")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        melding = _meerwerk(session, meerwerk_id)
        actor = _gebruiker(session, actor_id)
        if actor.rol != GebruikerRol.UITVOERDER or not _heeft_toewijzing(
            session, administratie_id, actor_id, melding.project_id
        ):
            raise GeenToegang("Alleen een uitvoerder van dit project beantwoordt de vraag")
        if melding.vraag_tekst is None:
            raise OngeldigeOvergang("Er staat geen vraag open op deze melding")
        melding.vraag_antwoord = tekst
        melding.vraag_beantwoord_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="meerwerk",
            record_id=melding.id,
            actie="meerwerk_vraag_beantwoord",
            correlatie_id=melding.id,
            nieuwe_waarde={"antwoord": tekst},
            administratie_id=administratie_id,
        )
        return _meerwerk_data(session, melding)


def contract_toets(
    *, administratie_id: uuid.UUID, project_id: uuid.UUID, eenheid: str
) -> list[StaffelRegelData]:
    """VOORSTEL uit de offerte-staffel: alle staffelregels van dit project met dezelfde
    eenheid. Leeg = geen staffel bekend — de mens prijst dan volledig handmatig. Bewust een
    lijst (meerdere regels met dezelfde eenheid = de mens kiest), nooit een berekening."""
    with scoped_session(administratie_id) as session:
        regels = session.scalars(
            select(ProjectStaffel)
            .where(
                ProjectStaffel.administratie_id == administratie_id,
                ProjectStaffel.project_id == project_id,
                ProjectStaffel.eenheid == eenheid,
            )
            .order_by(ProjectStaffel.aangemaakt_op)
        ).all()
        return [
            StaffelRegelData(
                id=r.id,
                omschrijving=r.omschrijving,
                eenheid=r.eenheid,
                prijs_per_eenheid=r.prijs_per_eenheid,
                verrekenbaar=r.verrekenbaar,
                bron=r.bron,
            )
            for r in regels
        ]


def bewaking_niet_doorbelast(*, administratie_id: uuid.UUID) -> list[MeerwerkData]:
    """2-weken-signaal (mockup + item-niveau-doorbelastingscontrole): goedgekeurd meerwerk dat
    ná BEWAKING_DAGEN nog niet op een verkoopfactuur staat — werkvoorraad-signaal."""
    grens = datetime.now(UTC) - timedelta(days=BEWAKING_DAGEN)
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(
            select(Meerwerk)
            .where(
                Meerwerk.administratie_id == administratie_id,
                Meerwerk.status == MeerwerkStatus.GOEDGEKEURD.value,
                Meerwerk.beoordeeld_op < grens,
            )
            .order_by(Meerwerk.beoordeeld_op)
        ).all()
        return [_meerwerk_data(session, m) for m in rijen]


# --- koppelingen-beheer (Beheerder-only via de router, geaudit) --------------------------------


def koppel_project(
    *, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID, project_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    """Koppel een ZZP'er of uitvoerder aan een project (kantoor-beheer). Idempotent."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _project(session, administratie_id, project_id)
        gebruiker = _gebruiker(session, gebruiker_id)
        if gebruiker.rol not in (GebruikerRol.ZZPER, GebruikerRol.UITVOERDER):
            raise OngeldigeInvoer("Alleen ZZP'ers en uitvoerders worden aan projecten gekoppeld")
        if _heeft_toewijzing(session, administratie_id, gebruiker_id, project_id):
            return  # idempotent
        session.add(
            UrenProjectToewijzing(
                administratie_id=administratie_id,
                gebruiker_id=gebruiker_id,
                project_id=project_id,
                toegevoegd_door=actor_id,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="uren_project_toewijzing",
            record_id=gebruiker_id,
            actie="uren_project_gekoppeld",
            correlatie_id=project_id,
            nieuwe_waarde={"gebruiker_id": str(gebruiker_id), "project_id": str(project_id), "rol": gebruiker.rol},
            administratie_id=administratie_id,
        )


def ontkoppel_project(
    *, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID, project_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    """Koppeling verwijderen — bestaande weekstaten/meerwerk blijven staan (niets verdwijnt)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(UrenProjectToewijzing, (administratie_id, gebruiker_id, project_id))
        if rij is None:
            return  # idempotent
        session.delete(rij)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="uren_project_toewijzing",
            record_id=gebruiker_id,
            actie="uren_project_ontkoppeld",
            correlatie_id=project_id,
            oude_waarde={"gebruiker_id": str(gebruiker_id), "project_id": str(project_id)},
            administratie_id=administratie_id,
        )


def koppel_detacheerder(*, detacheerder_id: uuid.UUID, zzper_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Koppel een detacheerder aan een ZZP'er (kantoor-beheer, persoonsniveau). Idempotent."""
    with scoped_session(None, actor_id=actor_id) as session:
        detacheerder = _gebruiker(session, detacheerder_id)
        zzper = _gebruiker(session, zzper_id)
        if detacheerder.rol != GebruikerRol.DETACHEERDER:
            raise OngeldigeInvoer("De eerste gebruiker moet de rol detacheerder hebben")
        if zzper.rol != GebruikerRol.ZZPER:
            raise OngeldigeInvoer("De tweede gebruiker moet de rol ZZP'er hebben")
        if session.get(DetacheerderKoppeling, (detacheerder_id, zzper_id)) is not None:
            return  # idempotent
        session.add(
            DetacheerderKoppeling(
                detacheerder_gebruiker_id=detacheerder_id,
                zzper_gebruiker_id=zzper_id,
                aangemaakt_door=actor_id,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="detacheerder_koppeling",
            record_id=detacheerder_id,
            actie="detacheerder_gekoppeld",
            correlatie_id=zzper_id,
            nieuwe_waarde={"detacheerder_gebruiker_id": str(detacheerder_id), "zzper_gebruiker_id": str(zzper_id)},
        )


# --- kantoor: lijsten, stand en module-recht (fase 3) ------------------------------------------


@dataclass(frozen=True)
class UrenStand:
    """Tellers voor de klantpagina-standen (toon-regel: blok alleen bij teller > 0) en het
    werkvoorraad-signaal van de 2-weken-bewaking."""

    meerwerk_te_beoordelen: int
    meerwerk_nog_doorbelasten: int
    meerwerk_te_lang_niet_doorbelast: int
    urenstaten_wachten_op_keuring: int


def meerwerk_lijst(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> list[MeerwerkData]:
    """Meerwerklijst voor het kantoor-deelscherm (alle statussen — niets verdwijnt stil;
    filteren doet de UI). Module-recht server-side."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_meerwerk_recht(session, actor_id)
        rijen = session.scalars(
            select(Meerwerk)
            .where(Meerwerk.administratie_id == administratie_id)
            .order_by(Meerwerk.gemeld_op.desc())
        ).all()
        return [_meerwerk_data(session, m) for m in rijen]


def contract_toets_voor_melding(
    *, administratie_id: uuid.UUID, meerwerk_id: uuid.UUID, actor_id: uuid.UUID
) -> list[StaffelRegelData]:
    """Contract-toets bij het beoordeel-paneel: staffelregels van het project van de melding
    met dezelfde eenheid — een VOORSTEL, de mens bevestigt (leeg = handmatig prijzen)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_meerwerk_recht(session, actor_id)
        melding = _meerwerk(session, meerwerk_id)
        project_id, eenheid = melding.project_id, melding.eenheid
    return contract_toets(administratie_id=administratie_id, project_id=project_id, eenheid=eenheid)


def uren_stand(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> UrenStand:
    grens = datetime.now(UTC) - timedelta(days=BEWAKING_DAGEN)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)

        def _tel(*condities) -> int:
            return session.execute(select(func.count()).where(*condities)).scalar_one()

        return UrenStand(
            meerwerk_te_beoordelen=_tel(
                Meerwerk.administratie_id == administratie_id,
                Meerwerk.status == MeerwerkStatus.GEMELD.value,
            ),
            meerwerk_nog_doorbelasten=_tel(
                Meerwerk.administratie_id == administratie_id,
                Meerwerk.status == MeerwerkStatus.GOEDGEKEURD.value,
            ),
            meerwerk_te_lang_niet_doorbelast=_tel(
                Meerwerk.administratie_id == administratie_id,
                Meerwerk.status == MeerwerkStatus.GOEDGEKEURD.value,
                Meerwerk.beoordeeld_op < grens,
            ),
            urenstaten_wachten_op_keuring=_tel(
                Weekstaat.administratie_id == administratie_id,
                Weekstaat.status == WeekstaatStatus.INGEDIEND.value,
            ),
        )


def module_recht_houders() -> list[uuid.UUID]:
    """Gebruikers mét het module-recht 'Meerwerk & urenstaten' (Beheerder-only via de router;
    Beheerders zelf staan hier niet in — zij hebben het recht impliciet altijd)."""
    with scoped_session(None) as session:
        return list(
            session.scalars(
                select(GebruikerModuleRol.gebruiker_id).where(
                    GebruikerModuleRol.module == MODULE,
                    GebruikerModuleRol.rol == MEERWERK_URENSTATEN_RECHT,
                )
            )
        )


def zet_meerwerk_recht(*, gebruiker_id: uuid.UUID, ingeschakeld: bool, actor_id: uuid.UUID) -> bool:
    """Module-recht toekennen/intrekken (Beheerder-only via de router; de RLS + audit-trigger
    van migratie 0034 bijten hieronder mee — nooit op de eigen gebruiker). Idempotent. Een
    Beheerder heeft het recht altijd impliciet; een expliciete rij voor een Beheerder of een
    externe rol is betekenisloos en wordt geweigerd."""
    with scoped_session(None, actor_id=actor_id) as session:
        doel = _gebruiker(session, gebruiker_id)
        if doel.rol == GebruikerRol.BEHEERDER:
            raise OngeldigeInvoer("Een Beheerder heeft dit recht altijd — niet instelbaar")
        if not is_kantoorrol(doel.rol):
            raise OngeldigeInvoer("Het module-recht is alleen voor kantoor-rollen")
        rij = session.get(GebruikerModuleRol, (gebruiker_id, MODULE))
        if ingeschakeld and rij is None:
            session.add(GebruikerModuleRol(gebruiker_id=gebruiker_id, module=MODULE, rol=MEERWERK_URENSTATEN_RECHT))
        elif not ingeschakeld and rij is not None:
            session.delete(rij)
        return ingeschakeld


def ontkoppel_detacheerder(*, detacheerder_id: uuid.UUID, zzper_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.get(DetacheerderKoppeling, (detacheerder_id, zzper_id))
        if rij is None:
            return  # idempotent
        session.delete(rij)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="detacheerder_koppeling",
            record_id=detacheerder_id,
            actie="detacheerder_ontkoppeld",
            correlatie_id=zzper_id,
            oude_waarde={"detacheerder_gebruiker_id": str(detacheerder_id), "zzper_gebruiker_id": str(zzper_id)},
        )
