"""Omzetmodule (fase 2): kassarapporten → SalesInvoice + kostprijsmemoriaal.

Fundament (mockup #omzetreview + CLAUDE.md "Omzetboekingen"; STAP 0-verificatie 2026-08-07,
verkenning/api-verkenning.md "Omzetmodule STAP 0"):

- boekhouding.document.soort — discriminator 'inkoopfactuur' | 'kassarapport': een kassarapport
  doorloopt dezelfde statusmachine/werkvoorraad, maar krijgt de rapport-extractie en het
  omzetreview-scherm i.p.v. de inkoopflow. TEXT + CHECK (zelfde overweging als vraag.status:
  geen PG-enum-uitbreiding nodig bij een later derde documentsoort).
- boekhouding.omzet_categorie_mapping — categorie→GB+btw-mapping per administratie ("eerste
  keer instellen, daarna onthouden", zelfde principe als het boekingsgeheugen): omzet-GB +
  btw-code + kostprijs-GB per genormaliseerde categorie-sleutel. Deactiveren i.p.v. verwijderen;
  uniek per actieve sleutel per administratie.
- boekhouding.omzet_instelling — per-administratie omzetconfig: RLZ-GUID van de systeemdebiteur
  "Kasomzet" (idempotent aangemaakt bij de eerste boeking), voorraad-tegenrekening voor het
  kostprijsmemoriaal en het gecachte memoriaal-dagboek-GUID (per administratie opgevraagd,
  nooit hardcoden).
- boekhouding.omzet_voorstel + omzet_voorstel_regel — het omzetreview-voorstel per document
  (periode + rapport-totalen; per categorie de gelezen bedragen + gekozen GB/btw/kostprijs-GB).
  RLS via subquery-op-document (zelfde patroon als boekvoorstel, migratie 0008).
- boekhouding.omzet_boeking — registratie per geboekte periode: de duplicaatbewaking-per-periode
  (partiële unique index op (administratie, periode) zolang niet gestorneerd — óók op DB-niveau)
  én de "nooit stil een halve boeking"-werkstaat: status half_geboekt is de zichtbare
  foutstatus als het kostprijsmemoriaal faalde ná een geboekte verkoopfactuur en de storno
  (actie 19) van die verkoop óók faalde — de omzet-reconciliatie rapporteert die rijen.

Alle tabellen: RLS + FORCE, GRANT SELECT/INSERT/UPDATE (géén DELETE — niets verdwijnt).

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0027"
down_revision: str | None = "0026"
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
    # --- documentsoort-discriminator -----------------------------------------------------------
    op.add_column(
        "document",
        sa.Column("soort", sa.Text(), nullable=False, server_default="inkoopfactuur"),
        schema="boekhouding",
    )
    op.create_check_constraint(
        "document_soort_geldig",
        "document",
        "soort IN ('inkoopfactuur', 'kassarapport')",
        schema="boekhouding",
    )

    # --- categorie→GB+btw-mapping per administratie ---------------------------------------------
    op.create_table(
        "omzet_categorie_mapping",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("categorie_sleutel", sa.Text(), nullable=False),
        sa.Column("weergave_naam", sa.Text(), nullable=False),
        sa.Column("omzet_ledger_id", UUID(as_uuid=True), nullable=False),
        sa.Column("taxrate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kostprijs_ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gedeactiveerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gedeactiveerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("categorie_sleutel <> ''", name="omzet_mapping_sleutel_niet_leeg"),
        schema="boekhouding",
    )
    op.create_index(
        "ux_omzet_mapping_actief_per_categorie",
        "omzet_categorie_mapping",
        ["administratie_id", "categorie_sleutel"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("actief"),
    )
    _rls_op_administratie("omzet_categorie_mapping")

    # --- omzetconfig per administratie ----------------------------------------------------------
    op.create_table(
        "omzet_instelling",
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True),
        sa.Column("kasomzet_customer_id", UUID(as_uuid=True), nullable=True),
        sa.Column("kasomzet_naam", sa.Text(), nullable=True),
        sa.Column("voorraad_ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("memoriaal_diary_id", UUID(as_uuid=True), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="boekhouding",
    )
    _rls_op_administratie("omzet_instelling")

    # --- omzetreview-voorstel per document ------------------------------------------------------
    op.create_table(
        "omzet_voorstel",
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), primary_key=True),
        sa.Column("periode_start", sa.Date(), nullable=True),
        sa.Column("periode_eind", sa.Date(), nullable=True),
        sa.Column("rapport_totaal_omzet", sa.Numeric(14, 2), nullable=True),
        sa.Column("rapport_totaal_kostprijs", sa.Numeric(14, 2), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="boekhouding",
    )
    op.create_table(
        "omzet_voorstel_regel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("boekhouding.omzet_voorstel.document_id"),
            nullable=False,
        ),
        sa.Column("volgnummer", sa.Integer(), nullable=False),
        sa.Column("categorie", sa.Text(), nullable=False),
        sa.Column("categorie_sleutel", sa.Text(), nullable=False),
        sa.Column("omzet_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("kostprijs_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("omzet_ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("taxrate_id", UUID(as_uuid=True), nullable=True),
        sa.Column("kostprijs_ledger_id", UUID(as_uuid=True), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_omzet_voorstel_regel_document_id", "omzet_voorstel_regel", ["document_id"], schema="boekhouding"
    )
    _rls_via_document("omzet_voorstel")
    _rls_via_document("omzet_voorstel_regel")
    # Het voorstel is werkstaat (geen audit): opslaan herschrijft de regels — zelfde
    # DELETE-grant als boekvoorstel_regel (migratie 0008). De audit-/tijdlijnsporen zelf
    # blijven append-only.
    op.execute(f"GRANT DELETE ON boekhouding.omzet_voorstel_regel TO {APP_ROLE}")

    # --- registratie per geboekte periode (duplicaatbewaking + half-geboekt-werkstaat) ----------
    op.create_table(
        "omzet_boeking",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("periode_start", sa.Date(), nullable=False),
        sa.Column("periode_eind", sa.Date(), nullable=False),
        sa.Column("totaal_omzet", sa.Numeric(14, 2), nullable=False),
        sa.Column("totaal_kostprijs", sa.Numeric(14, 2), nullable=False),
        sa.Column("verkoop_rlz_id", UUID(as_uuid=True), nullable=False),
        sa.Column("verkoop_invoice_number", sa.Integer(), nullable=True),
        sa.Column("verkoop_referentie", sa.Text(), nullable=True),
        sa.Column("verkoop_boekstuknummer", sa.Text(), nullable=True),
        # Nullable: een rapport zonder kostprijskolom heeft geen kostprijsmemoriaal — dan is de
        # verkoopfactuur het enige RLZ-document van deze boeking.
        sa.Column("memoriaal_rlz_id", UUID(as_uuid=True), nullable=True),
        sa.Column("memoriaal_referentie", sa.Text(), nullable=True),
        sa.Column("memoriaal_boekstuknummer", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="geboekt"),
        sa.Column("half_geboekt_detail", JSONB, nullable=True),
        sa.Column("geboekt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("geboekt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gestorneerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gestorneerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("storno_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('geboekt', 'half_geboekt', 'gestorneerd')", name="omzet_boeking_status_geldig"),
        sa.CheckConstraint(
            "(status = 'gestorneerd') = (gestorneerd_op IS NOT NULL)", name="omzet_boeking_storno_consistent"
        ),
        sa.CheckConstraint(
            "(status = 'half_geboekt') = (half_geboekt_detail IS NOT NULL)",
            name="omzet_boeking_half_geboekt_consistent",
        ),
        sa.CheckConstraint("periode_start <= periode_eind", name="omzet_boeking_periode_geldig"),
        schema="boekhouding",
    )
    # Duplicaatbewaking per periode óók op DB-niveau: hooguit één niet-gestorneerde boeking per
    # exact dezelfde periode. Overlappende (niet-identieke) periodes vangt de harde check in de
    # servicelaag — een EXCLUDE-constraint op daterange zou ook storno-heboekingen blokkeren.
    op.create_index(
        "ux_omzet_boeking_actief_per_periode",
        "omzet_boeking",
        ["administratie_id", "periode_start", "periode_eind"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status IN ('geboekt', 'half_geboekt')"),
    )
    op.create_index("ix_omzet_boeking_document_id", "omzet_boeking", ["document_id"], schema="boekhouding")
    _rls_op_administratie("omzet_boeking")


def downgrade() -> None:
    for tabel in (
        "omzet_boeking",
        "omzet_voorstel_regel",
        "omzet_voorstel",
        "omzet_instelling",
        "omzet_categorie_mapping",
    ):
        op.execute(f"REVOKE ALL ON boekhouding.{tabel} FROM {APP_ROLE}")
        op.execute(f"DROP POLICY IF EXISTS {tabel}_scope ON boekhouding.{tabel}")
        op.drop_table(tabel, schema="boekhouding")
    op.drop_constraint("document_soort_geldig", "document", schema="boekhouding")
    op.drop_column("document", "soort", schema="boekhouding")
