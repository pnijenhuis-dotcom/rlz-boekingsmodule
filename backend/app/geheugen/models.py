from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

# Vast, mag NOOIT wijzigen (zelfde redenering als app/documenten/rlz_ids.py): de deterministische
# observatie-id's maken seed en leerlus idempotent — een gewijzigde namespace zou bij her-runs
# stilletjes dubbele observaties opleveren en daarmee de weging vervalsen.
_NAMESPACE = uuid.UUID("7c1f4b7e-9c1d-4f5a-b7c3-5d20a4c4f9d2")


def seed_observatie_id(administratie_id: uuid.UUID, rlz_line_id: uuid.UUID | str) -> uuid.UUID:
    """Deterministische id voor een rlz_seed-observatie: de RLZ-regel-id is stabiel, dus een
    her-run van de seed raakt exact dezelfde rij (skip-if-exists) — idempotent en hervatbaar."""
    return uuid.uuid5(_NAMESPACE, f"seed:{administratie_id}:{rlz_line_id}")


def app_observatie_id(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    volgnummer: int,
    *,
    gb_id: uuid.UUID,
    btw_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    regel_sleutel: str | None,
) -> uuid.UUID:
    """Deterministische id voor een leerlus-observatie: per geboekt document + regelvolgnummer
    + de geboekte wáárden. Een retry van boek_document (zelfde client-GUID's, zelfde waarden)
    legt dus niets dubbel vast, maar een CORRECTIE (actie 19 -> aangepast -> opnieuw geboekt,
    koppelcontract §7.3) krijgt een nieuwe id en wordt als nieuwe observatie geleerd — nooit
    stil overgeslagen als "al gezien per boekstuk"; de recency-weging (bron_datum = boekdatum)
    laat de gecorrigeerde waarde vervolgens winnen. Waarden-afleiding gewijzigd 2026-07-13,
    vóór er productie-app-observaties bestonden — hierna geldt weer: NOOIT wijzigen."""
    return uuid.uuid5(
        _NAMESPACE,
        f"app:{administratie_id}:{document_id}:{volgnummer}:{gb_id}:{btw_id}:{project_id}:{regel_sleutel}",
    )


class ObservatieBron(enum.StrEnum):
    """'rlz_seed' = ingest uit RLZ's PurchaseInvoices+Lines (historie); 'app' = leerlus, een door
    een mens bevestigde boeking (actie 17). App-observaties wegen zwaarder in de engine
    (CLAUDE.md: "correcties wegen zwaarder")."""

    RLZ_SEED = "rlz_seed"
    APP = "app"


class BoekingObservatie(Base):
    """Eén waarneming voor het boekingsgeheugen (migratie 0020, append-only — correcties zijn
    nieuwe observaties, nooit mutaties). `regel_sleutel` NULL = leverancier-niveau (samengevoegde
    boeking); gevuld = regel-niveau (genormaliseerde token-set, app/geheugen/normalisatie.py).
    Bewust geen FK's naar de sync-caches (gb/btw/project): een observatie moet een cache-refresh
    of sync-verdwijning overleven — de engine stelt voor, de checks/controleur valideren."""

    __tablename__ = "boeking_observatie"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    regel_sleutel: Mapped[str | None] = mapped_column(default=None)
    regel_omschrijving_raw: Mapped[str | None] = mapped_column(default=None)
    gb_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    btw_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    bron: Mapped[str]
    bron_datum: Mapped[date]
    boekstuk_ref: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
