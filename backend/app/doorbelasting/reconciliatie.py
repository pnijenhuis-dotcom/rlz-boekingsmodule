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
