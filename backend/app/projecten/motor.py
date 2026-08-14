"""Idempotente projectaanmaak-naar-RLZ (route A, koppelcontract §5; BOUWPLAN fase 4).
Schrijfroute-feiten: verkenning/api-verkenning.md "Projects klant-loze schrijfroute
(browsercapture Peter + hertest)", 2026-08-14 — de correctie op de eerdere STAP-0-conclusie.

Kernontwerp:
- Deterministisch client-GUID (rlz_pand_project_id: UUIDv5 over administratie + vastgoeds
  stabiele pand-referentie) + lookup-vóór-PUT tegen de ACTUELE RLZ-staat. De hertest bevestigde
  het STAP-0-gedrag: een herhaal-PUT met afwijkende body muteert (PUT = create-or-update), dus
  bij een bestaand project wordt NOOIT opnieuw gePUT — de bestaande RLZ-staat wint, incl. naam.
- De schrijfroute is de klant-loze top-level `PUT {adminId}/Projects/{id}` (screencheck Peter
  2026-08-14 + Basic-Auth-hertest): een project heeft GEEN customer nodig. Het systeemanker
  "Pandprojecten (systeem)" verdwijnt daarmee uit het aanmaakpad; de anker-checklaag
  (app/projecten/anker.py) blijft als vangnet staan zolang er nog een anker-debiteur in een
  administratie bestaat (archiveren van een Customer kan niet via de API — hertest).
- `IsActive: true` expliciet in de PUT (hertest: default is opnieuw false — het project zou
  anders onzichtbaar/inactief zijn; NB RLZ wéígert een inactief project niet op documentregels).
- project_cache wordt direct ná succes bijgewerkt (geen wachtend sync-venster): het verse
  RLZ-record wordt teruggelezen (de PUT-respons is 204 zonder body) en geüpsert.
- Failsafes: naam-conflict (zelfde naam, ander GUID) en elke RLZ-fout zijn zichtbare,
  blokkerende fouten — nooit stil, nooit gokken."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.rlz_ids import rlz_pand_project_id
from app.projecten.models import ProjectAanvraagStatus
from app.projecten.naamconventie import vorm_projectnaam
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import ProjectCache

logger = logging.getLogger(__name__)


class ProjectAanmakenMislukt(Exception):
    """RLZ-fout of onoplosbare toestand tijdens de aanmaak — zichtbare foutstatus (502 op het
    koppelvlak), vastgoed herhaalt met hetzelfde bericht_id; nooit een halve stille uitkomst."""


class ProjectNaamConflict(Exception):
    """Er bestaat al een RLZ-project met exact deze naam onder een ánder GUID — fail-closed:
    mens lost op (in RLZ of met een andere naam-invoer), de motor maakt nooit een gelijknamig
    tweede project en hernoemt nooit stil."""

    def __init__(self, naam: str, bestaand_project_id: str) -> None:
        super().__init__(
            f"Er bestaat al een RLZ-project met de naam '{naam}' (id {bestaand_project_id}) "
            "dat niet bij deze pand-referentie hoort"
        )
        self.naam = naam
        self.bestaand_project_id = bestaand_project_id


@dataclass(frozen=True)
class ProjectAanmaakResultaat:
    rlz_project_id: uuid.UUID
    projectnaam: str
    status: ProjectAanvraagStatus


def _upsert_project_cache(
    *, administratie_id: uuid.UUID, project_id: uuid.UUID, record: dict[str, Any]
) -> None:
    """Directe cache-bijwerking ná succes (zelfde veldmapping als app/sync/service.py::
    _project_waarden) — de reguliere sync blijft de periodieke waarheid, dit dicht alleen het
    venster tussen aanmaak en eerstvolgende sync-run."""
    now = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        rij = session.get(ProjectCache, (project_id, administratie_id))
        if rij is None:
            session.add(
                ProjectCache(
                    id=project_id,
                    administratie_id=administratie_id,
                    naam=record.get("Name"),
                    is_actief=record.get("IsActive"),
                    brondata=record,
                    laatst_gesynchroniseerd=now,
                    verdwenen_uit_bron_op=None,
                )
            )
        else:
            rij.naam = record.get("Name")
            rij.is_actief = record.get("IsActive")
            rij.brondata = record
            rij.laatst_gesynchroniseerd = now
            rij.verdwenen_uit_bron_op = None


def maak_pand_project_aan(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    pand_referentie: str,
    naam_invoer: str,
    client: RlzClient | None = None,
) -> ProjectAanmaakResultaat:
    """Vindt of maakt het RLZ-project voor dit pand, idempotent. Kan OngeldigeProjectnaam
    (naamconventie), ProjectNaamConflict of ProjectAanmakenMislukt gooien — allemaal zichtbaar
    voor de aanroeper (het koppelvlak vertaalt naar 400/409/502)."""
    naam = vorm_projectnaam(naam_invoer)
    project_id = rlz_pand_project_id(administratie_id, pand_referentie)

    eigen_client = client is None
    if client is None:
        client = client_voor_rlz_admin_id(rlz_admin_id_voor(administratie_id))
    try:
        try:
            bestaand = client.get_project(project_id)
        except Exception as exc:  # noqa: BLE001 — fail-closed: zonder betrouwbare lookup geen PUT
            raise ProjectAanmakenMislukt(f"Project-lookup in RLZ mislukt: {exc}") from exc

        if bestaand is not None:
            # RLZ-staat wint: geen herhaal-PUT (die zou muteren — create-or-update), de
            # werkelijke naam gaat terug in het antwoord. Cache wél verversen.
            _upsert_project_cache(
                administratie_id=administratie_id, project_id=project_id, record=bestaand
            )
            return ProjectAanmaakResultaat(
                rlz_project_id=project_id,
                projectnaam=bestaand.get("Name") or naam,
                status=ProjectAanvraagStatus.BESTOND_AL,
            )

        try:
            naamgenoten = client.find_projects_by_name(name=naam)
        except Exception as exc:  # noqa: BLE001
            raise ProjectAanmakenMislukt(f"Project-naamcheck in RLZ mislukt: {exc}") from exc
        if naamgenoten:
            raise ProjectNaamConflict(naam, str(naamgenoten[0].get("id")))

        try:
            client.put_project(project_id, name=naam, is_active=True)
            vers = client.get_project(project_id)
        except Exception as exc:  # noqa: BLE001 — élke RLZ-fout is een zichtbare foutstatus
            raise ProjectAanmakenMislukt(f"Projectaanmaak in RLZ mislukt: {exc}") from exc
        if vers is None:
            raise ProjectAanmakenMislukt(
                "RLZ accepteerde de project-PUT maar het project is niet terugleesbaar — "
                "niet doorgaan zonder geverifieerde staat"
            )

        _upsert_project_cache(administratie_id=administratie_id, project_id=project_id, record=vers)
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="projectaanvraag",
                record_id=project_id,
                actie="project_aangemaakt_in_rlz",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "rlz_project_id": str(project_id),
                    "projectnaam": naam,
                    "pand_referentie": pand_referentie,
                },
                administratie_id=administratie_id,
            )
        logger.info(
            "RLZ-project %s ('%s') aangemaakt voor administratie %s", project_id, naam, administratie_id
        )
        return ProjectAanmaakResultaat(
            rlz_project_id=project_id, projectnaam=naam, status=ProjectAanvraagStatus.AANGEMAAKT
        )
    finally:
        if eigen_client:
            client.close()
