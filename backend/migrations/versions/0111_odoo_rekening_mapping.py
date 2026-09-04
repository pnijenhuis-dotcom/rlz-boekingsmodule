"""Boekingsgeheugen-mapping RLZ → Odoo bij een overstap (blok A Odoo-afrondingsrun 04-09, besluit Peter
04-09 — beslispunt 1 van "ODOO-ADAPTER BLOK E").

Een RLZ-administratie die op Odoo overstapt (ingang B, volledige backend) draagt een boekingsgeheugen
met RLZ-UUID's (grootboek `ledger_id`, btw `taxrate_id`). Zonder vertaling zou dat geheugen — en daarmee
élke autoboek-opt-in — ná de overstap stil doodvallen: de Odoo-stamgegevens hebben andere lokale UUID's
(`odoo_uuid(company, model, id)`). Deze tabel legt per administratie de door de MENS bevestigde
mapping vast: RLZ-rekening/-tarief → Odoo-account/-tax, op REKENINGCODE voorgesteld door code
(`zelfde_code`, `code_verlengd` = RLZ-code + "00") resp. tarief (`tarief`), anders `handmatig`.

- `boekhouding.odoo_rekening_mapping`: APPEND-ONLY (GRANT zonder UPDATE/DELETE) — een correctie is een
  nieuwe rij met `versie + 1`; de geldende rij is de hoogste versie per (administratie, soort, rlz_id).
  `odoo_id` 0 = de synthetische "Geen btw (0%)" (alleen soort 'btw'; besluit Peter 02-09: 0 %-inkoop =
  géén tax_ids). RLS ENABLE+FORCE + policy op administratie_id (patroon 0101).

Schema-only, geen backfill (bestaande Odoo-administraties zonder RLZ-verleden hebben geen mapping —
lege mapping = geen vertaling).

Revision ID: 0111
Revises: 0110
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0111"
down_revision: str | None = "0110"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABEL = "odoo_rekening_mapping"


def upgrade() -> None:
    op.create_table(
        TABEL,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("soort", sa.String(length=16), nullable=False),
        sa.Column("rlz_id", UUID(as_uuid=True), nullable=False),
        sa.Column("rlz_code", sa.Text(), nullable=True),
        sa.Column("rlz_naam", sa.Text(), nullable=True),
        sa.Column("odoo_lokaal_id", UUID(as_uuid=True), nullable=False),
        sa.Column("odoo_id", sa.Integer(), nullable=False),
        sa.Column("odoo_code", sa.Text(), nullable=True),
        sa.Column("odoo_naam", sa.Text(), nullable=True),
        sa.Column("bron", sa.String(length=16), nullable=False),
        sa.Column("versie", sa.Integer(), nullable=False),
        sa.Column("bevestigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("bevestigd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("administratie_id", "soort", "rlz_id", "versie", name="uq_odoo_rekening_mapping_versie"),
        sa.CheckConstraint("soort IN ('grootboek', 'btw')", name="ck_odoo_rekening_mapping_soort"),
        sa.CheckConstraint(
            "bron IN ('zelfde_code', 'code_verlengd', 'tarief', 'handmatig')", name="ck_odoo_rekening_mapping_bron"
        ),
        sa.CheckConstraint("versie >= 1", name="ck_odoo_rekening_mapping_versie"),
        sa.CheckConstraint("odoo_id >= 0", name="ck_odoo_rekening_mapping_odoo_id"),
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
    # Append-only: een correctie is een nieuwe versie — bewust geen UPDATE en geen DELETE.
    op.execute(f"GRANT SELECT, INSERT ON boekhouding.{TABEL} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABEL}_scope ON boekhouding.{TABEL}")
    op.drop_index(f"ix_{TABEL}_administratie_id", table_name=TABEL, schema="boekhouding")
    op.drop_table(TABEL, schema="boekhouding")
