"""Crediteuren-dubbelen schaalbaar (blok B13, fixrun 07-09 — richting Peter 06-09): verliezers van een dubbel-cluster
worden in de MODULE onbruikbaar (crediteur-voorstellen, matching, autoboeken, geheugen → uitsluitend de voorkeur);
RLZ-archivering is geen doel meer. Eenduidige clusters handelt het systeem in één run af, twijfel blijft mens.

- `boekhouding.vendor_cache` + `voorkeur_vendor_id` (gezet = deze crediteur is een VERLIEZER en wijst naar de
  voorkeur in dezelfde administratie), `dubbel_afgehandeld_op/door/bron` ('auto' | 'mens'). De sync-upsert raakt
  deze kolommen niet (`_upsert_en_markeer_verdwenen` zet alleen naam/is_gearchiveerd/brondata).
- `boekhouding.crediteur_dubbel_afhandeling` — append-only log per afgehandeld cluster mét de OUDE stand van alles
  wat verhuisd/gewijzigd is (geheugen-kopieën, kenmerk-oud, IBAN-kopieën, hervertaalde boekvoorstellen) zodat
  `draai_terug` de markering en de kenmerk-/boekvoorstel-wijzigingen herstelt; `teruggedraaid_*` is de enige UPDATE.
RLS per administratie (0100-patroon), GRANT SELECT/INSERT/UPDATE — geen DELETE (nooit verwijderen). Schema-only.

Revision ID: 0117
Revises: 0116
Create Date: 2026-09-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0117"
down_revision: str | None = "0116"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABEL = "crediteur_dubbel_afhandeling"


def upgrade() -> None:
    op.add_column(
        "vendor_cache", sa.Column("voorkeur_vendor_id", UUID(as_uuid=True), nullable=True), schema="boekhouding"
    )
    op.add_column(
        "vendor_cache",
        sa.Column("dubbel_afgehandeld_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.add_column(
        "vendor_cache",
        sa.Column(
            "dubbel_afgehandeld_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True
        ),
        schema="boekhouding",
    )
    op.add_column("vendor_cache", sa.Column("dubbel_afgehandeld_bron", sa.Text(), nullable=True), schema="boekhouding")
    op.create_check_constraint(
        "ck_vendor_cache_dubbel_afgehandeld_bron",
        "vendor_cache",
        "dubbel_afgehandeld_bron IS NULL OR dubbel_afgehandeld_bron IN ('auto', 'mens')",
        schema="boekhouding",
    )
    op.create_index(
        "ix_vendor_cache_voorkeur_vendor_id",
        "vendor_cache",
        ["administratie_id", "voorkeur_vendor_id"],
        schema="boekhouding",
        postgresql_where=sa.text("voorkeur_vendor_id IS NOT NULL"),
    )

    op.create_table(
        TABEL,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("voorkeur_vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("voorkeur_naam", sa.Text(), nullable=True),
        # [{"vendor_id": "...", "naam": "..."}] — de verliezers.
        sa.Column("verliezers", JSONB(), nullable=False),
        # [{"soort": "naam", "sleutel": "wola"}, ...] — waarop het cluster dubbel was.
        sa.Column("sleutels", JSONB(), nullable=False),
        sa.Column("classificatie_reden", sa.Text(), nullable=False),
        # Oude stand voor terugdraaien: {"geheugen": [[oud_id, nieuw_id], ...], "kenmerk_oud": {...} | null,
        #  "ibans": [...], "boekvoorstellen": [{"document_id": "...", "van_vendor_id": "..."}]}
        sa.Column("verhuisd", JSONB(), nullable=False),
        sa.Column("afgehandeld_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("afgehandeld_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("teruggedraaid_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("teruggedraaid_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("teruggedraaid_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("bron IN ('auto', 'mens')", name=f"ck_{TABEL}_bron"),
        schema="boekhouding",
    )
    op.create_index(f"ix_{TABEL}_administratie_id", TABEL, ["administratie_id"], schema="boekhouding")
    op.execute(f"ALTER TABLE boekhouding.{TABEL} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{TABEL} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {TABEL}_scope ON boekhouding.{TABEL}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{TABEL} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABEL}_scope ON boekhouding.{TABEL}")
    op.drop_index(f"ix_{TABEL}_administratie_id", table_name=TABEL, schema="boekhouding")
    op.drop_table(TABEL, schema="boekhouding")
    op.drop_index("ix_vendor_cache_voorkeur_vendor_id", table_name="vendor_cache", schema="boekhouding")
    op.drop_constraint("ck_vendor_cache_dubbel_afgehandeld_bron", "vendor_cache", schema="boekhouding", type_="check")
    for kolom in ("dubbel_afgehandeld_bron", "dubbel_afgehandeld_door", "dubbel_afgehandeld_op", "voorkeur_vendor_id"):
        op.drop_column("vendor_cache", kolom, schema="boekhouding")
