"""Opslag van de deterministische extractie-templates (best-practice-besluit 2, 31-08; migratie 0094).

`boekhouding.extractie_template`: één rij per crediteur-sleutel. Sleutel = het crediteur-kenmerk
(btw-nummer, anders KvK-nummer — dan werkt het template over administraties heen: dezelfde
leverancier stuurt dezelfde factuurlayout naar elke klant), anders administratie + crediteur.

BEWUST GEEN RLS: een template bevat uitsluitend layout-metadata van de LEVERANCIER (ankerwoorden
zoals "Factuurnummer"/"Totaal incl. btw", het vormpatroon van het factuurnummer, de geleerde
btw-percentages) — geen klantgegevens, geen bedragen, geen referenties, geen documenttekst. Juist het
delen over administraties heen (kenmerk-sleutel) is de bedoeling. `geleerd_uit` draagt alleen
opake document-id's (herleidbaarheid in de audit). Rijen worden nooit verwijderd: ongeldig =
`geldig=false` mét reden; opnieuw leren = zelfde rij, `versie` + 1 (de audit-events dragen de historie).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class ExtractieTemplate(Base):
    __tablename__ = "extractie_template"
    __table_args__ = (
        UniqueConstraint("sleutel", name="uq_extractie_template_sleutel"),
        CheckConstraint(
            "sleutel_soort IN ('btw_nummer', 'kvk_nummer', 'administratie_vendor')",
            name="ck_extractie_template_sleutel_soort",
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # "btw:NL001234567B01" | "kvk:12345678" | "adm:<administratie_id>:<vendor_id>"
    sleutel: Mapped[str]
    sleutel_soort: Mapped[str]  # 'btw_nummer' | 'kvk_nummer' | 'administratie_vendor'
    # Administratie/crediteur waaruit (het laatst) geleerd is — informatief; de sleutel bepaalt het gebruik.
    administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    definitie: Mapped[dict] = mapped_column(JSONB)
    geleerd_uit: Mapped[list] = mapped_column(JSONB)
    geleerd_op: Mapped[datetime] = mapped_column(server_default=func.now())
    versie: Mapped[int] = mapped_column(server_default=text("1"), default=1)
    geldig: Mapped[bool] = mapped_column(default=True)
    ongeldig_op: Mapped[datetime | None] = mapped_column(default=None)
    ongeldig_reden: Mapped[str | None] = mapped_column(default=None)
    gebruikt_aantal: Mapped[int] = mapped_column(server_default=text("0"), default=0)
    laatst_gebruikt_op: Mapped[datetime | None] = mapped_column(default=None)
