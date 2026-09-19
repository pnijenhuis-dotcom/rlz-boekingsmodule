"""Projectstatus lopend/afgesloten (blok A opdracht 18-09, Peter: "als een project afgesloten is kan het uit de lijst").

Model: `project_cache.status` is de MODULE-status mét afsluit-spoor; `is_actief` blijft de spiegel van de bron (RLZ
`IsActive`
/ Odoo `active`). Afsluiten = (1) bron inactief zetten via de bestaande adapter-seam — RLZ: klant-loze `PUT
Projects/{id}` mét
de bestaande naam + `IsActive:false` en TERUGLEESVERIFICATIE (RLZ wint bij conflict: leest RLZ nog `true`, dan is het
project
niet afgesloten en krijgt de mens dat te zien), Odoo: `active=False` op de analytic account via de company-gebonden
client
(archiveren, nooit unlink); (2) pas dán de status + audit oud→nieuw. Heropenen is het spiegelbeeld. Rol: Beheerder +
Boekhouding+Projecten (`_vereis_schrijfrol`). Gevolg: alle keuzelijsten filteren al op `is_actief` (planning, weekstaat,
verplichting, combobox onderaan mét chip) — één mechanisme, geen tweede waarheid.

Kandidaat afsluiten (automatisering-first, nooit automatisch): zie `app/projecten/afsluiten.py` (opdracht 19-09 —
redenen stil /
eindfactuur / naam zegt afgesloten / looptijd verstreken; herziet het 18-09-criterium op contract-m²)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.sync.models import PROJECT_STATUS_AFGESLOTEN, PROJECT_STATUS_LOPEND, ProjectCache


class ProjectStatusFout(Exception):
    """Basis voor status-domeinfouten (router: 422/409/502 op de subklasse)."""


class StatusOngewijzigd(ProjectStatusFout):
    """Al afgesloten resp. al lopend — 409, niets gebeurd."""


class BronWeigert(ProjectStatusFout):
    """De bron (RLZ/Odoo) nam de wijziging niet aan of bevestigde 'm niet bij teruglezen — 502, status ongewijzigd."""


@dataclass(frozen=True)
class ProjectStatusStand:
    project_id: uuid.UUID
    status: str
    is_actief: bool | None
    afgesloten_op: datetime | None
    afgesloten_door: uuid.UUID | None
    afsluit_reden: str | None


def _stand(p: ProjectCache) -> ProjectStatusStand:
    return ProjectStatusStand(
        project_id=p.id,
        status=p.status,
        is_actief=p.is_actief,
        afgesloten_op=p.afgesloten_op,
        afgesloten_door=p.afgesloten_door,
        afsluit_reden=p.afsluit_reden,
    )


# --- bron (adapter-seam)
# -----------------------------------------------------------------------------------------------


def _zet_rlz_actief(*, administratie_id: uuid.UUID, project: ProjectCache, actief: bool, client: Any | None) -> dict:
    """Klant-loze PUT mét de BESTAANDE naam (PUT = create-or-update; nooit een andere naam sturen) + teruglezen.
    Geeft het verse RLZ-record terug (bron voor de cache-upsert)."""
    from app.rlz.client import RlzApiError
    from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

    eigen = client is None
    if client is None:
        try:
            rlz_admin_id = rlz_admin_id_voor(administratie_id)
            client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
        except GeenRlzCredentials as exc:
            raise BronWeigert(f"Geen RLZ-login voor deze administratie: {exc}") from exc
    try:
        try:
            bestaand = client.get_project(project.id)
        except RlzApiError as exc:
            raise BronWeigert(f"RLZ-lookup mislukt ({exc.status_code}) — status ongewijzigd") from exc
        if bestaand is None:
            raise BronWeigert("Project bestaat niet (meer) in RLZ — status ongewijzigd; synchroniseer de projecten")
        naam = bestaand.get("Name") or project.naam or ""
        try:
            client.put_project(project.id, name=naam, is_active=actief)
            vers = client.get_project(project.id)
        except RlzApiError as exc:
            raise BronWeigert(f"RLZ weigerde de wijziging ({exc.status_code}) — status ongewijzigd") from exc
        if vers is None or bool(vers.get("IsActive")) is not actief:
            raise BronWeigert(
                f"RLZ bevestigde IsActive={str(actief).lower()} niet bij teruglezen — RLZ wint, status ongewijzigd"
            )
        return vers
    finally:
        if eigen and client is not None:
            client.close()


