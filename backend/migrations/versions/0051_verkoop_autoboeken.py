"""Autoboek-opt-in voor VASTLY-VERKOOP-documenten (besluit Peter 2026-08-15, gebouwd 16-08).

Automatisering-first-principe (BESLISSINGEN "Automatisering-first"): elk deterministisch pad
krijgt een autoboek-opt-in volgens het vaste patroon — opt-in default UIT, harde checks
onverkort blokkerend, volumerem, zichtbare 'automatisch'-markering + audit, storno als
terugweg. Dit is de verkoop-afnemer: één kolom op platform.administratie, zelfde vorm als
`bank_autoboeken_ingeschakeld` (0026) en `afgeletterd_event_ingeschakeld` (0037). Aanzetten
kan alleen voor is_vastgoed-administraties (server-side in app/beheer/service.py — VASTLY-
VERKOOP-documenten bestaan alleen dáár); de poortlogica zelf staat in app/verkoop/autoboeken.py.

Revision ID: 0051
Revises: 0050
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("verkoop_autoboeken_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "verkoop_autoboeken_ingeschakeld", schema="platform")
