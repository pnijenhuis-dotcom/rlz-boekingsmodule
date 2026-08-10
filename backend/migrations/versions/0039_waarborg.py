"""VASTLY-WAARBORG-intake + memoriaal-boekpad (blok E grote opdracht 2026-08-10;
koppelcontract §2d-waarborgroute, velddefinitie DEFINITIEF v1.11).

- document.soort krijgt de vierde waarde 'waarborg' (TEXT + CHECK, patroon 0027/0028).
- boekhouding.waarborg_bericht: de contractvelden per herkend bericht (brongegeven) + de éne
  menselijke keuze (tegenrekening van het saldo-0-memoriaal) + RLZ-registratie. `bericht_id`
  DB-uniek = de idempotentiesleutel uit v1.11. RLS op administratie (patroon 0035), GRANT
  zonder DELETE (niets verdwijnt).

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.execute("ALTER TABLE boekhouding.document DROP CONSTRAINT document_soort_geldig")
    op.create_check_constraint(
        "document_soort_geldig",
        "document",
        "soort IN ('inkoopfactuur', 'kassarapport', 'verkoopfactuur', 'waarborg')",
        schema="boekhouding",
    )

    op.create_table(
        "waarborg_bericht",
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("bericht_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("schema_versie", sa.Text(), nullable=True),
        sa.Column("verhuurder_entiteit", sa.Text(), nullable=False),
        sa.Column("rlz_admin_id_hint", sa.Text(), nullable=True),
        sa.Column("contract_referentie", sa.Text(), nullable=False),
        sa.Column("huurder", sa.Text(), nullable=False),
        sa.Column("bedrag", sa.Numeric(12, 2), nullable=False),
        sa.Column("richting", sa.Text(), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("balans_gb_code", sa.Text(), nullable=False),
        sa.Column("tegenrekening_ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("rlz_boekstuknummer", sa.Text(), nullable=True),
        sa.Column("geboekt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("geboekt_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("richting IN ('ontvangst', 'terugbetaling')", name="waarborg_richting_geldig"),
        sa.CheckConstraint("bedrag > 0", name="waarborg_bedrag_positief"),
        sa.CheckConstraint("status IN ('open', 'geboekt')", name="waarborg_status_geldig"),
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.waarborg_bericht ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.waarborg_bericht FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY waarborg_bericht_scope ON boekhouding.waarborg_bericht
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.waarborg_bericht TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS waarborg_bericht_scope ON boekhouding.waarborg_bericht")
    op.drop_table("waarborg_bericht", schema="boekhouding")
    op.execute("ALTER TABLE boekhouding.document DROP CONSTRAINT document_soort_geldig")
    op.create_check_constraint(
        "document_soort_geldig",
        "document",
        "soort IN ('inkoopfactuur', 'kassarapport', 'verkoopfactuur')",
        schema="boekhouding",
    )
