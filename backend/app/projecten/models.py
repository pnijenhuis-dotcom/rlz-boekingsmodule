from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class ProjectAanvraagStatus(enum.StrEnum):
    AANGEMAAKT = "aangemaakt"
    BESTOND_AL = "bestond_al"


class ProjectAanvraag(Base):
    """Eén verwerkte projectaanvraag van vastgoed (route A, koppelcontract §5 v1.15; migratie
    0048). `bericht_id` is de idempotentiesleutel (UUIDv5 door vastgoed gegenereerd, PK): een
    herlevering van hetzelfde bericht vindt deze rij en krijgt exact hetzelfde synchrone
    antwoord terug, zonder tweede RLZ-call. `nonce` is DB-uniek als replay-verdediging bovenop
    het timestamp-venster: dezelfde nonce onder een ánder bericht wordt geweigerd. Rijen
    ontstaan alleen bij een geslaagde verwerking (append-only register — een RLZ-fout is een
    zichtbare 502 + audit_event, vastgoed herhaalt met hetzelfde bericht_id)."""

    __tablename__ = "projectaanvraag"
    __table_args__ = {"schema": "boekhouding"}

    bericht_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    nonce: Mapped[str] = mapped_column(unique=True)
    pand_referentie: Mapped[str] = mapped_column()
    naam_invoer: Mapped[str] = mapped_column()
    # De door ónze naamconventie-motor gevormde definitieve projectnaam — bij `bestond_al` de
    # werkelijke naam van het bestaande RLZ-project (RLZ-staat wint, nooit stil hernoemen).
    projectnaam: Mapped[str] = mapped_column()
    rlz_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column()
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