def _zet_odoo_actief(*, administratie_id: uuid.UUID, project: ProjectCache, actief: bool, client: Any | None) -> None:
    """Odoo: `active` op de analytic account (archiveren/dearchiveren via `write`, nooit unlink) + teruglezen."""
    from app.odoo.client import OdooFout
    from app.odoo.credentials import GeenOdooKoppeling, odoo_client_voor
    from app.odoo.models import OdooIdKoppeling
    from app.odoo.sync import MODEL_ANALYTIC

    with scoped_session(administratie_id) as session:
        koppeling = session.scalar(
            select(OdooIdKoppeling).where(
                OdooIdKoppeling.administratie_id == administratie_id,
                OdooIdKoppeling.model == MODEL_ANALYTIC,
                OdooIdKoppeling.lokaal_id == project.id,
            )
        )
        odoo_id = koppeling.odoo_id if koppeling else (project.brondata or {}).get("odoo_id")
    if odoo_id is None:
        raise BronWeigert("Geen Odoo-id bekend voor dit project (sync eerst) — status ongewijzigd")
    eigen = client is None
    if client is None:
        try:
            client = odoo_client_voor(administratie_id)
        except GeenOdooKoppeling as exc:
            raise BronWeigert(f"Geen Odoo-koppeling: {exc}") from exc
    try:
        try:
            client.write(MODEL_ANALYTIC, [int(odoo_id)], {"active": actief})
            terug = client.search_read(
                MODEL_ANALYTIC, [["id", "=", int(odoo_id)], ["active", "in", [True, False]]], ["id", "active"]
            )
        except OdooFout as exc:
            raise BronWeigert(f"Odoo weigerde de wijziging: {exc}") from exc
        if not terug or bool(terug[0].get("active")) is not actief:
            raise BronWeigert("Odoo bevestigde de wijziging niet bij teruglezen — status ongewijzigd")
    finally:
        if eigen and client is not None:
            client.close()


def _zet_bron_actief(
    *, administratie_id: uuid.UUID, project: ProjectCache, actief: bool, client: Any | None
) -> dict | None:
    from app.backends.port import Backend
    from app.backends.registry import backend_voor

    backend = backend_voor(administratie_id)
    if backend is Backend.ODOO:
        _zet_odoo_actief(administratie_id=administratie_id, project=project, actief=actief, client=client)
        return None
    return _zet_rlz_actief(administratie_id=administratie_id, project=project, actief=actief, client=client)


# --- schrijfpaden
# --------------------------------------------------------------------------------------------------------


