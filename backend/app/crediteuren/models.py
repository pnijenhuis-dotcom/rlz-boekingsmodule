"""Tabellen crediteuren-dubbelen v2 (migratie 0100, design-ronde 03-09):

- `boekhouding.crediteur_dubbel_afmelding` — "Geen dubbel — afmelden" (ontwerpnotitie ⑤): per administratie
  één rij per COMBINATIE (gesorteerde vendor-id's); het cluster verdwijnt uit de lijst en komt voor exact
  die combinatie nooit terug. Een nieuw lid in het cluster = nieuwe combinatie = wél weer zichtbaar.
- `boekhouding.crediteur_archiveer_werklijst` — de uitkomst van "Voorkeur kiezen & rest archiveren…" op het
  pad "API werkt niet" (STAP-0 03-09, api-verkenning "Vendor archiveren via API"): één regel
  "klaargezet — archiveer in RLZ: <namen>" mét status open/gedaan; de dagelijkse hertoets (sync-alles) leest
  de Vendors in RLZ en vinkt af, een mens kan óók handmatig afvinken (audit). Nooit verwijderen — geen
  DELETE-grant."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

SLEUTEL_SOORTEN = ("btw_nummer", "kvk_nummer", "iban", "naam")
WERKLIJST_STATUSSEN = ("open", "gedaan")


def combinatie_sleutel(vendor_ids: list[uuid.UUID] | set[uuid.UUID] | tuple[uuid.UUID, ...]) -> str:
    """Genormaliseerde combinatie: gesorteerde vendor-id's, komma-gescheiden — de afmeld-sleutel."""
    return ",".join(sorted(str(v) for v in vendor_ids))


class CrediteurDubbelAfmelding(Base):
    __tablename__ = "crediteur_dubbel_afmelding"
    __table_args__ = (
        UniqueConstraint("administratie_id", "combinatie", name="uq_crediteur_dubbel_afmelding_combinatie"),
        Index("ix_crediteur_dubbel_afmelding_administratie_id", "administratie_id"),
        CheckConstraint(
            "sleutel_soort IN ('btw_nummer', 'kvk_nummer', 'iban', 'naam')",
            name="ck_crediteur_dubbel_afmelding_soort",
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    sleutel_soort: Mapped[str]
    sleutel: Mapped[str]
    combinatie: Mapped[str]
    vendor_ids: Mapped[list] = mapped_column(JSONB)
    reden: Mapped[str]
    afgemeld_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    afgemeld_op: Mapped[datetime] = mapped_column(server_default=func.now())


class CrediteurArchiveerWerklijst(Base):
    __tablename__ = "crediteur_archiveer_werklijst"
    __table_args__ = (
        Index("ix_crediteur_archiveer_werklijst_administratie_id", "administratie_id"),
        CheckConstraint("status IN ('open', 'gedaan')", name="ck_crediteur_archiveer_werklijst_status"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    voorkeur_vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    voorkeur_naam: Mapped[str | None] = mapped_column(default=None)
    # [{"vendor_id": "...", "naam": "..."}] — de te archiveren crediteuren (RLZ-klikwerk).
    te_archiveren: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(default="open")
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gedaan_op: Mapped[datetime | None] = mapped_column(default=None)
    gedaan_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gedaan_bron: Mapped[str | None] = mapped_column(default=None)  # 'hertoets' | 'handmatig'
    laatste_hertoets_op: Mapped[datetime | None] = mapped_column(default=None)
    # {"<vendor_id>": "gearchiveerd" | "actief" | "fout: …"} — stand van de laatste hertoets per crediteur.
    hertoets_detail: Mapped[dict | None] = mapped_column(JSONB, default=None)


AFHANDELING_BRONNEN = ("auto", "mens")


class CrediteurDubbelAfhandeling(Base):
    """Append-only log per afgehandeld dubbel-cluster (blok B13 07-09, migratie 0117): voorkeur + verliezers +
    sleutels + classificatie-reden + de OUDE stand van alles wat verhuisd/gewijzigd is (`verhuisd`), zodat
    `draai_terug` de markering op `vendor_cache`, het kenmerk en de hervertaalde boekvoorstellen herstelt.
    Geheugen-/IBAN-kopieën zijn append-only en blijven staan (zichtbaar in `verhuisd` + audit). De enige UPDATE
    is `teruggedraaid_*`; geen DELETE-grant."""

    __tablename__ = "crediteur_dubbel_afhandeling"
    __table_args__ = (
        Index("ix_crediteur_dubbel_afhandeling_administratie_id", "administratie_id"),
        CheckConstraint("bron IN ('auto', 'mens')", name="ck_crediteur_dubbel_afhandeling_bron"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    bron: Mapped[str]
    voorkeur_vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    voorkeur_naam: Mapped[str | None] = mapped_column(default=None)
    # [{"vendor_id": "...", "naam": "..."}]
    verliezers: Mapped[list] = mapped_column(JSONB)
    # [{"soort": "naam", "sleutel": "wola"}, ...]
    sleutels: Mapped[list] = mapped_column(JSONB)
    classificatie_reden: Mapped[str]
    # {"geheugen": [[oud_id, nieuw_id], ...], "kenmerk_oud": {...} | None, "ibans": [...],
    #  "boekvoorstellen": [{"document_id": "...", "van_vendor_id": "..."}]}
    verhuisd: Mapped[dict] = mapped_column(JSONB)
    afgehandeld_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    afgehandeld_op: Mapped[datetime] = mapped_column(server_default=func.now())
    teruggedraaid_op: Mapped[datetime | None] = mapped_column(default=None)
    teruggedraaid_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    teruggedraaid_reden: Mapped[str | None] = mapped_column(default=None)
