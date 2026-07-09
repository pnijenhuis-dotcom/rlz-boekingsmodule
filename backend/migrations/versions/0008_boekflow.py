"""Boekflow fundament (CLAUDE.md, "de boekflow — van klaar om te boeken naar een echt
RLZ-boekstuk"): boekhouding.boekvoorstel + boekvoorstel_regel (het controlescherm-voorstel per
document — kopgegevens + regels, vóór en na boeken), plus de twee boeken-failsafes die
databestand nodig hebben: `platform.administratie.boeken_ingeschakeld` (per-administratie
opt-in toggle, default UIT — CLAUDE.md: "Automatisch boeken = opt-in") en het singleton-record
`platform.boeken_instelling` (globale kill switch, Beheerder-only). De derde failsafe
(volumerem) heeft geen eigen tabel nodig — die telt op de al bestaande `document_gebeurtenis`.

RLS op boekvoorstel/-regel: zelfde subquery-op-document-patroon als document_gebeurtenis
(migratie 0004) — geen eigen administratie_id-kolom nodig, scope erft van het document.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    # --- boeken-failsafe (a), deel 1: per-administratie opt-in toggle -----------------------
    op.add_column(
        "administratie",
        sa.Column("boeken_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )

    # --- boeken-failsafe (a), deel 2: globale kill switch (singleton) -----------------------
    op.create_table(
        "boeken_instelling",
        sa.Column("singleton", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("globaal_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("gewijzigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("singleton", name="boeken_instelling_singleton"),
        schema="platform",
    )
    op.execute("INSERT INTO platform.boeken_instelling (singleton, globaal_ingeschakeld) VALUES (true, true)")
    op.execute(f"GRANT SELECT, UPDATE ON platform.boeken_instelling TO {APP_ROLE}")

    # --- boekvoorstel (kopgegevens) + boekvoorstel_regel (regels) ----------------------------
    op.create_table(
        "boekvoorstel",
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), primary_key=True),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("referentie", sa.Text(), nullable=True),
        sa.Column("factuurdatum", sa.Date(), nullable=True),
        sa.Column("totaalbedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("rlz_boekstuknummer", sa.Text(), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="boekhouding",
    )
    op.create_table(
        "boekvoorstel_regel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.boekvoorstel.document_id"), nullable=False
        ),
        sa.Column("volgnummer", sa.Integer(), nullable=False),
        sa.Column("ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("taxrate_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("netto_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("btw_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_boekvoorstel_regel_document_id", "boekvoorstel_regel", ["document_id"], schema="boekhouding"
    )

    for tabel in ("boekvoorstel", "boekvoorstel_regel"):
        op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")

    # document_id is de PK op boekvoorstel zelf, en een gewone kolom op boekvoorstel_regel — de
    # EXISTS-subquery is voor beide identiek (zelfde patroon als document_gebeurtenis_scope).
    op.execute(
        """
        CREATE POLICY boekvoorstel_scope ON boekhouding.boekvoorstel
        USING (
            EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = boekvoorstel.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = boekvoorstel.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY boekvoorstel_regel_scope ON boekhouding.boekvoorstel_regel
        USING (
            EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = boekvoorstel_regel.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = boekvoorstel_regel.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        """
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON boekhouding.boekvoorstel TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON boekhouding.boekvoorstel_regel TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.boekvoorstel_regel FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON boekhouding.boekvoorstel FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS boekvoorstel_regel_scope ON boekhouding.boekvoorstel_regel")
    op.execute("DROP POLICY IF EXISTS boekvoorstel_scope ON boekhouding.boekvoorstel")
    op.drop_table("boekvoorstel_regel", schema="boekhouding")
    op.drop_table("boekvoorstel", schema="boekhouding")

    op.execute(f"REVOKE ALL ON platform.boeken_instelling FROM {APP_ROLE}")
    op.drop_table("boeken_instelling", schema="platform")

    op.drop_column("administratie", "boeken_ingeschakeld", schema="platform")
