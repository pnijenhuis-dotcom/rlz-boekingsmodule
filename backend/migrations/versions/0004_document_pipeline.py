"""Document-pipeline fundament: boekhouding.document + document_gebeurtenis (append-only
tijdlijn). RLS op administratie-scope (besluit 0004) — `administratie_id` is NULL toegestaan
voor de 'niet_toegewezen'-verzamelbak, zelfde patroon als platform.audit_event (migratie 0001):
platformbrede rijen zijn zichtbaar ongeacht scope, geen RLS-uitzondering. document_gebeurtenis
erft de scope van zijn document via een subquery-policy (geen eigen administratie_id-kolom nodig).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"

DOCUMENT_BRON_VALUES = ("upload", "email")
DOCUMENT_STATUS_VALUES = (
    "ontvangen",
    "extractie_bezig",
    "te_controleren",
    "klaar_om_te_boeken",
    "geboekt",
    "vraag_open",
    "afgewezen",
    "boeken_mislukt",
    "niet_toegewezen",
)


def upgrade() -> None:
    document_bron = ENUM(*DOCUMENT_BRON_VALUES, name="document_bron", schema="boekhouding")
    document_status = ENUM(*DOCUMENT_STATUS_VALUES, name="document_status", schema="boekhouding")
    document_bron.create(op.get_bind(), checkfirst=True)
    document_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "document",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=True),
        sa.Column(
            "bron", ENUM(*DOCUMENT_BRON_VALUES, name="document_bron", schema="boekhouding", create_type=False),
            nullable=False,
        ),
        sa.Column("bestandsnaam", sa.Text(), nullable=False),
        sa.Column("sha256_hash", sa.Text(), nullable=False),
        sa.Column(
            "status",
            ENUM(*DOCUMENT_STATUS_VALUES, name="document_status", schema="boekhouding", create_type=False),
            nullable=False,
            server_default="ontvangen",
        ),
        sa.Column("toegewezen_aan", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("mogelijk_duplicaat_van_id", UUID(as_uuid=True), nullable=True),
        sa.Column("opslag_pad", sa.Text(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "laatst_gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["mogelijk_duplicaat_van_id"], ["boekhouding.document.id"]),
        schema="boekhouding",
    )
    op.create_index("ix_document_administratie_id", "document", ["administratie_id"], schema="boekhouding")
    # Duplicaatcheck bij binnenkomst: altijd binnen dezelfde administratie.
    op.create_index(
        "ix_document_administratie_hash", "document", ["administratie_id", "sha256_hash"], schema="boekhouding"
    )
    op.create_index("ix_document_status", "document", ["status"], schema="boekhouding")

    op.create_table(
        "document_gebeurtenis",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column(
            "van_status",
            ENUM(*DOCUMENT_STATUS_VALUES, name="document_status", schema="boekhouding", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "naar_status",
            ENUM(*DOCUMENT_STATUS_VALUES, name="document_status", schema="boekhouding", create_type=False),
            nullable=False,
        ),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column("tijdstip", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="boekhouding",
    )
    op.create_index(
        "ix_document_gebeurtenis_document_id", "document_gebeurtenis", ["document_id"], schema="boekhouding"
    )
    op.create_index(
        "ix_document_gebeurtenis_tijdstip", "document_gebeurtenis", ["tijdstip"], schema="boekhouding"
    )

    # --- RLS (besluit 0004, registers/conventies.md: geen uitzonderingen) -------------------
    op.execute("ALTER TABLE boekhouding.document ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.document FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY document_administratie_scope ON boekhouding.document
        USING (administratie_id IS NULL OR administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id IS NULL OR administratie_id = platform.current_administratie_id())
        """
    )

    op.execute("ALTER TABLE boekhouding.document_gebeurtenis ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.document_gebeurtenis FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY document_gebeurtenis_scope ON boekhouding.document_gebeurtenis
        USING (
            EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = document_gebeurtenis.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = document_gebeurtenis.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        """
    )

    # --- GRANTs: document_gebeurtenis is append-only (net als audit_event), document mag UPDATE
    # (status/toewijzing/duplicaat-vlag) maar nooit DELETE (niets hard verwijderen). -----------
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.document TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON boekhouding.document_gebeurtenis TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.document_gebeurtenis FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON boekhouding.document FROM {APP_ROLE}")

    op.execute("DROP POLICY IF EXISTS document_gebeurtenis_scope ON boekhouding.document_gebeurtenis")
    op.execute("DROP POLICY IF EXISTS document_administratie_scope ON boekhouding.document")

    op.drop_table("document_gebeurtenis", schema="boekhouding")
    op.drop_table("document", schema="boekhouding")

    op.execute("DROP TYPE IF EXISTS boekhouding.document_status")
    op.execute("DROP TYPE IF EXISTS boekhouding.document_bron")
