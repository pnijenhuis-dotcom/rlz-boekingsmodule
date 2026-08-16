"""Nieuwe-facturen-bundelmelding per accordeur (besluit Peter 2026-08-16: expliciet GEEN
melding per factuur — periodieke check bundelt NIEUW klaargezet werk tot één bericht
"Er staan N facturen voor u klaar").

platform.accordeur_nieuw_gemeld is de idempotentie-drager: één rij per (accordeur, document),
uniek — een document wordt nooit tweemaal aan dezelfde accordeur gemeld, ook niet als het
later opnieuw ter accordering komt. Claim-vóór-verzenden (zelfde patroon als
accordeur_herinnering, 0050): rijen gaan op 'bezig' en pas na geslaagde verzending op
'verzonden'; 'mislukt'/'overgeslagen' (aantoonbaar niets bezorgd) mag een volgende run opnieuw,
een 'bezig'-blijver nooit automatisch (zichtbaar via exit 1).

Revision ID: 0054
Revises: 0053
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "accordeur_nieuw_gemeld",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="bezig"),
        sa.Column("kanaal", sa.Text(), nullable=True),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verzonden_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('bezig', 'verzonden', 'mislukt', 'overgeslagen')", name="ck_accordeur_nieuw_gemeld_status"
        ),
        sa.CheckConstraint(
            "kanaal IS NULL OR kanaal IN ('push', 'e-mail')", name="ck_accordeur_nieuw_gemeld_kanaal"
        ),
        sa.UniqueConstraint("gebruiker_id", "document_id", name="uq_accordeur_nieuw_gemeld"),
        schema="platform",
    )
    op.create_index(
        "ix_accordeur_nieuw_gemeld_gebruiker_id", "accordeur_nieuw_gemeld", ["gebruiker_id"], schema="platform"
    )
    # Nooit DELETE: het gemeld-log is de idempotentie-bron (zelfde lijn als accordeur_herinnering).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.accordeur_nieuw_gemeld TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("accordeur_nieuw_gemeld", schema="platform")
