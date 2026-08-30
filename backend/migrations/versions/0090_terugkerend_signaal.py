"""Terugkerende-facturen-signaal (opdracht 30-08 blok B; benchmark-besluit Peter 29-08 "inbouwen",
verkenning/BENCHMARK_PAKKETTEN_29-08.md gap #3). Deterministische detectie op de bestaande historie
per (administratie, crediteur) — géén AI, puur code:

- `boekhouding.terugkerend_signaal`: één rij per (administratie, vendor) mét het gedetecteerde patroon
  (maand/kwartaal, ≥ 3 facturen met een regelmatig interval binnen ±35 %), laatste factuur (datum,
  bedrag), verwachte volgende datum, signaal 1 "verwachte factuur ontbreekt" (`ontbreekt_sinds`),
  signaal 2 "prijsstijging" (laatste vs vorige vergelijkbare factuur boven de drempel), snooze/afmelden
  per leverancier (nooit stil: audit) en `berekend_op`. Afgeleide, herrekenbare laag (dagelijks in
  sync-alles; UPSERT + DELETE van vervallen rijen) — daarom óók DELETE-grant. RLS per administratie.
- `platform.administratie.terugkerend_prijsstijging_pct`: drempel voor signaal 2, default 10 (%),
  instelbaar (Beheerder).
Alleen signaleren — nooit blokkeren of muteren. Schema-only.

Revision ID: 0090
Revises: 0089
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0090"
down_revision: str | None = "0089"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("terugkerend_prijsstijging_pct", sa.Numeric(5, 2), nullable=False, server_default="10.00"),
        schema="platform",
    )
    op.create_table(
        "terugkerend_signaal",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("patroon", sa.Text(), nullable=False),
        sa.Column("interval_dagen", sa.Integer(), nullable=False),
        sa.Column("aantal_facturen", sa.Integer(), nullable=False),
        sa.Column("laatste_datum", sa.Date(), nullable=False),
        sa.Column("laatste_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("laatste_document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=True),
        sa.Column("vorige_datum", sa.Date(), nullable=True),
        sa.Column("vorige_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("verwacht_op", sa.Date(), nullable=False),
        sa.Column("uiterlijk_op", sa.Date(), nullable=False),
        sa.Column("ontbreekt_sinds", sa.Date(), nullable=True),
        sa.Column("prijsstijging_pct", sa.Numeric(7, 2), nullable=True),
        sa.Column("snooze_tot", sa.Date(), nullable=True),
        sa.Column("afgemeld_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("afgemeld_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("berekend_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("administratie_id", "vendor_id", name="uq_terugkerend_signaal_vendor"),
        sa.CheckConstraint("patroon IN ('maand', 'kwartaal')", name="ck_terugkerend_signaal_patroon"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_terugkerend_signaal_administratie_id", "terugkerend_signaal", ["administratie_id"], schema="boekhouding"
    )
    op.execute("ALTER TABLE boekhouding.terugkerend_signaal ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.terugkerend_signaal FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY terugkerend_signaal_scope ON boekhouding.terugkerend_signaal
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON boekhouding.terugkerend_signaal TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS terugkerend_signaal_scope ON boekhouding.terugkerend_signaal")
    op.drop_index("ix_terugkerend_signaal_administratie_id", table_name="terugkerend_signaal", schema="boekhouding")
    op.drop_table("terugkerend_signaal", schema="boekhouding")
    op.drop_column("administratie", "terugkerend_prijsstijging_pct", schema="platform")
