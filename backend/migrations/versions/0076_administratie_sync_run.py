"""Eerste-sync-run voor een via de UI aangesloten administratie (feedbackronde 26-08 punt 5 —
"Administratie toevoegen"-wizard, besluit Peter 26-08).

`boekhouding.administratie_sync_run`: het bank-sync-run-patroon (0071) toegepast op de
onboarding — ná het opslaan van een nieuwe administratie start de eerste sync (Ledgers/TaxRates/
Vendors/Projects/PaymentAccounts) als achtergrondrun met status PER ONDERDEEL (`onderdelen`
JSONB: {naam: {status, aangemaakt, bijgewerkt, fout}}), zichtbaar in de wizard via 202+poll.
RLS per administratie + GRANT zonder DELETE (niets verdwijnt), zelfde helper als 0071.

Revision ID: 0076
Revises: 0075
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def _rls(tabel: str) -> None:
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


def upgrade() -> None:
    op.create_table(
        "administratie_sync_run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("aangevraagd_door", sa.UUID(), nullable=True),
        sa.Column("aangevraagd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("gestart_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("laatst_actief_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("beeindigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onderdelen", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fout_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('wachtrij', 'bezig', 'klaar', 'fout')", name="ck_administratie_sync_run_status"),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["aangevraagd_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_administratie_sync_run_administratie_id", "administratie_sync_run", ["administratie_id"], schema="boekhouding"
    )
    op.create_index(
        "ix_administratie_sync_run_administratie_status",
        "administratie_sync_run",
        ["administratie_id", "status"],
        schema="boekhouding",
    )
    _rls("administratie_sync_run")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS administratie_sync_run_scope ON boekhouding.administratie_sync_run")
    op.drop_index("ix_administratie_sync_run_administratie_status", table_name="administratie_sync_run", schema="boekhouding")
    op.drop_index("ix_administratie_sync_run_administratie_id", table_name="administratie_sync_run", schema="boekhouding")
    op.drop_table("administratie_sync_run", schema="boekhouding")
