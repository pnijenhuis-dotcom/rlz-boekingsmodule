from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import scoped_session
from app.geheugen.engine import GeheugenVoorstel, Observatie, bepaal_voorstel
from app.geheugen.models import BoekingObservatie
from app.geheugen.normalisatie import normaliseer_regel_sleutel


def voorstel_voor(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, regel_omschrijving: str | None = None
) -> GeheugenVoorstel:
    """Geheugen-voorstel voor één crediteur (+ optionele regelomschrijving): laadt de observaties
    en laat de pure engine wegen. Gebruikt door het controlescherm (B6-endpoint) én straks door
    de autoboek-gate — beide krijgen exact dezelfde confidence/oranje-vlaggen; het voorstel heft
    nooit een harde check op (projectplicht blijft blokkerend, zie app/documenten/checks.py)."""
    with scoped_session(administratie_id) as session:
        observaties = laad_engine_observaties(session, administratie_id=administratie_id, vendor_id=vendor_id)
    return bepaal_voorstel(
        observaties,
        regel_sleutel=normaliseer_regel_sleutel(regel_omschrijving),
        vandaag=datetime.now(UTC).date(),
    )


def laad_engine_observaties(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> list[Observatie]:
    """Dé lader van de vendor-niveau-observaties voor de engine — één vertaalpunt: staat er een Odoo-
    rekening-mapping voor deze administratie (overstap RLZ → Odoo, blok A 04-09, migratie 0111), dan
    worden RLZ-grootboek/-btw-UUID's VÓÓR het wegen vertaald (`app/odoo/mapping.py::vertaal_observaties`),
    zodat oude RLZ-stemmen en nieuwe Odoo-stemmen op dezelfde rekening één stem vormen en `app_bevestigd`
    behouden blijft. Geen mapping = ongewijzigd. Gebruikt door `voorstel_voor` (controlescherm + autoboek-
    poorten) én `documenten/regel_prefill.py` (btw-default-toets) — beide zien exact dezelfde invoer."""
    from app.odoo import mapping as odoo_mapping  # lokaal: odoo.mapping importeert de engine-dataclass

    rijen = session.scalars(
        select(BoekingObservatie).where(
            BoekingObservatie.administratie_id == administratie_id,
            BoekingObservatie.vendor_id == vendor_id,
        )
    ).all()
    observaties = [
        Observatie(
            regel_sleutel=rij.regel_sleutel,
            gb_id=rij.gb_id,
            btw_id=rij.btw_id,
            project_id=rij.project_id,
            bron=rij.bron,
            bron_datum=rij.bron_datum,
        )
        for rij in rijen
    ]
    mapping = odoo_mapping.geldende_mapping(session, administratie_id)
    if mapping.leeg:
        return observaties
    return odoo_mapping.vertaal_observaties(observaties, mapping)
