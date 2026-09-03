"""Crediteuren-dubbelen v2 — kantoorbreed mét actie (design-ronde 03-09, mockup crediteuren-dubbelen-v2.html):

- `boekhouding.crediteur_dubbel_afmelding`: "Geen dubbel — afmelden" per (administratie, genormaliseerde
  combinatie van vendor-id's) mét sleutel-soort/-waarde, verplichte reden, actor en tijdstip — het cluster
  verdwijnt en komt voor dezelfde combinatie nooit terug (ontwerpnotitie ⑤).
- `boekhouding.crediteur_archiveer_werklijst`: de RLZ-werklijst-regel "klaargezet — archiveer in RLZ: <namen>"
  (ontwerpnotitie ④, pad "API werkt niet" — STAP-0 03-09: een Vendor is via de API niet te archiveren):
  voorkeur + te archiveren crediteuren (JSONB, mét namen), status open/gedaan, aangemaakt/gedaan door+op,
  laatste hertoets + detail per crediteur.
RLS per administratie (patroon 0095); géén DELETE-grant — nooit verwijderen. Schema-only.

Revision ID: 0100
Revises: 0099
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0100"
down_revision: str | None = "0099"
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
        "crediteur_dubbel_afmelding",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("sleutel_soort", sa.String(), nullable=False),
        sa.Column("sleutel", sa.String(), nullable=False),
        sa.Column("combinatie", sa.String(), nullable=False),
        sa.Column("vendor_ids", JSONB(), nullable=False),
        sa.Column("reden", sa.String(), nullable=False),
        sa.Column("afgemeld_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("afgemeld_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("administratie_id", "combinatie", name="uq_crediteur_dubbel_afmelding_combinatie"),
        sa.CheckConstraint(
            "sleutel_soort IN ('btw_nummer', 'kvk_nummer', 'iban', 'naam')",
            name="ck_crediteur_dubbel_afmelding_soort",
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ix_crediteur_dubbel_afmelding_administratie_id",
        "crediteur_dubbel_afmelding",
        ["administratie_id"],
        schema="boekhouding",
    )
    _rls("crediteur_dubbel_afmelding")

    op.create_table(
        "crediteur_archiveer_werklijst",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("voorkeur_vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("voorkeur_naam", sa.String(), nullable=True),
        sa.Column("te_archiveren", JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("gedaan_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gedaan_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gedaan_bron", sa.String(), nullable=True),
        sa.Column("laatste_hertoets_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hertoets_detail", JSONB(), nullable=True),
        sa.CheckConstraint("status IN ('open', 'gedaan')", name="ck_crediteur_archiveer_werklijst_status"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_crediteur_archiveer_werklijst_administratie_id",
        "crediteur_archiveer_werklijst",
        ["administratie_id"],
        schema="boekhouding",
    )
    _rls("crediteur_archiveer_werklijst")


def downgrade() -> None:
    for tabel in ("crediteur_archiveer_werklijst", "crediteur_dubbel_afmelding"):
        op.execute(f"DROP POLICY IF EXISTS {tabel}_scope ON boekhouding.{tabel}")
        op.drop_index(f"ix_{tabel}_administratie_id", table_name=tabel, schema="boekhouding")
        op.drop_table(tabel, schema="boekhouding")
