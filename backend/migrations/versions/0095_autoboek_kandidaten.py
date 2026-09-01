"""Autoboek-kandidaten-motor (mockup autoboek-kandidaten.html, besluit Peter 01-09 — de per-leverancier-
opt-in schaalt niet over ~80 administraties als Peter zelf moet zoeken; het systeem nomineert
deterministisch, de mens zet in bulk aan):

- `boekhouding.autoboek_kandidaat_stand`: afgeleide, herrekenbare stand per (administratie, vendor) —
  reeks "op rij ongewijzigd", correcties, open vragen, kwalificatie + leesbare redenen, onderbouwings-
  chips, heroverweeg-signalen (advies-only), laatste factuur, actief/actief_sinds én de enige menskeuze:
  snooze ("Kandidaat verbergen" mét verplichte reden, geaudit). RLS per administratie; DELETE-grant
  (afgeleide laag, vervallen rijen worden opgeruimd). De opt-in zelf blijft op
  `leverancier_voorkeur.autoboeken_ingeschakeld` (ene schrijver).
- `platform.autoboek_instelling`: singleton met de Beheerder-drempel "N op rij" (default 5, 1–50) en het
  tijdstip van de laatste motor-run (tabs tonen de stand mét tijdstip). Patroon intake_instelling.
Schema-only.

Revision ID: 0095
Revises: 0094
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0095"
down_revision: str | None = "0094"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "autoboek_kandidaat_stand",
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True),
        sa.Column("vendor_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("reeks_ongewijzigd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correcties", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mens_boekingen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("open_vragen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kwalificeert", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actief_sinds", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redenen", JSONB(), nullable=False, server_default="[]"),
        sa.Column("chips", JSONB(), nullable=False, server_default="[]"),
        sa.Column("heroverweeg_signalen", JSONB(), nullable=False, server_default="[]"),
        sa.Column("laatste_factuur_datum", sa.Date(), nullable=True),
        sa.Column("laatste_factuur_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("laatste_document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("snooze_reden", sa.Text(), nullable=True),
        sa.Column("snooze_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snooze_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("berekend_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="boekhouding",
    )
    op.create_index(
        "ix_autoboek_kandidaat_stand_administratie_id",
        "autoboek_kandidaat_stand",
        ["administratie_id"],
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.autoboek_kandidaat_stand ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.autoboek_kandidaat_stand FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY autoboek_kandidaat_stand_scope ON boekhouding.autoboek_kandidaat_stand
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON boekhouding.autoboek_kandidaat_stand TO {APP_ROLE}")

    op.create_table(
        "autoboek_instelling",
        sa.Column("singleton", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("drempel_op_rij", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("laatste_run_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gewijzigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("singleton", name="autoboek_instelling_singleton"),
        sa.CheckConstraint("drempel_op_rij >= 1 AND drempel_op_rij <= 50", name="autoboek_instelling_drempel"),
        schema="platform",
    )
    op.execute("INSERT INTO platform.autoboek_instelling (singleton, drempel_op_rij) VALUES (true, 5)")
    # INSERT óók: de app-laag maakt de singleton-rij opnieuw aan als die ontbreekt (test-reset/lege DB).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.autoboek_instelling TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.autoboek_instelling FROM {APP_ROLE}")
    op.drop_table("autoboek_instelling", schema="platform")
    op.execute("DROP POLICY IF EXISTS autoboek_kandidaat_stand_scope ON boekhouding.autoboek_kandidaat_stand")
    op.drop_index(
        "ix_autoboek_kandidaat_stand_administratie_id", table_name="autoboek_kandidaat_stand", schema="boekhouding"
    )
    op.drop_table("autoboek_kandidaat_stand", schema="boekhouding")
