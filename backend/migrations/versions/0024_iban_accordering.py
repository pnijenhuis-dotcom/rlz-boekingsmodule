"""IBAN-wissel vier-ogen-accordering (docs/ontwerp/iban-wissel-accordering.md, goedgekeurde
flow Cowork-mockup 2026-07-15).

Drie onderdelen:
1. Nieuwe document-status `wacht_op_iban_accordering` (ALTER TYPE ... ADD VALUE, zelfde
   patroon als migratie 0015): document geblokkeerd zolang de accordering open staat.
2. `boekhouding.iban_accordeur`: instelling per administratie wie IBAN-wissels mag
   accorderen; lege set → actieve beheerders (servicelaag).
3. `boekhouding.iban_accordering`: het accordering-record — append-only historie (geen
   DELETE-grant), één open accordering per document (partiële unique index), reden verplicht
   bij afwijzen (CHECK), vier-ogen óók op DB-niveau (CHECK besloten_door <> aangevraagd_door).

`status_voor_accordering` is de document-status van vóór het aanbieden: accorderen herstelt
exact díé herkomst — zelfde status_voor_*-patroon als vraag (0022) en afwijzing (0023).
RLS conform het standaardpatroon.

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    # PG12+: ADD VALUE mag in een transactie zolang de nieuwe waarde niet in dezelfde
    # transactieketen in DDL gebruikt wordt (zie migratie 0015) — de tabellen hieronder
    # refereren de enum bewust niet (status_voor_accordering is TEXT + CHECK).
    op.execute("ALTER TYPE boekhouding.document_status ADD VALUE IF NOT EXISTS 'wacht_op_iban_accordering'")

    op.create_table(
        "iban_accordeur",
        sa.Column(
            "administratie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.administratie.id"),
            primary_key=True,
        ),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), primary_key=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.iban_accordeur ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.iban_accordeur FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY iban_accordeur_scope ON boekhouding.iban_accordeur
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    # DELETE wél toegestaan: dit is een instelling (set-vervanging), geen historie —
    # de historie zit in het audit_event per wijziging.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON boekhouding.iban_accordeur TO {APP_ROLE}")

    op.create_table(
        "iban_accordering",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("nieuw_iban", sa.Text(), nullable=False),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column(
            "aangevraagd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False
        ),
        sa.Column("aangevraagd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status_voor_accordering", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("besloten_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("besloten_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("afwijs_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('open', 'geaccordeerd', 'afgewezen')", name="iban_accordering_status_geldig"),
        sa.CheckConstraint("soort IN ('regulier', 'g_rekening')", name="iban_accordering_soort_geldig"),
        sa.CheckConstraint("btrim(nieuw_iban) <> ''", name="iban_accordering_iban_niet_leeg"),
        sa.CheckConstraint(
            "status_voor_accordering IN ('te_controleren', 'handmatig_afmaken', 'klaar_om_te_boeken')",
            name="iban_accordering_herkomst_herstelbaar",
        ),
        # Vier-ogen óók op DB-niveau: de besluter is nooit de aanvrager.
        sa.CheckConstraint(
            "besloten_door IS NULL OR besloten_door <> aangevraagd_door",
            name="iban_accordering_vier_ogen",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND besloten_door IS NULL AND besloten_op IS NULL AND afwijs_reden IS NULL)"
            " OR (status = 'geaccordeerd' AND besloten_door IS NOT NULL AND besloten_op IS NOT NULL"
            " AND afwijs_reden IS NULL)"
            " OR (status = 'afgewezen' AND besloten_door IS NOT NULL AND besloten_op IS NOT NULL"
            " AND btrim(afwijs_reden) <> '')",
            name="iban_accordering_besluit_consistent",
        ),
        schema="boekhouding",
    )
    # Eén open accordering per document tegelijk — op DB-niveau afgedwongen (zelfde reden als
    # vraag/afwijzing: twee gelijktijdige requests kunnen de service-check allebei passeren).
    op.create_index(
        "iban_accordering_een_open_per_document",
        "iban_accordering",
        ["document_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.execute("ALTER TABLE boekhouding.iban_accordering ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.iban_accordering FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY iban_accordering_scope ON boekhouding.iban_accordering
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.iban_accordering TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.iban_accordering FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS iban_accordering_scope ON boekhouding.iban_accordering")
    op.drop_index("iban_accordering_een_open_per_document", table_name="iban_accordering", schema="boekhouding")
    op.drop_table("iban_accordering", schema="boekhouding")
    op.execute(f"REVOKE ALL ON boekhouding.iban_accordeur FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS iban_accordeur_scope ON boekhouding.iban_accordeur")
    op.drop_table("iban_accordeur", schema="boekhouding")
    # De enum-waarde 'wacht_op_iban_accordering' blijft staan: PostgreSQL kent geen
    # ALTER TYPE ... DROP VALUE (zelfde beperking als migratie 0015).
