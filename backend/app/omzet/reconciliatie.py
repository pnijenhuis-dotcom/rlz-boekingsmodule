"""Omzet-reconciliatie (failsafe, zelfde patroon als de document- en bank-reconciliatie):
vergelijkt elke lokale omzet-boeking met de werkelijke RLZ-staat van BEIDE documenten
(verkoopfactuur + kostprijsmemoriaal) en rapporteert afwijkingen — in de RLZ-UI teruggedraaide
boekingen (Status 1), verdwenen documenten en alle half_geboekt-rijen (die zíjn de afwijking,
tot een mens ze oplost). Rapporteert alleen; herstellen is mensenwerk."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.db.models import Administratie
from app.db.session import scoped_session
from app.omzet.models import OmzetBoeking, OmzetBoekingStatus
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)

# Geboekt in RLZ-termen = Status 2 (open) of 3 (afgeletterd/gesloten) — nooit alleen op 2
# toetsen (DocumentStatus-semantiek, geverifieerd 2026-07-13).
_GEBOEKTE_STATUSSEN = {2, 3}


@dataclass(frozen=True)
class OmzetAfwijking:
    administratie_id: uuid.UUID
    boeking_id: uuid.UUID
    document_id: uuid.UUID
    soort: str
    detail: str


def _controleer_rlz_document(*, client: RlzClient, pad: str, rlz_id: uuid.UUID, label: str) -> str | None:
    """None = in orde; anders de afwijkingsomschrijving."""
    try:
        doc = client.get(f"{pad}/{rlz_id}")
    except RlzApiError as exc:
        if exc.status_code == 404:
            return f"{label} {rlz_id} bestaat niet (meer) in RLZ"
        return f"{label} {rlz_id} kon niet opgehaald worden: {exc}"
    status = doc.get("Status")
    if status not in _GEBOEKTE_STATUSSEN:
        return f"{label} {rlz_id} staat in RLZ op Status {status} (teruggedraaid naar concept?)"
    return None


def reconcilieer_omzet(administratie_id: uuid.UUID) -> list[OmzetAfwijking]:
    with scoped_session(administratie_id) as session:
        boekingen = session.scalars(
            select(OmzetBoeking).where(
                OmzetBoeking.administratie_id == administratie_id,
                OmzetBoeking.status.in_((OmzetBoekingStatus.GEBOEKT.value, OmzetBoekingStatus.HALF_GEBOEKT.value)),
            )
        ).all()
    if not boekingen:
        return []

    afwijkingen: list[OmzetAfwijking] = []
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    with client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id) as client:
        for boeking in boekingen:
            if boeking.status == OmzetBoekingStatus.HALF_GEBOEKT.value:
                afwijkingen.append(
                    OmzetAfwijking(
                        administratie_id=administratie_id,
                        boeking_id=boeking.id,
                        document_id=boeking.document_id,
                        soort="half_geboekt",
                        detail=(
                            f"Periode {boeking.periode_start} t/m {boeking.periode_eind}: "
                            f"verkoopfactuur {boeking.verkoop_rlz_id} staat (mogelijk) geboekt zonder "
                            f"kostprijsmemoriaal — {boeking.half_geboekt_detail}"
                        ),
                    )
                )
                continue
            for pad, rlz_id, label in (
                ("SalesInvoices", boeking.verkoop_rlz_id, "verkoopfactuur"),
                ("ManualJournals", boeking.memoriaal_rlz_id, "kostprijsmemoriaal"),
            ):
                if rlz_id is None:
                    continue
                detail = _controleer_rlz_document(client=client, pad=pad, rlz_id=rlz_id, label=label)
                if detail is not None:
                    afwijkingen.append(
                        OmzetAfwijking(
                            administratie_id=administratie_id,
                            boeking_id=boeking.id,
                            document_id=boeking.document_id,
                            soort="rlz_afwijking",
                            detail=f"Periode {boeking.periode_start} t/m {boeking.periode_eind}: {detail}",
                        )
                    )
    return afwijkingen


def reconcilieer_alle_omzet() -> list[OmzetAfwijking]:
    """Alle administraties; één kapotte administratie (credentials, RLZ-storing) stopt de rest
    niet — zelfde patroon als sync_alle_administraties."""
    with scoped_session(None) as session:
        administratie_ids = [rij.id for rij in session.scalars(select(Administratie))]

    alle: list[OmzetAfwijking] = []
    for administratie_id in administratie_ids:
        try:
            alle.extend(reconcilieer_omzet(administratie_id))
        except Exception:  # noqa: BLE001 — rapporteren en door, nooit de hele run stoppen
            logger.exception("Omzet-reconciliatie mislukt voor administratie %s", administratie_id)
    return alle
