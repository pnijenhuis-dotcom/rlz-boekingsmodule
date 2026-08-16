"""Handmatige accordeur-herinnering per document (beheer-mini, opdracht 2026-08-16).

Kantoor kan bij een document "bij klant ter accordering" per direct een extra herinnering
sturen (push, anders mail) aan de accordeur die aan de beurt is. Remmen: max één handmatige
herinnering per document per dag (unique document_id + datum, datum = Europe/Amsterdam),
claim-vóór-verzenden (zelfde patroon als platform.accordeur_herinnering, migratie 0050) en
audit op elke verzending. "Laatst herinnerd" is zichtbaar in de accorderingssectie en op de
klantpagina.

Revision ID: 0053
Revises: 0052
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "document_herinnering",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column(
            "accordeur_gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False
        ),
        # Dagrem-anker: lokale (Europe/Amsterdam) kalenderdag van de verzending.
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="bezig"),
        sa.Column("kanaal", sa.Text(), nullable=True),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column("verzonden_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verzonden_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('bezig', 'verzonden', 'mislukt', 'overgeslagen')", name="ck_document_herinnering_status"
        ),
        sa.CheckConstraint("kanaal IS NULL OR kanaal IN ('push', 'e-mail')", name="ck_document_herinnering_kanaal"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_document_herinnering_document_id", "document_herinnering", ["document_id"], schema="boekhouding"
    )
    op.create_index(
        "ix_document_herinnering_administratie_id", "document_herinnering", ["administratie_id"], schema="boekhouding"
    )
    # De dagrem: hooguit één handmatige herinnering per document per (lokale) dag.
    op.create_index(
        "uq_document_herinnering_dag",
        "document_herinnering",
        ["document_id", "datum"],
        unique=True,
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.document_herinnering ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.document_herinnering FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY document_herinnering_scope ON boekhouding.document_herinnering
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.document_herinnering TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("document_herinnering", schema="boekhouding")
