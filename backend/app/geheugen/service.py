from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

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
    return bepaal_voorstel(
        observaties,
        regel_sleutel=normaliseer_regel_sleutel(regel_omschrijving),
        vandaag=datetime.now(UTC).date(),
    )
