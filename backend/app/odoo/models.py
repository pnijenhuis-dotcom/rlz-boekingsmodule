"""Odoo-adapter-modellen (migratie 0101): koppeling+credential per administratie (platform-schema,
patroon rlz_credential) en de drie boekhouding-mappingtabellen (RLS per administratie)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class OdooKoppeling(Base):
    """Koppeling-record + credential voor een Odoo-administratie (besluit 0016: koppeling per
    administratie, secret uitsluitend versleuteld — envelope zoals RlzCredential; de API-key komt
    nooit terug in een response, log of audit). `company_id` is de heilige poort: élke write draagt
    'm expliciet en wordt ná de write terug-gelezen. De dagboek-/plan-id's worden bij de probe
    vastgesteld en hier vastgelegd — de boekmotor raadt nooit een dagboek."""

    __tablename__ = "odoo_koppeling"
    __table_args__ = (CheckConstraint("company_id > 0", name="ck_odoo_koppeling_company"),)

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    odoo_url: Mapped[str]
    company_id: Mapped[int] = mapped_column(Integer)
    company_naam: Mapped[str | None] = mapped_column(default=None)
    api_gebruiker: Mapped[str | None] = mapped_column(default=None)
    api_key_ciphertext: Mapped[bytes] = mapped_column(BYTEA)
    wrapped_data_key: Mapped[bytes] = mapped_column(BYTEA)
    api_key_verloopt_op: Mapped[date | None] = mapped_column(default=None)
    journal_purchase_id: Mapped[int | None] = mapped_column(Integer, default=None)
    journal_general_id: Mapped[int | None] = mapped_column(Integer, default=None)
    journal_sale_id: Mapped[int | None] = mapped_column(Integer, default=None)
    analytic_plan_id: Mapped[int | None] = mapped_column(Integer, default=None)
    probe_rapport: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), default=None)
    probe_op: Mapped[datetime | None] = mapped_column(default=None)
    #: Blok D (migratie 0102): uitsluitend LEZEN — mag óók bij een RLZ-administratie (Odoo = leesbron voor de
    #: voorraad-uitstroom, boeken blijft in RLZ); `odoo_client_voor` dwingt dan altijd read_only af.
    alleen_lezen: Mapped[bool] = mapped_column(default=False, server_default="false")
    #: Vanaf deze factuurdatum is Odoo de bron van de verkoop-uitstroom (RLZ-facturen ≥ knip tellen niet meer).
    voorraad_knip_datum: Mapped[date | None] = mapped_column(default=None)
    #: Blok E (migratie 0104): overstap van een bestaande RLZ-administratie — vanaf deze factuurdatum boekt de
    #: administratie in Odoo (adapter-poort: factuurdatum < overgangsdatum = leesbare weigering, hoort nog in
    #: RLZ). NULL = geen poort (nieuwe Odoo-administratie zonder RLZ-verleden, of alleen-lezen-koppeling).
    overgangsdatum: Mapped[date | None] = mapped_column(default=None)
    #: Het oude RLZ-administratie-id vóór de overstap (`administratie.rlz_admin_id` draagt daarna de sentinel).
    rlz_admin_id_voor_overstap: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class OdooIdKoppeling(Base):
    """Odoo-int-id ↔ lokale UUID per (administratie, model) — gevuld door de stamgegevens-sync
    (`app/odoo/sync.py`), gelezen door de boekmotor (UUID → int, fail-loud als afwezig)."""

    __tablename__ = "odoo_id_koppeling"
    __table_args__ = (
        UniqueConstraint("administratie_id", "lokaal_id", name="uq_odoo_id_koppeling_lokaal"),
        {"schema": "boekhouding"},
    )

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    odoo_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lokaal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    naam: Mapped[str | None] = mapped_column(default=None)
    laatst_gezien_op: Mapped[datetime] = mapped_column(server_default=func.now())


class OdooDocumentKoppeling(Base):
    """(document, boek_cyclus, soort) → account.move. Het idempotentie-anker van de Odoo-boekmotor
    (STAP-0 §3.1: zoek-vóór-create + eigen id-mapping) én de kruisverwijzing van een reversal
    (`reversal_van_move_id`). `state` is een cache van de laatst terug-gelezen Odoo-stand."""

    __tablename__ = "odoo_document_koppeling"
    __table_args__ = (
        UniqueConstraint(
            "administratie_id", "document_id", "boek_cyclus", "soort", name="uq_odoo_document_koppeling_cyclus"
        ),
        CheckConstraint("soort IN ('boeking', 'tegenboeking')", name="ck_odoo_document_koppeling_soort"),
        Index("ix_odoo_document_koppeling_administratie_id", "administratie_id"),
        Index("ix_odoo_document_koppeling_move", "company_id", "odoo_move_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    boek_cyclus: Mapped[int] = mapped_column(Integer)
    soort: Mapped[str] = mapped_column(String(16))
    odoo_move_id: Mapped[int] = mapped_column(Integer)
    odoo_naam: Mapped[str | None] = mapped_column(default=None)
    odoo_move_type: Mapped[str] = mapped_column(String(16))
    company_id: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    reversal_van_move_id: Mapped[int | None] = mapped_column(Integer, default=None)
    detail: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class OdooProductKoppeling(Base):
    """Materiaalcatalogus-product ↔ Odoo product.product (brug voor regelniveau-data; eis Peter
    03-09). `bron` = 'gevonden' (lookup op naam/code, nooit dubbel aanmaken) of 'aangemaakt'."""

    __tablename__ = "odoo_product_koppeling"
    __table_args__ = (
        CheckConstraint("bron IN ('gevonden', 'aangemaakt')", name="ck_odoo_product_koppeling_bron"),
        {"schema": "boekhouding"},
    )

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    materiaal_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.materiaal_product.id"), primary_key=True
    )
    odoo_product_id: Mapped[int] = mapped_column(Integer)
    odoo_template_id: Mapped[int | None] = mapped_column(Integer, default=None)
    default_code: Mapped[str | None] = mapped_column(default=None)
    naam: Mapped[str | None] = mapped_column(default=None)
    bron: Mapped[str] = mapped_column(String(16))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class OdooRekeningMapping(Base):
    """Door de MENS bevestigde vertaling RLZ-grootboek/-btw → Odoo-account/-tax per administratie
    (migratie 0111, blok A Odoo-afrondingsrun 04-09). Het boekingsgeheugen draagt RLZ-UUID's van vóór de
    overstap; `app/odoo/mapping.py::vertaal_observaties` vertaalt ze mét deze tabel VÓÓR de engine weegt,
    zodat `app_bevestigd` behouden blijft (de mens bevestigde het bóékgedrag, niet het rekeningnummer).

    APPEND-ONLY (GRANT zonder UPDATE/DELETE): een correctie is een nieuwe rij met `versie + 1`; de
    geldende rij is de hoogste versie per (administratie, soort, rlz_id). `odoo_id` 0 = de synthetische
    "Geen btw (0%)" (alleen soort 'btw'). `bron` = hoe de rij tot stand kwam: `zelfde_code` (groen
    voorstel, exact gelijke code), `code_verlengd` (RLZ-code + "00", oranje — bevestigd), `tarief`
    (btw op percentage/verlegd/vrijgesteld) of `handmatig` (mens koos zelf)."""

    __tablename__ = "odoo_rekening_mapping"
    __table_args__ = (
        UniqueConstraint("administratie_id", "soort", "rlz_id", "versie", name="uq_odoo_rekening_mapping_versie"),
        CheckConstraint("soort IN ('grootboek', 'btw')", name="ck_odoo_rekening_mapping_soort"),
        CheckConstraint(
            "bron IN ('zelfde_code', 'code_verlengd', 'tarief', 'handmatig')", name="ck_odoo_rekening_mapping_bron"
        ),
        CheckConstraint("versie >= 1", name="ck_odoo_rekening_mapping_versie"),
        CheckConstraint("odoo_id >= 0", name="ck_odoo_rekening_mapping_odoo_id"),
        Index("ix_odoo_rekening_mapping_administratie_id", "administratie_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    soort: Mapped[str] = mapped_column(String(16))
    rlz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rlz_code: Mapped[str | None] = mapped_column(default=None)
    rlz_naam: Mapped[str | None] = mapped_column(default=None)
    odoo_lokaal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    odoo_id: Mapped[int] = mapped_column(Integer)
    odoo_code: Mapped[str | None] = mapped_column(default=None)
    odoo_naam: Mapped[str | None] = mapped_column(default=None)
    bron: Mapped[str] = mapped_column(String(16))
    versie: Mapped[int] = mapped_column(Integer)
    bevestigd_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    bevestigd_op: Mapped[datetime] = mapped_column(server_default=func.now())
