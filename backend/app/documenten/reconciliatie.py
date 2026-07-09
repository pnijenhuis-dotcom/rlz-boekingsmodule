from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, Document, DocumentStatus
from app.documenten.rlz_ids import rlz_purchase_invoice_id
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

# Kleine afrondingstolerantie, zelfde als de regeltelling-check (app/documenten/checks.py) —
# geen 0-tolerantie, wél klein genoeg om een echte afwijking te vangen.
_ROND_TOLERANTIE = Decimal("0.01")
_RLZ_STATUS_DEFINITIEF = 2


@dataclass(frozen=True)
class ReconciliatieAfwijking:
    document_id: uuid.UUID
    rlz_document_id: uuid.UUID
    soort: str
    detail: str


@dataclass(frozen=True)
class ReconciliatieRapport:
    administratie_id: uuid.UUID
    aantal_gecontroleerd: int
    afwijkingen: tuple[ReconciliatieAfwijking, ...]


def _geboekte_documenten(administratie_id: uuid.UUID) -> list[tuple[uuid.UUID, Decimal | None, str | None]]:
    with scoped_session(administratie_id) as session:
        rows = session.execute(
            select(Document.id, Boekvoorstel.totaalbedrag, Boekvoorstel.rlz_boekstuknummer)
            .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
            .where(Document.administratie_id == administratie_id, Document.status == DocumentStatus.GEBOEKT)
        ).all()
        return list(rows)


def _vergelijk_met_rlz(
    *, client: RlzClient, document_id: uuid.UUID, totaalbedrag: Decimal | None, rlz_boekstuknummer: str | None
) -> list[ReconciliatieAfwijking]:
    rlz_document_id = rlz_purchase_invoice_id(document_id)
    try:
        invoice = client.get(f"PurchaseInvoices/{rlz_document_id}")
    except RlzApiError as exc:
        return [ReconciliatieAfwijking(document_id, rlz_document_id, "ontbreekt_in_rlz", str(exc))]

    afwijkingen: list[ReconciliatieAfwijking] = []
    if invoice.get("Status") != _RLZ_STATUS_DEFINITIEF:
        afwijkingen.append(
            ReconciliatieAfwijking(
                document_id, rlz_document_id, "status_niet_definitief", f"RLZ-status={invoice.get('Status')}"
            )
        )
    rlz_bedrag = invoice.get("BaseInvoiceAmount")
    if (
        totaalbedrag is not None
        and rlz_bedrag is not None
        and abs(Decimal(str(rlz_bedrag)) - totaalbedrag) > _ROND_TOLERANTIE
    ):
        detail = f"eigen=€{totaalbedrag} rlz=€{rlz_bedrag}"
        afwijkingen.append(ReconciliatieAfwijking(document_id, rlz_document_id, "bedrag_wijkt_af", detail))
    if invoice.get("ReceiptNumber") != rlz_boekstuknummer:
        afwijkingen.append(
            ReconciliatieAfwijking(
                document_id,
                rlz_document_id,
                "boekstuknummer_wijkt_af",
                f"eigen={rlz_boekstuknummer!r} rlz={invoice.get('ReceiptNumber')!r}",
            )
        )
    return afwijkingen


def reconcilieer_administratie(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> ReconciliatieRapport:
    """Failsafe (b) (CLAUDE.md-taak 2.4): vergelijkt elk lokaal GEBOEKT document met de
    werkelijke RLZ-staat (bestaat, Status=2 definitief, bedrag, boekstuknummer) — vangt gevallen
    waarin de boeking lokaal als geslaagd geregistreerd staat maar in RLZ zelf iets anders is
    (bv. een latere handmatige correctie in RLZ, of een netwerkfout ná de succesvolle RLZ-schrijf-
    actie maar vóór onze eigen statusovergang — theoretisch, dit rapport is het vangnet)."""
    geboekte_documenten = _geboekte_documenten(administratie_id)
    if not geboekte_documenten:
        return ReconciliatieRapport(administratie_id=administratie_id, aantal_gecontroleerd=0, afwijkingen=())

    eigen_client = client is None
    if client is None:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    try:
        afwijkingen: list[ReconciliatieAfwijking] = []
        for document_id, totaalbedrag, rlz_boekstuknummer in geboekte_documenten:
            afwijkingen.extend(
                _vergelijk_met_rlz(
                    client=client,
                    document_id=document_id,
                    totaalbedrag=totaalbedrag,
                    rlz_boekstuknummer=rlz_boekstuknummer,
                )
            )
    finally:
        if eigen_client:
            client.close()

    return ReconciliatieRapport(
        administratie_id=administratie_id, aantal_gecontroleerd=len(geboekte_documenten), afwijkingen=tuple(afwijkingen)
    )


def reconcilieer_alle_administraties() -> dict[uuid.UUID, ReconciliatieRapport | str]:
    """Eén administratie zonder werkende credentials laat de rest niet stoppen — zelfde patroon
    als app/sync/service.py::sync_alle_administraties."""
    with scoped_session(None) as session:
        administratie_ids = [row.id for row in session.scalars(select(Administratie))]

    resultaten: dict[uuid.UUID, ReconciliatieRapport | str] = {}
    for administratie_id in administratie_ids:
        try:
            resultaten[administratie_id] = reconcilieer_administratie(administratie_id=administratie_id)
        except Exception as exc:  # noqa: BLE001 — bewust breed, zie sync_alle_administraties
            resultaten[administratie_id] = str(exc)
    return resultaten
