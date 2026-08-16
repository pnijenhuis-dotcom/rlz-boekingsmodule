"""Doorbelasting-reconciliatie (failsafe, zelfde patroon als de omzet-reconciliatie):
vergelijkt elke lokale doorbelastings-boeking met de werkelijke RLZ-staat van BEIDE kanten —
de verkoopfactuur in de bron-administratie én de spiegel-inkoopfactuur in de
doel-administratie — en rapporteert afwijkingen: in de RLZ-UI teruggedraaide documenten
(Status 1), verdwenen documenten, alle half_geboekt-rijen (die zíjn de afwijking) en
spiegel_open-taken ouder dan een week (open werk mag niet stilletjes verstoffen).
Rapporteert alleen; herstellen is mensenwerk."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Administratie
from app.db.session import scoped_session
from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingBoekingStatus
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)

_GEBOEKTE_STATUSSEN = {2, 3}
_SPIEGEL_OPEN_SIGNALEER_NA = timedelta(days=7)


@dataclass(frozen=True)
class DoorbelastingAfwijking:
    administratie_id: uuid.UUID
    boeking_id: uuid.UUID
    document_id: uuid.UUID
    soort: str
    detail: str


@dataclass(frozen=True)
class DoorbelastingReconciliatieResultaat:
    afwijkingen: list[DoorbelastingAfwijking]
    fouten: dict[uuid.UUID, str]


def _controleer(client: RlzClient, pad: str, rlz_id: uuid.UUID, label: str) -> tuple[str, str] | None:
    try:
        doc = client.get(f"{pad}/{rlz_id}")
    except RlzApiError as exc:
        if exc.status_code == 404:
            return "ontbreekt_in_rlz", f"{label} {rlz_id} bestaat niet (meer) in RLZ"
        return "controle_mislukt", f"{label} {rlz_id} kon niet opgehaald worden: {exc}"
    status = doc.get("Status")
    if status not in _GEBOEKTE_STATUSSEN:
        return "status_niet_definitief", f"{label} {rlz_id} staat in RLZ op Status {status}"
    return None


def reconcilieer_doorbelasting(administratie_id: uuid.UUID) -> list[DoorbelastingAfwijking]:
    with scoped_session(administratie_id) as session:
        boekingen = session.scalars(
            select(DoorbelastingBoeking).where(
                DoorbelastingBoeking.administratie_id == administratie_id,
                DoorbelastingBoeking.status.in_(
                    (
                        DoorbelastingBoekingStatus.GEBOEKT.value,
                        DoorbelastingBoekingStatus.HALF_GEBOEKT.value,
                        DoorbelastingBoekingStatus.SPIEGEL_OPEN.value,
                    )
                ),
            )
        ).all()
    if not boekingen:
        return []

    afwijkingen: list[DoorbelastingAfwijking] = []

    def meld(boeking: DoorbelastingBoeking, soort: str, detail: str) -> None:
        afwijkingen.append(
            DoorbelastingAfwijking(
                administratie_id=administratie_id,
                boeking_id=boeking.id,
                document_id=boeking.document_id,
                soort=soort,
                detail=detail,
            )
        )

    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    with client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id) as bron_client:
        for boeking in boekingen:
            if boeking.status == DoorbelastingBoekingStatus.HALF_GEBOEKT.value:
                meld(
                    boeking,
                    "half_geboekt",
                    f"half geboekt sinds {boeking.aangemaakt_op:%Y-%m-%d}: {boeking.half_geboekt_detail}",
                )
                continue
            # bron-kant: de verkoopfactuur moet geboekt staan (geldt voor geboekt én spiegel_open)
            fout = _controleer(bron_client, "SalesInvoices", boeking.verkoop_rlz_id, "doorbelastings-verkoop")
            if fout is not None:
                meld(boeking, *fout)
            if boeking.status == DoorbelastingBoekingStatus.SPIEGEL_OPEN.value:
                leeftijd = datetime.now(UTC) - boeking.aangemaakt_op
                if leeftijd > _SPIEGEL_OPEN_SIGNALEER_NA:
                    meld(
                        boeking,
                        "spiegel_open_verouderd",
                        f"open spiegel-taak staat al {leeftijd.days} dagen open (doel niet onboarded?)",
                    )

    # doel-kant per doel-administratie (eigen client per administratie, alleen voor geboekte)
    per_doel: dict[uuid.UUID, list[DoorbelastingBoeking]] = {}
    for boeking in boekingen:
        if boeking.status == DoorbelastingBoekingStatus.GEBOEKT.value and boeking.doel_administratie_id:
            per_doel.setdefault(boeking.doel_administratie_id, []).append(boeking)
    for doel_administratie_id, doel_boekingen in per_doel.items():
        try:
            doel_rlz_admin_id = rlz_admin_id_voor(doel_administratie_id)
            with client_voor_rlz_admin_id(doel_rlz_admin_id).for_administration(doel_rlz_admin_id) as doel_client:
                for boeking in doel_boekingen:
                    fout = _controleer(
                        doel_client, "PurchaseInvoices", boeking.spiegel_rlz_id, "spiegel-inkoopfactuur"
                    )
                    if fout is not None:
                        meld(boeking, *fout)
        except GeenRlzCredentials:
            for boeking in doel_boekingen:
                meld(
                    boeking,
                    "controle_mislukt",
                    f"doel-administratie {doel_administratie_id} heeft geen credentials (meer) — "
                    "spiegel niet controleerbaar",
                )
    return afwijkingen


# --- Opruimlijst achtergebleven RLZ-concepten (hygiëne-run 2026-08-16) ---------------------------
#
# RLZ-actie 19 (storno) verwijdert niet maar zet terug naar concept (Status 1); een gefaalde
# boekpoging kan bovendien een concept achterlaten zónder lokale boeking-rij (document-PUT
# geslaagd, actie 17 niet). Die concepten blijven in RLZ staan tot een mens ze opruimt —
# kernprincipe 3 (expliciet herbevestigd door Peter): DE APP VERWIJDERT NOOIT iets in RLZ.
# Deze lijst signaleert dus alleen ("handmatig opruimen indien gewenst") en telt nooit mee in
# de exit-code van de reconciliatie.


@dataclass(frozen=True)
class OpruimKandidaat:
    administratie_id: uuid.UUID  # bron-administratie (eigenaar van de doorbelasting)
    concept_administratie_id: uuid.UUID  # waar het concept staat (bron of doel)
    kant: str  # 'verkoop_bron' | 'spiegel_doel'
    rlz_id: uuid.UUID
    document_id: uuid.UUID
    referentie: str | None
    reden: str  # 'gestorneerd' | 'vervallen_run'
    detail: str


@dataclass(frozen=True)
class OpruimlijstResultaat:
    kandidaten: list[OpruimKandidaat]
    fouten: list[str]


def _rlz_status(client: RlzClient, pad: str, rlz_id: uuid.UUID) -> int | None:
    """RLZ-status van een document, of None bij 404 (al opgeruimd — geen bevinding)."""
    try:
        doc = client.get(f"{pad}/{rlz_id}")
    except RlzApiError as exc:
        if exc.status_code == 404:
            return None
        raise
    return doc.get("Status")


def verzamel_opruimlijst(administratie_id: uuid.UUID) -> OpruimlijstResultaat:
    """Achtergebleven RLZ-concepten (Status 1) van gestorneerde boekingen en vervallen
    (gefaalde) runs, beide kanten. Alleen rapporteren — verwijderen is mensenwerk in de
    RLZ-UI."""
    from app.documenten.rlz_ids import rlz_doorbelasting_spiegel_id, rlz_doorbelasting_verkoop_id
    from app.doorbelasting.models import (
        DoorbelastingMapping,
        DoorbelastingRegel,
        DoorbelastingRun,
        DoorbelastingRunStatus,
    )

    with scoped_session(administratie_id) as session:
        gestorneerd = session.scalars(
            select(DoorbelastingBoeking).where(
                DoorbelastingBoeking.administratie_id == administratie_id,
                DoorbelastingBoeking.status == DoorbelastingBoekingStatus.GESTORNEERD.value,
            )
        ).all()
        vervallen_runs = session.scalars(
            select(DoorbelastingRun).where(
                DoorbelastingRun.administratie_id == administratie_id,
                DoorbelastingRun.status == DoorbelastingRunStatus.CONCEPT.value,
                DoorbelastingRun.laatste_fout.is_not(None),
            )
        ).all()
        run_mappings: dict[uuid.UUID, set[uuid.UUID]] = {}
        for run in vervallen_runs:
            mapping_ids = set(
                session.scalars(
                    select(DoorbelastingRegel.mapping_id).where(DoorbelastingRegel.run_id == run.id)
                )
            )
            run_mappings[run.id] = mapping_ids
        mappings = {
            m.id: m
            for m in session.scalars(
                select(DoorbelastingMapping).where(DoorbelastingMapping.administratie_id == administratie_id)
            )
        }
        session.expunge_all()

    kandidaten: list[OpruimKandidaat] = []
    fouten: list[str] = []

    # Te controleren doelen: (document_id, verkoop_rlz_id, spiegel_rlz_id, doel_administratie_id,
    # referentie, reden, detail) — uit gestorneerde boekingen én afgeleide GUID's van
    # vervallen runs (deterministische UUIDv5, app/documenten/rlz_ids.py).
    te_controleren: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID | None, str | None, str, str]] = []
    for boeking in gestorneerd:
        te_controleren.append(
            (
                boeking.document_id,
                boeking.verkoop_rlz_id,
                boeking.spiegel_rlz_id,
                boeking.doel_administratie_id,
                boeking.verkoop_referentie,
                "gestorneerd",
                f"gestorneerd ({boeking.storno_reden or 'zonder reden'})",
            )
        )
    for run in vervallen_runs:
        for mapping_id in run_mappings.get(run.id, set()):
            mapping = mappings.get(mapping_id)
            if mapping is None:
                continue
            te_controleren.append(
                (
                    run.document_id,
                    rlz_doorbelasting_verkoop_id(run.document_id, mapping.doel_customer_guid),
                    rlz_doorbelasting_spiegel_id(run.document_id, mapping.doel_customer_guid),
                    mapping.doel_administratie_id,
                    None,
                    "vervallen_run",
                    f"gefaalde boekpoging (run {run.id}, doel {mapping.doelentiteit_naam})",
                )
            )

    if not te_controleren:
        return OpruimlijstResultaat(kandidaten=[], fouten=[])

    def voeg_toe(
        kant: str,
        concept_administratie_id: uuid.UUID,
        rlz_id: uuid.UUID,
        document_id: uuid.UUID,
        referentie: str | None,
        reden: str,
        detail: str,
    ) -> None:
        kandidaten.append(
            OpruimKandidaat(
                administratie_id=administratie_id,
                concept_administratie_id=concept_administratie_id,
                kant=kant,
                rlz_id=rlz_id,
                document_id=document_id,
                referentie=referentie,
                reden=reden,
                detail=detail,
            )
        )

    # Bron-kant: verkoop-concepten.
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    with client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id) as bron_client:
        for document_id, verkoop_rlz_id, _spiegel, _doel, referentie, reden, detail in te_controleren:
            try:
                status = _rlz_status(bron_client, "SalesInvoices", verkoop_rlz_id)
            except RlzApiError as exc:
                fouten.append(f"verkoop {verkoop_rlz_id} niet controleerbaar: {exc}")
                continue
            if status == 1:
                voeg_toe("verkoop_bron", administratie_id, verkoop_rlz_id, document_id, referentie, reden, detail)

    # Doel-kant: spiegel-concepten, per doel-administratie één client.
    per_doel: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, str | None, str, str]]] = {}
    for document_id, _verkoop, spiegel_rlz_id, doel_administratie_id, referentie, reden, detail in te_controleren:
        if doel_administratie_id is not None:
            per_doel.setdefault(doel_administratie_id, []).append(
                (document_id, spiegel_rlz_id, referentie, reden, detail)
            )
    for doel_administratie_id, items in per_doel.items():
        try:
            doel_rlz_admin_id = rlz_admin_id_voor(doel_administratie_id)
            with client_voor_rlz_admin_id(doel_rlz_admin_id).for_administration(doel_rlz_admin_id) as doel_client:
                for document_id, spiegel_rlz_id, referentie, reden, detail in items:
                    try:
                        status = _rlz_status(doel_client, "PurchaseInvoices", spiegel_rlz_id)
                    except RlzApiError as exc:
                        fouten.append(f"spiegel {spiegel_rlz_id} niet controleerbaar: {exc}")
                        continue
                    if status == 1:
                        voeg_toe(
                            "spiegel_doel", doel_administratie_id, spiegel_rlz_id, document_id,
                            referentie, reden, detail,
                        )
        except GeenRlzCredentials:
            fouten.append(
                f"doel-administratie {doel_administratie_id} heeft geen credentials (meer) — "
                f"{len(items)} spiegel-concept(en) niet controleerbaar"
            )
    return OpruimlijstResultaat(kandidaten=kandidaten, fouten=fouten)


def verzamel_alle_opruimlijsten() -> OpruimlijstResultaat:
    """Over alle administraties met doorbelasting aan — zelfde looppatroon als
    reconcilieer_alle_doorbelasting; puur informatief (nooit exit-code)."""
    with scoped_session(None) as session:
        administraties = session.scalars(
            select(Administratie).where(
                Administratie.actief.is_(True), Administratie.doorbelasting_ingeschakeld.is_(True)
            )
        ).all()
    kandidaten: list[OpruimKandidaat] = []
    fouten: list[str] = []
    for administratie in administraties:
        try:
            resultaat = verzamel_opruimlijst(administratie.id)
            kandidaten.extend(resultaat.kandidaten)
            fouten.extend(resultaat.fouten)
        except Exception as exc:  # noqa: BLE001 — rapportagerun: doorgaan, fout zichtbaar
            logger.exception("Opruimlijst faalde voor %s", administratie.naam)
            fouten.append(f"{administratie.naam}: {exc}")
    return OpruimlijstResultaat(kandidaten=kandidaten, fouten=fouten)


def reconcilieer_alle_doorbelasting() -> DoorbelastingReconciliatieResultaat:
    """Over alle actieve administraties mét doorbelasting aan (CLI-hook, zelfde vorm als
    reconcilieer_alle_omzet — een fout per administratie stopt de rest niet)."""
    with scoped_session(None) as session:
        administraties = session.scalars(
            select(Administratie).where(
                Administratie.actief.is_(True), Administratie.doorbelasting_ingeschakeld.is_(True)
            )
        ).all()
    afwijkingen: list[DoorbelastingAfwijking] = []
    fouten: dict[uuid.UUID, str] = {}
    for administratie in administraties:
        try:
            afwijkingen.extend(reconcilieer_doorbelasting(administratie.id))
        except Exception as exc:  # noqa: BLE001 — rapportagerun: doorgaan, fout zichtbaar
            logger.exception("Doorbelasting-reconciliatie faalde voor %s", administratie.naam)
            fouten[administratie.id] = f"{administratie.naam}: {exc}"
    return DoorbelastingReconciliatieResultaat(afwijkingen=afwijkingen, fouten=fouten)
