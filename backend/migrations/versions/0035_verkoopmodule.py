"""Vastly-verkoopfactuur-boekpad (fase 3-kern, koppelcontract §2d v1.10/v1.11).

Het reviewscherm + boekpad voor documenten met soort 'verkoopfactuur' (de intake herkent ze al
sinds migratie 0028): SalesInvoice mét Entity = de échte huurder als RLZ-debiteur (besluit
Peter 2026-08-08 — idempotente debiteur-aanmaak, géén verzameldebiteur), GB per regel
deterministisch uit de UBL (cbc:AccountingCost, BT-133), en de CreditNote-381-tegenboeking
(§2d-creditnota's v1.11, achter config-gate creditnota_381_ingeschakeld, default UIT).

- boekhouding.verkoop_voorstel + verkoop_voorstel_regel — het reviewvoorstel per document:
  deterministisch uit de UBL geprefilld (geen AI — de UBL ís de gestructureerde bron), door de
  controleur te bevestigen. `gb_code` = de ruwe AccountingCost (herleidbaarheid); `ledger_id`
  nullable (regel zonder code = mens kiest, §2d: géén fout). RLS via subquery-op-document
  (zelfde patroon als boekvoorstel/omzet_voorstel).
- boekhouding.verkoop_boeking — registratie per geboekte factuur/creditnota: lokale
  duplicaatbewaking per (administratie, Vastly-factuurnummer, soort) óók op DB-niveau
  (partiële unique index zolang niet gestorneerd), bron voor het nummer-herstel (de
  SalesInvoices-collectie ziet API-facturen niet) én de creditnota-herleiding (een 381 boekt
  alleen tegen een hier bekend, geboekt origineel).

Alle tabellen: RLS + FORCE, GRANT SELECT/INSERT/UPDATE (géén DELETE — niets verdwijnt);
verkoop_voorstel_regel krijgt als werkstaat wél DELETE (opslaan herschrijft de regels, zelfde
afweging als omzet_voorstel_regel/boekvoorstel_regel).

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def _rls_op_administratie(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def _rls_via_document(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (
            EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = {tabel}.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = {tabel}.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    # --- verkoopreview-voorstel per document ----------------------------------------------------
    op.create_table(
        "verkoop_voorstel",
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), primary_key=True),
        sa.Column("debiteur_naam", sa.Text(), nullable=True),
        sa.Column("factuurnummer", sa.Text(), nullable=True),
        sa.Column("factuurdatum", sa.Date(), nullable=True),
        sa.Column("totaalbedrag_incl", sa.Numeric(14, 2), nullable=True),
        sa.Column("is_creditnota", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gecrediteerd_factuurnummer", sa.Text(), nullable=True),
        sa.Column("rlz_boekstuknummer", sa.Text(), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="boekhouding",
    )
    op.create_table(
        "verkoop_voorstel_regel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("boekhouding.verkoop_voorstel.document_id"),
            nullable=False,
        ),
        sa.Column("volgnummer", sa.Integer(), nullable=False),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        sa.Column("netto_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("btw_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("gb_code", sa.Text(), nullable=True),
        sa.Column("ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("taxrate_id", UUID(as_uuid=True), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_verkoop_voorstel_regel_document_id", "verkoop_voorstel_regel", ["document_id"], schema="boekhouding"
    )
    _rls_via_document("verkoop_voorstel")
    _rls_via_document("verkoop_voorstel_regel")
    # Werkstaat: opslaan herschrijft de regels (zelfde DELETE-grant-afweging als
    # omzet_voorstel_regel, migratie 0027). Audit-/tijdlijnsporen blijven append-only.
    op.execute(f"GRANT DELETE ON boekhouding.verkoop_voorstel_regel TO {APP_ROLE}")

    # --- registratie per geboekte verkoopfactuur/creditnota -------------------------------------
    op.create_table(
        "verkoop_boeking",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("factuurnummer", sa.Text(), nullable=False),
        sa.Column("is_creditnota", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("totaalbedrag_incl", sa.Numeric(14, 2), nullable=False),
        sa.Column("debiteur_customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("debiteur_naam", sa.Text(), nullable=False),
        sa.Column("verkoop_rlz_id", UUID(as_uuid=True), nullable=False),
        sa.Column("verkoop_invoice_number", sa.Integer(), nullable=True),
        sa.Column("verkoop_referentie", sa.Text(), nullable=True),
        sa.Column("verkoop_boekstuknummer", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="geboekt"),
        sa.Column("geboekt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("geboekt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gestorneerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gestorneerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("storno_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("factuurnummer <> ''", name="verkoop_boeking_factuurnummer_niet_leeg"),
        sa.CheckConstraint("status IN ('geboekt', 'gestorneerd')", name="verkoop_boeking_status_geldig"),
        sa.CheckConstraint(
            "(status = 'gestorneerd') = (gestorneerd_op IS NOT NULL)", name="verkoop_boeking_storno_consistent"
        ),
        schema="boekhouding",
    )
    # Duplicaatbewaking óók op DB-niveau: hooguit één niet-gestorneerde boeking per
    # (administratie, Vastly-factuurnummer, factuur-of-creditnota).
    op.create_index(
        "ux_verkoop_boeking_actief_per_factuurnummer",
        "verkoop_boeking",
        ["administratie_id", "factuurnummer", "is_creditnota"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status = 'geboekt'"),
    )
    op.create_index("ix_verkoop_boeking_document_id", "verkoop_boeking", ["document_id"], schema="boekhouding")
    _rls_op_administratie("verkoop_boeking")


def downgrade() -> None:
    for tabel in ("verkoop_boeking", "verkoop_voorstel_regel", "verkoop_voorstel"):
        op.execute(f"REVOKE ALL ON boekhouding.{tabel} FROM {APP_ROLE}")
        op.execute(f"DROP POLICY IF EXISTS {tabel}_scope ON boekhouding.{tabel}")
        op.drop_table(tabel, schema="boekhouding")
