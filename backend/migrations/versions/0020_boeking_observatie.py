"""Boekingsgeheugen: append-only observaties per (administratie, crediteur[, regel]).

Fundament van het boekingsgeheugen (CLAUDE.md: "RLZ-historie + app-correcties; correcties wegen
zwaarder"). Elke rij is één waarneming "deze crediteur(+regelsoort) werd op deze GB/btw/project
geboekt" — nooit muteren, alleen toevoegen; de voorstel-engine (app/geheugen/engine.py) weegt ze
met bron-gewicht × recency-verval. `bron` = 'rlz_seed' (eenmalige/herhaalbare ingest uit RLZ's
PurchaseInvoices+Lines — bewust NIET JournalEntries, zie BOUWPLAN/besluit 2026-07-13) of 'app'
(leerlus: door een mens bevestigde boeking via actie 17).

`id` is een deterministische UUIDv5 over de bronregel (seed: RLZ-line-id; app: document+regel) —
dat maakt seed én leerlus idempotent en hervatbaar zonder aparte dedup-tabel. `regel_sleutel` is
de genormaliseerde token-set van de regelomschrijving (app/geheugen/normalisatie.py), NULL voor
leverancier-niveau-observaties (samengevoegde boekingen). De rauwe omschrijving reist mee voor
menselijke controle, maar hoort nooit in logs/URL's.

RLS conform het bestaande patroon (FORCE, scope op administratie).

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "boeking_observatie",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("regel_sleutel", sa.Text(), nullable=True),
        sa.Column("regel_omschrijving_raw", sa.Text(), nullable=True),
        sa.Column("gb_id", UUID(as_uuid=True), nullable=False),
        sa.Column("btw_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("bron_datum", sa.Date(), nullable=False),
        sa.Column("boekstuk_ref", sa.Text(), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("bron IN ('rlz_seed', 'app')", name="boeking_observatie_bron_geldig"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_boeking_observatie_admin_vendor_sleutel",
        "boeking_observatie",
        ["administratie_id", "vendor_id", "regel_sleutel"],
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.boeking_observatie ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.boeking_observatie FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY boeking_observatie_scope ON boekhouding.boeking_observatie
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    # Append-only: bewust geen UPDATE-grant — correcties zijn nieuwe observaties, nooit mutaties.
    op.execute(f"GRANT SELECT, INSERT ON boekhouding.boeking_observatie TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.boeking_observatie FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS boeking_observatie_scope ON boekhouding.boeking_observatie")
    op.drop_index("ix_boeking_observatie_admin_vendor_sleutel", "boeking_observatie", schema="boekhouding")
    op.drop_table("boeking_observatie", schema="boekhouding")
