"""Afdelingen binnen een administratie (bouwrun 28-08 blok A, mockup afdelingen.html = bouwnorm;
besluiten Peter 27/28-08: handmatige keuze per document, toggle op het project_verplicht-patroon,
route per afdeling vervangt de administratie-route, terugval-afdeling "Algemeen").

1. platform.administratie.afdelingen_ingeschakeld — toggle (Beheerder-only): AAN = afdeling
   verplicht op élk inkoopdocument (blokkerende check), UIT = veld onzichtbaar. Default UIT.
2. boekhouding.afdeling — afdelingen per administratie; `is_terugval` markeert de automatische
   terugval-afdeling "Algemeen" (volgt de administratie-accorderingsconfig; precies één per
   administratie, partiële unique index). Archiveren i.p.v. verwijderen (documenten verwijzen
   ernaar); actieve naam uniek per administratie (case-insensitief).
3. boekhouding.accordering_laag.afdeling_id — NULL = de administratie-route (bestaand), gevuld =
   de route van díe afdeling (zelfde lagen-bouwstenen).
4. boekhouding.boekvoorstel.afdeling_id — de handmatige keuze per document (kopveld; tevens de
   MI-dimensie voor later). Geen backfill op geboekte historie.
5. boekhouding.staande_goedkeuring.afdeling_id — een staande goedkeuring telt alleen binnen de
   afdeling waar ze is afgegeven (NULL = afgegeven zonder afdeling).
6. boekhouding.leverancier_afdeling — prefill-geheugen per (administratie, crediteur): laatste
   keuze wint, opslag bij boekvoorstel-opslaan (zelfde moment als crediteur-kenmerken). Geen FK
   naar vendor_cache (overleeft sync-verdwijning, patroon leverancier_voorkeur).
RLS per administratie + GRANT zonder DELETE. Schema-only.

Revision ID: 0084
Revises: 0083
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0084"
down_revision: str | None = "0083"
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
    op.add_column(
        "administratie",
        sa.Column("afdelingen_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )

    op.create_table(
        "afdeling",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("is_terugval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gearchiveerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gearchiveerd_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_index("ix_afdeling_administratie_id", "afdeling", ["administratie_id"], schema="boekhouding")
    op.execute(
        "CREATE UNIQUE INDEX uq_afdeling_actieve_naam ON boekhouding.afdeling (administratie_id, lower(naam)) "
        "WHERE actief"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_afdeling_terugval ON boekhouding.afdeling (administratie_id) WHERE is_terugval"
    )
    _rls("afdeling")

    op.add_column(
        "accordering_laag",
        sa.Column("afdeling_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.afdeling.id"), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_accordering_laag_afdeling_id", "accordering_laag", ["afdeling_id"], schema="boekhouding"
    )
    op.add_column(
        "boekvoorstel",
        sa.Column("afdeling_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.afdeling.id"), nullable=True),
        schema="boekhouding",
    )
    op.add_column(
        "staande_goedkeuring",
        sa.Column("afdeling_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.afdeling.id"), nullable=True),
        schema="boekhouding",
    )

    op.create_table(
        "leverancier_afdeling",
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True),
        sa.Column("vendor_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("afdeling_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.afdeling.id"), nullable=False),
        sa.Column("laatste_document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("gewijzigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="boekhouding",
    )
    _rls("leverancier_afdeling")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS leverancier_afdeling_scope ON boekhouding.leverancier_afdeling")
    op.drop_table("leverancier_afdeling", schema="boekhouding")
    op.drop_column("staande_goedkeuring", "afdeling_id", schema="boekhouding")
    op.drop_column("boekvoorstel", "afdeling_id", schema="boekhouding")
    op.drop_index("ix_accordering_laag_afdeling_id", table_name="accordering_laag", schema="boekhouding")
    op.drop_column("accordering_laag", "afdeling_id", schema="boekhouding")
    op.execute("DROP POLICY IF EXISTS afdeling_scope ON boekhouding.afdeling")
    op.execute("DROP INDEX IF EXISTS boekhouding.uq_afdeling_terugval")
    op.execute("DROP INDEX IF EXISTS boekhouding.uq_afdeling_actieve_naam")
    op.drop_index("ix_afdeling_administratie_id", table_name="afdeling", schema="boekhouding")
    op.drop_table("afdeling", schema="boekhouding")
    op.drop_column("administratie", "afdelingen_ingeschakeld", schema="platform")
