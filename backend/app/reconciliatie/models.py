from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class ReconciliatieBron(enum.StrEnum):
    """Welke van de drie reconciliaties de afwijking meldde. Bewust een eigen discriminator en
    geen documentsoort: de bank-reconciliatie kent helemaal geen document, de omzet-variant
    rapporteert per boeking."""

    DOCUMENTEN = "documenten"
    BANK = "bank"
    OMZET = "omzet"


class ReconciliatieAcceptatie(Base):
    """Eén beoordeelde-en-bewust-blijvende afwijking (migratie 0042).

    Waarom dit bestaat: een afwijking die terecht is maar niet meer opgelost gaat worden — het
    klassieke geval is een testboeking die een mens ná een storno in de RLZ-UI heeft opgeruimd,
    waardoor ons lokale GEBOEKT-document elke ochtend opnieuw als `ontbreekt_in_rlz` binnenkomt.
    Zonder acceptatie blijft die ruis staan, went het kantoor eraan en sterft de vangrail.

    Drie harde eigenschappen, in lijn met "niets verdwijnt stil":
    1. **Acceptatie onderdrukt niets.** De afwijking blijft in elk rapport zichtbaar, alleen met
       de markering GEACCEPTEERD; ze telt niet mee in de exit-code.
    2. **Acceptatie is zo smal als de afwijking zelf.** `vingerafdruk` is een hash over
       (bron, soort, detail): verandert het detail — ander bedrag, andere RLZ-status, ineens een
       500 i.p.v. een 404 — dan matcht de acceptatie niet meer en staat het signaal er gewoon
       weer. Fail-loud is hier de veilige richting.
    3. **Acceptatie is nooit een delete.** Intrekken zet `ingetrokken_op/-door`; de rij blijft
       staan (append-only-gedachte, GRANT zonder DELETE).

    Reden is verplicht en gaat mét actor in het audit_event — zelfde discipline als afwijzen
    met verplichte reden in de werkvoorraad."""

    __tablename__ = "reconciliatie_acceptatie"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    bron: Mapped[str] = mapped_column()
    # Het record waar de meldende reconciliatie over sprak: document_id (documenten),
    # bankboeking-/afletteropdracht-id (bank) of omzetboeking-id (omzet). Bewust géén FK — de
    # drie bronnen wijzen naar drie verschillende tabellen.
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    soort: Mapped[str] = mapped_column()
    vingerafdruk: Mapped[str] = mapped_column()
    # De detailtekst zoals hij op het moment van accepteren luidde — puur voor leesbaarheid in
    # rapport en audit; de vingerafdruk is de sleutel.
    detail: Mapped[str] = mapped_column()
    reden: Mapped[str] = mapped_column()
    geaccepteerd_door: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id")
    )
    geaccepteerd_op: Mapped[datetime] = mapped_column(server_default=func.now())
    ingetrokken_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)
