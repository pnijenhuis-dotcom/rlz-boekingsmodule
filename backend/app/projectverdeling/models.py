from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Projectverdeling(Base):
    """Eén actuele projectverdeling per document (migratie 0107, mockup projectverdeling-en-
    regelvoorstellen.html blok 1). `vaste_regels` = [{project_id, bedrag, hint}], `verdeling` = de berekende
    delen [{project_id, wijze, bedrag, aandeel, omzet}], `omzetstanden` = het snapshot per project dat bij
    het BOEKEN bevroren wordt (①, audit + herleidbaarheid). Status `voorstel` wordt bij elke lezing live
    herrekend uit het actuele boekvoorstel + de omzet-cache; `geboekt` is bevroren (boek_cyclus); `vervallen`
    = de mens heeft de verdeling weggehaald (nooit een DELETE). De hercontrole (⑥) schrijft de laatste
    herberekening + de afwijking in % terug; boven de administratie-drempel is `hercontrole_verdeling` gevuld
    (het signaal mét actie "Herverdelen…")."""

    __tablename__ = "projectverdeling"
    __table_args__ = (
        CheckConstraint("status IN ('voorstel', 'geboekt', 'vervallen')", name="ck_projectverdeling_status"),
        CheckConstraint("pro_rato_soort IN ('maand', 'jaar')", name="ck_projectverdeling_pro_rato_soort"),
        CheckConstraint(
            "hercontrole_bevinding IS NULL OR hercontrole_bevinding IN ('omzet_ontbreekt')",
            name="ck_projectverdeling_hercontrole_bevinding",
        ),
        UniqueConstraint("document_id", name="uq_projectverdeling_document"),
        Index("ix_projectverdeling_administratie_id", "administratie_id"),
        Index(
            "ix_projectverdeling_hercontrole_signaal",
            "administratie_id",
            "hercontrole_afwijking_pct",
            postgresql_where=text("status = 'geboekt' AND hercontrole_afwijking_pct IS NOT NULL"),
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    vaste_regels: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    pro_rato_periode: Mapped[date | None] = mapped_column(default=None)
    #: D4 07-09 (migratie 0119): 'maand' = pro_rato_periode is de eerste dag van de omzetmaand; 'jaar' = 1 januari
    #: van het jaar waarvan de AFGESLOTEN maanden meetellen (mockup-notitie ⑩).
    pro_rato_soort: Mapped[str] = mapped_column(default="maand", server_default="maand")
    pro_rato_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    verdeling: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    omzetstanden: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(default="voorstel", server_default="voorstel")
    geboekt_op: Mapped[datetime | None] = mapped_column(default=None)
    boek_cyclus: Mapped[int | None] = mapped_column(default=None)
    hercontrole_op: Mapped[datetime | None] = mapped_column(default=None)
    hercontrole_afwijking_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), default=None)
    #: Blok 10 herstelrun 08-09: `none_as_null=True` — een expliciete `= None` (bij boeken/opslaan/onder de drempel)
    #: moet SQL NULL worden, geen JSON `null`; tot 08-09 gold élke pas geboekte verdeling daardoor als "signaal"
    #: (IS NOT NULL was waar) mét 0 % en een lege nieuwe verdeling (Universal, 5 rijen). Lezers: jsonb_typeof = 'array'.
    hercontrole_verdeling: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), default=None)
    #: Blok 10 (migratie 0124): eigen bevinding i.p.v. een herverdeling — 'omzet_ontbreekt' = geen enkel project mét
    #: omzet in de referentieperiode (cijfers-sync nog niet gedraaid of niets geboekt); actie = cijfers-sync starten,
    #: herverdelen geblokkeerd. NULL = geen bevinding.
    hercontrole_bevinding: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
