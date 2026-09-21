"""Activa / MVA fase 1 (migratie 0168; AKKOORD Peter 21-09 op docs/ONTWERP_ACTIVA_MVA.md — BESLISSINGEN "ACTIVA /
MVA — FASE 1 GEBOUWD (Peter 21-09)"). Kernprincipe 1: het activaregister leeft in RLZ (`FixedAssets`) — deze
tabellen zijn instelling en koppelrecord, nooit een tweede register.

- `ActivaInstelling`: één rij per administratie (opt-in automatisch aanmaken, activeringsgrens, RLZ-grens
  `FixedAssetAlertAmount`, termijnen/afschrijvingsrekening per categorie, register-probe). Ontbreekt de rij, dan
  gelden de ontwerp-defaults (§8): opt-in UIT, grens € 450 excl., lineair, restwaarde 0.
- `ActivumKoppeling`: document/regel/boek_cyclus ↔ RLZ-activum. Statussen: `gepland` (mens zei "aanmaken" vóór
  het boeken), `aangemaakt` (PUT + terug-lezen gelukt, `rlz_fixed_asset_id` gevuld), `overgeslagen` (mens: niet
  activeren, reden verplicht), `mislukt` (RLZ-write faalde — zichtbaar op de kaart en in het reconciliatieblok,
  retry), `beoordelen` (factuur gestorneerd — het activum wordt NOOIT verwijderd, de mens beoordeelt in RLZ).
  Geen DELETE-grant: niets verdwijnt stil.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class KoppelingStatus(enum.StrEnum):
    GEPLAND = "gepland"
    AANGEMAAKT = "aangemaakt"
    OVERGESLAGEN = "overgeslagen"
    MISLUKT = "mislukt"
    BEOORDELEN = "beoordelen"


class KoppelingHerkomst(enum.StrEnum):
    MENS = "mens"
    AUTOMATISCH = "automatisch"


class ActivaInstelling(Base):
    __tablename__ = "activa_instelling"
    __table_args__ = ({"schema": "boekhouding"},)

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform.administratie.id", name="fk_activa_instelling_administratie"),
        primary_key=True,
    )
    # Autoboek-patroon: default UIT; guard-test op het afwezig-pad (`@pytest.mark.afwezig_pad("activa_instelling.…")`).
    automatisch_aanmaken_ingeschakeld: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    activeringsgrens: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("450.00"), server_default="450.00"
    )
    grens_rlz: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    grens_rlz_gelezen_op: Mapped[datetime | None] = mapped_column(default=None)
    termijnen: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    afschrijving_ledgers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    register_leesbaar: Mapped[bool | None] = mapped_column(default=None)
    register_geprobeerd_op: Mapped[datetime | None] = mapped_column(default=None)
    register_fout: Mapped[str | None] = mapped_column(default=None)
    gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform.gebruiker.id", name="fk_activa_instelling_gewijzigd_door"),
        default=None,
    )
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now())


class ActivumKoppeling(Base):
    __tablename__ = "activum_koppeling"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "regel_volgnummer", "boek_cyclus", name="ux_activum_koppeling_document_regel_cyclus"
        ),
        CheckConstraint(
            "status IN ('gepland', 'aangemaakt', 'overgeslagen', 'mislukt', 'beoordelen')",
            name="ck_activum_koppeling_status",
        ),
        CheckConstraint("herkomst IN ('mens', 'automatisch')", name="ck_activum_koppeling_herkomst"),
        CheckConstraint("aanschafwaarde >= 0", name="ck_activum_koppeling_aanschafwaarde"),
        CheckConstraint("termijn_maanden > 0", name="ck_activum_koppeling_termijn"),
        Index("ix_activum_koppeling_administratie_id", "administratie_id"),
        Index("ix_activum_koppeling_status", "administratie_id", "status"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id", name="fk_activum_koppeling_administratie")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id", name="fk_activum_koppeling_document")
    )
    regel_volgnummer: Mapped[int]
    boek_cyclus: Mapped[int] = mapped_column(default=0, server_default="0")
    status: Mapped[str]
    herkomst: Mapped[str] = mapped_column(default=KoppelingHerkomst.MENS.value, server_default="mens")
    rlz_fixed_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    rlz_receipt_number: Mapped[str | None] = mapped_column(default=None)
    categorie: Mapped[str]
    termijn_maanden: Mapped[int]
    methode_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    methode_naam: Mapped[str | None] = mapped_column(default=None)
    aanschafwaarde: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    restwaarde: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), server_default="0.00")
    aanschafdatum: Mapped[date]
    omschrijving: Mapped[str]
    balans_ledger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    afschrijving_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    reden: Mapped[str | None] = mapped_column(default=None)
    door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id", name="fk_activum_koppeling_door"), default=None
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now())
