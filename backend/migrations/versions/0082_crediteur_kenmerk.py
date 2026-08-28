"""Crediteur-kenmerken: btw-nummer + KvK-nummer per crediteur (opruimrun 28-08 punt 14, besluiten
Peter 27-08 — crediteur-dedup + duplicaat over crediteuren heen).

boekhouding.crediteur_kenmerk: per (administratie, RLZ-vendor) het uit de factuur gelezen
btw-nummer (primair, deterministisch gevalideerd: NL-vorm + elfproef/mod-97 waar mogelijk) en
KvK-nummer (secundair), mét bron en het document waaruit het laatst is overgenomen. Geen FK naar
vendor_cache (overleeft sync-verdwijning — zelfde overweging als leverancier_iban/0019). Vult
(1) de crediteur-voorstel-match (nummer wint vóór fuzzy naam), (2) de blokkerende
duplicaatcheck over ÁLLE crediteuren (btw-nummer + factuurnummer + bedrag) en (3) de
dubbel-signalering op Instellingen. RLS per administratie + GRANT zonder DELETE. Schema-only.

Revision ID: 0082
Revises: 0081
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0082"
down_revision: str | None = "0081"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "crediteur_kenmerk",
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True),
        sa.Column("vendor_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("btw_nummer", sa.Text(), nullable=True),
        sa.Column("btw_nummer_geverifieerd", sa.Boolean(), nullable=True),
        sa.Column("btw_nummer_bron", sa.Text(), nullable=True),
        sa.Column("kvk_nummer", sa.Text(), nullable=True),
        sa.Column("kvk_nummer_bron", sa.Text(), nullable=True),
        sa.Column("laatst_uit_document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("bijgewerkt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "btw_nummer_bron IS NULL OR btw_nummer_bron IN ('factuur', 'handmatig')", name="ck_crediteur_kenmerk_btw_bron"
        ),
        sa.CheckConstraint(
            "kvk_nummer_bron IS NULL OR kvk_nummer_bron IN ('factuur', 'rlz', 'handmatig')",
            name="ck_crediteur_kenmerk_kvk_bron",
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ix_crediteur_kenmerk_btw", "crediteur_kenmerk", ["administratie_id", "btw_nummer"], schema="boekhouding"
    )
    op.create_index(
        "ix_crediteur_kenmerk_kvk", "crediteur_kenmerk", ["administratie_id", "kvk_nummer"], schema="boekhouding"
    )
    op.execute("ALTER TABLE boekhouding.crediteur_kenmerk ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.crediteur_kenmerk FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY crediteur_kenmerk_scope ON boekhouding.crediteur_kenmerk
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.crediteur_kenmerk TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS crediteur_kenmerk_scope ON boekhouding.crediteur_kenmerk")
    op.drop_index("ix_crediteur_kenmerk_kvk", table_name="crediteur_kenmerk", schema="boekhouding")
    op.drop_index("ix_crediteur_kenmerk_btw", table_name="crediteur_kenmerk", schema="boekhouding")
    op.drop_table("crediteur_kenmerk", schema="boekhouding")
