"""Duplicaatsignaal — gecachete uitkomst van de RLZ-duplicaatquery per document (besluit Peter
25-08, RLZ-feedbackronde deel 2 punt 6).

Waarom: de duplicaatcheck (Entity+Reference+bedrag, besluit 0013) draaide alleen op het
controlescherm/boekmoment; in de werkvoorraad zag je het pas na openen. Deze motor draait
dezélfde query ná extractie en bij elke veldopslag (`sla_boekvoorstel_op`) en cachet de
uitkomst op het document — de lijst toont een chip + filter zonder live RLZ-call per rij.

Harde regels:
- SIGNALERING, geen poort: de live check op het boekmoment (`checks.check_duplicaat` via
  `voer_checks_uit`) blijft bindend; de cache kan verouderen (een collega boekt intussen in
  RLZ) — bij verschil wint de live check.
- Nooit blokkerend voor de flow: elke fout is een gelogde waarschuwing én zichtbaar als
  uitkomst `onbekend` (RLZ onbereikbaar) — nooit stil.
- Zelfde uitzonderingslogica als de harde check: eigen client-GUID + de hele
  herboek-/tegenboek-keten van dit document tellen niet als duplicaat.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.db.session import scoped_session
from app.documenten.models import Document, DocumentSoort, DuplicaatSignaal, DuplicaatSignaalUitkomst
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DuplicaatSignaalData:
    document_id: uuid.UUID
    uitkomst: DuplicaatSignaalUitkomst
    treffers: list[dict]
    melding: str | None


def _treffer_kort(factuur: dict) -> dict:
    """Alleen de herleidbare kern van een RLZ-treffer (geen hele RLZ-records in de cache)."""
    return {
        "id": factuur.get("id"),
        "reference": factuur.get("Reference"),
        "invoice_number": factuur.get("InvoiceNumber"),
        "status": (factuur.get("Status") or {}).get("id") if isinstance(factuur.get("Status"), dict) else None,
    }


def bereken_duplicaatsignaal(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, client: RlzClient | None = None
) -> DuplicaatSignaalData | None:
    """Berekent en cachet het signaal voor één inkoopfactuur. `client=None` opent een eigen
    RlzClient (zelfde credential-resolutie als `voer_checks_uit`); een aanroeper met een open
    verbinding geeft 'm door. Geeft None terug voor documenten waar het signaal niet op van
    toepassing is (geen inkoopfactuur, verwijderd/gesplitst)."""
    from app.documenten.boekvoorstel import (
        haal_boekvoorstel_op,  # lokaal: boekvoorstel importeert ons niet, wij hem wel
    )

    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            return None
        if document.soort != DocumentSoort.INKOOPFACTUUR.value:
            return None

    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    kop_compleet = voorstel.vendor_id is not None and bool(voorstel.referentie) and voorstel.totaalbedrag is not None

    treffers: list[dict] = []
    melding: str | None = None
    if not kop_compleet:
        uitkomst = DuplicaatSignaalUitkomst.NIET_TOETSBAAR
        melding = "Crediteur, referentie en totaalbedrag zijn nog niet alle drie bekend"
    else:
        eigen_client = client is None
        try:
            if client is None:
                rlz_admin_id = rlz_admin_id_voor(administratie_id)
                client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
            gevonden = client.find_purchase_invoices_by_reference(
                vendor_id=voorstel.vendor_id,
                reference=voorstel.referentie,
                total_amount=float(voorstel.totaalbedrag),
            )
        except Exception as exc:  # noqa: BLE001 — bewust breed: RLZ-/credentialfout = zichtbaar 'onbekend', nooit een crash
            gevonden = None
            uitkomst = DuplicaatSignaalUitkomst.ONBEKEND
            melding = f"Duplicaatsignaal niet te berekenen: {exc}"
        finally:
            if eigen_client and client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    logger.debug("Sluiten RLZ-client mislukt", exc_info=True)
        if gevonden is not None:
            keten = {str(rlz_herboeking_id(document_id, c)) for c in range(voorstel.boek_cyclus + 1)} | {
                str(rlz_tegenboeking_id(document_id, c)) for c in range(voorstel.boek_cyclus + 1)
            }
            anderen = [f for f in gevonden if f.get("id") not in keten]
            treffers = [_treffer_kort(f) for f in anderen]
            if anderen:
                uitkomst = DuplicaatSignaalUitkomst.MOGELIJK_DUPLICAAT
                melding = f"{len(anderen)} bestaande factuur/facturen in RLZ met dezelfde crediteur, referentie en bedrag"
            else:
                uitkomst = DuplicaatSignaalUitkomst.GEEN
                melding = None

    with scoped_session(administratie_id) as session:
        rij = session.get(DuplicaatSignaal, document_id)
        if rij is None:
            rij = DuplicaatSignaal(document_id=document_id, administratie_id=administratie_id, uitkomst=uitkomst.value)
            session.add(rij)
        rij.uitkomst = uitkomst.value
        rij.vendor_id = voorstel.vendor_id
        rij.referentie = voorstel.referentie
        rij.totaalbedrag = voorstel.totaalbedrag
        rij.treffers = treffers
        rij.melding = melding
        session.flush()
    return DuplicaatSignaalData(document_id=document_id, uitkomst=uitkomst, treffers=treffers, melding=melding)


def bereken_duplicaatsignaal_stil(*, administratie_id: uuid.UUID | None, document_id: uuid.UUID) -> None:
    """Hook-variant voor post-commit-aanroepen (na extractie, na veldopslag): een fout is een
    gelogde waarschuwing — het signaal is signalering, nooit een blokkade van de verwerking."""
    if administratie_id is None:
        return
    try:
        bereken_duplicaatsignaal(administratie_id=administratie_id, document_id=document_id)
    except Exception:  # noqa: BLE001 — signalering mag de upload/worker/opslag nooit laten falen
        logger.exception("Duplicaatsignaal berekenen mislukt voor document %s", document_id)


@dataclass(frozen=True)
class DuplicaatSignaalKort:
    uitkomst: str
    aantal_treffers: int
    berekend_op: object  # datetime — object om de import in de lijst-laag licht te houden


def signalen_voor_documenten(session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, DuplicaatSignaalKort]:
    """Bulk-lezer voor de documentenlijst (geen N+1)."""
    if not document_ids:
        return {}
    return {
        s.document_id: DuplicaatSignaalKort(
            uitkomst=s.uitkomst, aantal_treffers=len(s.treffers or []), berekend_op=s.berekend_op
        )
        for s in session.scalars(select(DuplicaatSignaal).where(DuplicaatSignaal.document_id.in_(document_ids)))
    }
