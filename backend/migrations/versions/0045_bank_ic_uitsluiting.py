"""RC-consequentie doorbelasting (BLOK 2, besluit Peter 2026-08-13; verkenning/16 §2b):
intercompany-facturen lopen via de rekening-courant en worden nooit afgeletterd — de bank
mag een IC-open-post dus nooit als afletter-voorstel of match aanbieden, aan beide kanten.

Twee bouwstenen:
1. `payment_item_cache.entity_guid`/`entity_naam` — de tegenpartij van de open post, gevuld
   door de sync via de geneste expand `Document($expand=Entity)` (read-only geverifieerd
   2026-08-13 tegen de test-administratie). NULL voor rijen van vóór deze migratie; die
   worden bij de eerstvolgende sync-ronde gevuld.
2. `intercompany_tegenpartij` — per administratie de entity-GUID's die als intercompany
   gelden. Eigen tabel (en niet rechtstreeks de doorbelasting-mapping) omdat RLS de
   doel-administratie geen leestoegang geeft tot de mapping-rijen van de bron-administratie:
   de doorbelasting-service schrijft per kant een rij in de juiste scope (bron-kant =
   doel_customer_guid in de bron-administratie; doel-kant = de crediteur-GUID in de
   doel-administratie zodra die bij de eerste spiegel-boeking bekend is).

Revision ID: 0045
Revises: 0044
Create Date: 2026-08-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.add_column(
        "payment_item_cache", sa.Column("entity_guid", UUID(as_uuid=True), nullable=True), schema="boekhouding"
    )
    op.add_column(
        "payment_item_cache", sa.Column("entity_naam", sa.Text(), nullable=True), schema="boekhouding"
    )

    op.create_table(
        "intercompany_tegenpartij",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("entity_guid", UUID(as_uuid=True), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("bron", sa.Text(), nullable=False, server_default=sa.text("'doorbelasting_mapping'")),
        sa.Column("mapping_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("administratie_id", "entity_guid", name="intercompany_tegenpartij_uniek"),
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.intercompany_tegenpartij ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.intercompany_tegenpartij FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY intercompany_tegenpartij_scope ON boekhouding.intercompany_tegenpartij
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.intercompany_tegenpartij TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.intercompany_tegenpartij FROM {APP_ROLE}")
    op.drop_table("intercompany_tegenpartij", schema="boekhouding")
    op.drop_column("payment_item_cache", "entity_naam", schema="boekhouding")
    op.drop_column("payment_item_cache", "entity_guid", schema="boekhouding")
