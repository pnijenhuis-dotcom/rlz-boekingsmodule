from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.documenten.boekvoorstel import BoekvoorstelRegelData
from app.geheugen.models import BoekingObservatie, ObservatieBron, app_observatie_id
from app.geheugen.normalisatie import normaliseer_regel_sleutel

# Leerlus van het boekingsgeheugen (CLAUDE.md: "app-correcties wegen zwaarder"): elke geslaagde
# boeking (actie 17) is een door een mens bevestigde waarheid en wordt als observatie
# bron='app' vastgelegd — in dezelfde transactie als de status-overgang naar GEBOEKT
# (app/documenten/boeken.py), zodat geheugen en boekstatus nooit uit de pas lopen.


def leg_boeking_vast(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID,
    boekdatum: date,
    boekstuk_ref: str | None,
    regels: list[BoekvoorstelRegelData],
    regels_samenvoegen: bool,
) -> int:
    """Legt de geboekte regels vast als observaties. Samengevoegde boeking -> leverancier-niveau
    (regel_sleutel NULL: één samengevoegde regel zegt niets over regelsoorten); gesplitste
    boeking -> regel-niveau met de genormaliseerde omschrijving als sleutel.

    Idempotent per boekstuk-INHOUD, niet per boekstuk alleen: de deterministische id dekt ook de
    geboekte waarden (zie app_observatie_id) — een retry met identieke waarden legt niets dubbel
    vast, maar een correctie (actie 19 -> aanpassen -> opnieuw boeken) wordt een NIEUWE observatie
    met de nieuwe boekdatum, zodat de recency-weging de gecorrigeerde waarde laat winnen.
    `bron_datum` = boekdatum (het moment van menselijke bevestiging), bewust niet de factuurdatum:
    een correctie op een oude factuur is verse kennis. Retourneert het aantal nieuwe observaties."""
    nieuw = 0
    for volgnummer, regel in enumerate(regels, start=1):
        if regel.ledger_id is None:
            continue  # kan na de harde checks niet, maar het geheugen raadt nooit een GB
        omschrijving = None if regels_samenvoegen else (regel.omschrijving or None)
        regel_sleutel = normaliseer_regel_sleutel(omschrijving)
        observatie_id = app_observatie_id(
            administratie_id,
            document_id,
            volgnummer,
            gb_id=regel.ledger_id,
            btw_id=regel.taxrate_id,
            project_id=regel.project_id,
            regel_sleutel=regel_sleutel,
        )
        if session.get(BoekingObservatie, observatie_id) is not None:
            continue
        session.add(
            BoekingObservatie(
                id=observatie_id,
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                regel_sleutel=regel_sleutel,
                regel_omschrijving_raw=omschrijving,
                gb_id=regel.ledger_id,
                btw_id=regel.taxrate_id,
                project_id=regel.project_id,
                bron=ObservatieBron.APP.value,
                bron_datum=boekdatum,
                boekstuk_ref=boekstuk_ref,
            )
        )
        nieuw += 1
    return nieuw
