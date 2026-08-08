"""Klant-accorderingsflow — backend + kantoor-UI (fase 3-kern, mockup #autorisatie).

Sequentiële accorderingslagen met bedragdrempels per administratie (toggle default UIT),
statusmachine-tak ter_accordering (boekknop wordt "Ter accordering"), afwijzen door de
accordeur met verplichte reden, en de STAANDE GOEDKEURING (besluit Peter 2026-08-08): akkoord
voor toekomstige facturen van dezelfde leverancier bij exact hetzelfde bedrag — vervangt
alleen de menselijke akkoord-klik, nooit de harde checks. De accordeur-PWA zelf wordt apart
mobile-first ontworpen; de endpoints zijn er wel al op ontworpen (scope via RLS +
server-side checks, zoals overal).

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def _rls_op_administratie(tabel: str) -> None:
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
    # Nieuwe documentstatus (PG ≥ 12: ADD VALUE mag in een transactie zolang de waarde niet in
    # dezelfde transactie gebruikt wordt — deze migratie is puur DDL).
    op.execute("ALTER TYPE boekhouding.document_status ADD VALUE IF NOT EXISTS 'ter_accordering'")

    # Toggle per administratie, zelfde patroon als boeken_ingeschakeld/bank_autoboeken (default UIT).
    op.add_column(
        "administratie",
        sa.Column("accordering_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )

    # Accorderingslagen: sequentieel (volgnummer), optionele bedragdrempel ("laag 2 pas boven
    # € X"), append-only (deactiveren i.p.v. verwijderen — historie blijft).
    op.create_table(
        "accordering_laag",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("volgnummer", sa.Integer(), nullable=False),
        sa.Column(
            "accordeur_gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False
        ),
        sa.Column("bedrag_drempel", sa.Numeric(14, 2), nullable=True),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gedeactiveerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gedeactiveerd_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_accordering_laag_administratie_id", "accordering_laag", ["administratie_id"], schema="boekhouding"
    )
    _rls_op_administratie("accordering_laag")

    # Eén accorderingsronde per aangeboden document; de stappen zijn de bevroren evaluatie van
    # de lagen op het moment van aanbieden (drempel al toegepast in `vereist`).
    op.create_table(
        "document_accordering",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("aangeboden_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangeboden_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("afgerond_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", JSONB, nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_document_accordering_document_id", "document_accordering", ["document_id"], schema="boekhouding"
    )
    # Hooguit één open ronde per document.
    op.create_index(
        "uq_document_accordering_open",
        "document_accordering",
        ["document_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status = 'open'"),
    )
    _rls_op_administratie("document_accordering")

    op.create_table(
        "accordering_stap",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column(
            "accordering_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document_accordering.id"), nullable=False
        ),
        sa.Column("volgnummer", sa.Integer(), nullable=False),
        sa.Column(
            "accordeur_gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False
        ),
        sa.Column("bedrag_drempel", sa.Numeric(14, 2), nullable=True),
        sa.Column("vereist", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("besluit", sa.Text(), nullable=True),
        sa.Column("besluit_bron", sa.Text(), nullable=True),
        sa.Column("staande_regel_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reden", sa.Text(), nullable=True),
        sa.Column("besloten_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_accordering_stap_accordering_id", "accordering_stap", ["accordering_id"], schema="boekhouding"
    )
    _rls_op_administratie("accordering_stap")

    # Staande goedkeuring (besluit 2026-08-08): per accordeur + leverancier + exact bedrag;
    # zichtbaar + intrekbaar, nooit verwijderd.
    op.create_table(
        "staande_goedkeuring",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column(
            "accordeur_gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False
        ),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("leverancier_naam", sa.Text(), nullable=True),
        sa.Column("bedrag", sa.Numeric(14, 2), nullable=False),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("bron_document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=True),
        sa.Column("ingetrokken_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("ingetrokken_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_staande_goedkeuring_administratie_id",
        "staande_goedkeuring",
        ["administratie_id"],
        schema="boekhouding",
    )
    _rls_op_administratie("staande_goedkeuring")


def downgrade() -> None:
    # Rijen met de nieuwe statuswaarde eerst terugmappen: de enum-waarde zelf blijft staan
    # (PostgreSQL kent geen DROP VALUE), maar de type-REBUILD in de downgrade van migratie 0012
    # cast bestaande rijen en zou anders op 'ter_accordering' stranden (testdatabase-reset doet
    # downgrade base → upgrade head).
    op.execute("UPDATE boekhouding.document SET status = 'klaar_om_te_boeken' WHERE status = 'ter_accordering'")
    op.execute(
        "UPDATE boekhouding.document_gebeurtenis SET van_status = 'klaar_om_te_boeken' "
        "WHERE van_status = 'ter_accordering'"
    )
    op.execute(
        "UPDATE boekhouding.document_gebeurtenis SET naar_status = 'klaar_om_te_boeken' "
        "WHERE naar_status = 'ter_accordering'"
    )
    op.drop_table("staande_goedkeuring", schema="boekhouding")
    op.drop_table("accordering_stap", schema="boekhouding")
    op.drop_table("document_accordering", schema="boekhouding")
    op.drop_table("accordering_laag", schema="boekhouding")
    op.drop_column("administratie", "accordering_ingeschakeld", schema="platform")
    # De enum-waarde 'ter_accordering' blijft staan — PostgreSQL kent geen DROP VALUE.