def _wissel(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    naar: str,
    reden: str | None,
    datum: date | None,
    client: Any | None,
) -> ProjectStatusStand:
    from app.projecten.kantoor import ProjectNietGevonden, _vereis_schrijfrol

    with scoped_session(administratie_id) as session:
        _vereis_schrijfrol(session, actor_id)
        project = session.get(ProjectCache, (project_id, administratie_id))
        if project is None or project.verdwenen_uit_bron_op is not None:
            raise ProjectNietGevonden(f"Onbekend project: {project_id}")
        if project.status == naar:
            raise StatusOngewijzigd(f"Project staat al op {naar}")
        oud = _stand(project)
        session.expunge(project)

    actief = naar == PROJECT_STATUS_LOPEND
    vers = _zet_bron_actief(administratie_id=administratie_id, project=project, actief=actief, client=client)

    nu = datetime.now(UTC)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(ProjectCache, (project_id, administratie_id))
        if rij is None:
            raise ProjectNietGevonden(f"Onbekend project: {project_id}")
        rij.status = naar
        rij.is_actief = actief
        if vers is not None:
            rij.brondata = vers
            rij.laatst_gesynchroniseerd = nu
        if naar == PROJECT_STATUS_AFGESLOTEN:
            rij.afgesloten_op = datetime.combine(datum, datetime.min.time(), tzinfo=UTC) if datum else nu
            rij.afgesloten_door = actor_id
            rij.afsluit_reden = (reden or "").strip() or None
        else:
            rij.afgesloten_op = None
            rij.afgesloten_door = None
            rij.afsluit_reden = None
        nieuw = _stand(rij)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_cache",
            record_id=project_id,
            actie="project_afgesloten" if naar == PROJECT_STATUS_AFGESLOTEN else "project_heropend",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": oud.status, "is_actief": oud.is_actief, "afsluit_reden": oud.afsluit_reden},
            nieuwe_waarde={
                "status": nieuw.status,
                "is_actief": nieuw.is_actief,
                "afsluit_reden": nieuw.afsluit_reden,
                "afgesloten_op": nieuw.afgesloten_op.isoformat() if nieuw.afgesloten_op else None,
                "bron_bijgewerkt": "rlz" if vers is not None else "odoo",
            },
            administratie_id=administratie_id,
        )
        nieuw_stand = nieuw
    # Opdracht 19-09: de omzetsleutel van de projectverdeling volgt de status — nog niet geboekte verdelingen die dit
    # project
    # raken worden herrekend (snapshot + tijdlijn "verdeling herberekend: ‹project› afgesloten"), geboekte blijven
    # staan.
    # Eigen transactie, nooit blokkerend (fout = logregel; de volgende lezing rekent tóch live).
    from app.projectverdeling.afgesloten import herbereken_na_projectstatus_veilig

    herbereken_na_projectstatus_veilig(
        administratie_id=administratie_id,
        project_id=project_id,
        project_naam=project.naam,
        naar=naar,
        actor_id=actor_id,
    )
    return nieuw_stand


def sluit_project_af(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    reden: str | None = None,
    datum: date | None = None,
    client: Any | None = None,
) -> ProjectStatusStand:
    """Afsluiten: bron inactief (terugleesverificatie, RLZ wint bij conflict) → status afgesloten + audit. Nagekomen
    facturen blijven boekbaar (oranje signaal, nooit blokkerend —
    `app/documenten/checks.py::check_project_afgesloten`)."""
    return _wissel(
        administratie_id=administratie_id,
        project_id=project_id,
        actor_id=actor_id,
        naar=PROJECT_STATUS_AFGESLOTEN,
        reden=reden,
        datum=datum,
        client=client,
    )


def heropen_project(
    *, administratie_id: uuid.UUID, project_id: uuid.UUID, actor_id: uuid.UUID, client: Any | None = None
) -> ProjectStatusStand:
    """Terugweg: bron weer actief → status lopend, afsluit-spoor leeg (het audit-event houdt de historie)."""
    return _wissel(
        administratie_id=administratie_id,
        project_id=project_id,
        actor_id=actor_id,
        naar=PROJECT_STATUS_LOPEND,
        reden=None,
        datum=None,
        client=client,
    )


# --- kandidaat afsluiten ----------------------------------------------------------------------------------------------
# Opdracht 19-09: de kandidatenmotor leeft in `app/projecten/afsluiten.py` (één motor voor tab "Afsluiten? (N)", de chip
# op
# Inzicht › Projecten en de CLI). Het 18-09-criterium "stil ≥ 90 dagen ÉN contract-m² bereikt" is HERZIEN: kandidaat = één of meer
# redenen (stil N maanden per administratie, eindfactuur geboekt, naam zegt afgesloten, looptijd verstreken); "Niet
# afsluiten" mét
# reden onthoudt het besluit tot er nieuwe activiteit is. Afsluiten blijft altijd een klik van een mens (ook in bulk).
