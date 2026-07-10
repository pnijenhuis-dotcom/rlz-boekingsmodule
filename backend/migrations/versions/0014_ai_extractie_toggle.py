"""AVG-gate voor AI-extractie (fase AI-extractie sessie 1): per-administratie opt-in
`ai_extractie_ingeschakeld`, default UIT. PDF's van een administratie zonder deze toggle gaan
NIET naar de Claude API — tot de AVG-volgorde rond is (DPA + EU-verwerking-bevestiging +
verwerkersregister, zie docs/BOUWPLAN.md) staat hij alleen aan voor de test-administratie/eigen
facturen. Zelfde patroon als boeken_ingeschakeld (migratie 0008) en project_verplicht (0010):
alleen een Beheerder zet 'm aan, elke wijziging in het audit_event.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("ai_extractie_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "ai_extractie_ingeschakeld", schema="platform")
