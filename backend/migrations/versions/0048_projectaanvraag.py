"""Route A — inkomend projectaanvraag-register (koppelcontract §5 v1.15, 2026-08-14).

boekhouding.projectaanvraag: één rij per geslaagd verwerkte aanvraag van vastgoed.
`bericht_id` = PK én idempotentiesleutel (herlevering krijgt hetzelfde synchrone antwoord
terug); `nonce` DB-uniek = replay-verdediging bovenop het timestamp-venster. Append-only:
GRANT zonder UPDATE en zonder DELETE (rijen worden nooit gemuteerd — een mislukte aanvraag
krijgt geen rij, alleen een audit_event). RLS op administratie (patroon 0039, geen
uitzonderingen — registers/conventies.md).

Revision ID: 0048
Revises: 0047
Create Date: 2026-08-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "projectaanvraag",
        sa.Column("bericht_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False, unique=True),
        sa.Column("pand_referentie", sa.Text(), nullable=False),
        sa.Column("naam_invoer", sa.Text(), nullable=False),
        sa.Column("projectnaam", sa.Text(), nullable=False),
        sa.Column("rlz_project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('aangemaakt', 'bestond_al')", name="projectaanvraag_status_geldig"),
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.projectaanvraag ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.projectaanvraag FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY projectaanvraag_scope ON boekhouding.projectaanvraag
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT ON boekhouding.projectaanvraag TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS projectaanvraag_scope ON boekhouding.projectaanvraag")
    op.drop_table("projectaanvraag", schema="boekhouding")
