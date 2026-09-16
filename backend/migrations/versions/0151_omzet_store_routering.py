"""Store → administratie platformbreed (Peter 16-09 avond: Sunshine Island = eigen BV, dus een ándere administratie dan
Elderveld). `boekhouding.omzet_store_routering`: één rij per genormaliseerde POS-storenaam ("Store Used" in de
zonnestudio-dagstaat) → administratie, actief-vlag (deactiveren, nooit verwijderen), wie/wanneer. Unieke index op
`store_norm`: twee administraties voor dezelfde store is onmogelijk. RLS als referentietabel over administraties heen
(lezen voor iedereen in de app-rol; schrijven door de Beheerder via de service-poort en door de data-stap); geen DELETE.
De per-administratie-lijst `bron_instellingen.stores` (0146) blijft alleen als afgeleide weergave — de data-stap
`omzet-stores-migreren` zet de bestaande inhoud éénmalig over. Schema-only.

Revision ID: 0151
Revises: 0150
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0151"
down_revision: str | None = "0150"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABEL = "omzet_store_routering"


def upgrade() -> None:
    op.create_table(
        TABEL,
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("store_norm", sa.Text(), nullable=False),
        sa.Column("store_naam", sa.Text(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("actief", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("bron", sa.Text(), server_default="mens", nullable=False),
        sa.Column("gewijzigd_door", sa.UUID(), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("store_norm", name="uq_omzet_store_routering_store_norm"),
        sa.CheckConstraint("bron IN ('mens', 'migratie')", name="ck_omzet_store_routering_bron"),
        schema="boekhouding",
    )
    op.create_index("ix_omzet_store_routering_administratie", TABEL, ["administratie_id"], schema="boekhouding")
    op.execute(f"ALTER TABLE boekhouding.{TABEL} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{TABEL} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABEL}_lees ON boekhouding.{TABEL} FOR SELECT USING (true)")
    op.execute(f"CREATE POLICY {TABEL}_toevoegen ON boekhouding.{TABEL} FOR INSERT WITH CHECK (true)")
    op.execute(f"CREATE POLICY {TABEL}_muteren ON boekhouding.{TABEL} FOR UPDATE USING (true) WITH CHECK (true)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{TABEL} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_omzet_store_routering_administratie", table_name=TABEL, schema="boekhouding")
    op.drop_table(TABEL, schema="boekhouding")
