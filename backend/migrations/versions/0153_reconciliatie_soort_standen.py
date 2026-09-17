"""Reconciliatie — bevindingssoorten starten in stand `meten` (SPOED 17-09, melding Peter: actiemail "Mogelijk dubbel
betaald … en 1204 andere" — 1.214 valse positieven van een soort die op dag één mailde). Schema-only, pure DDL:
`boekhouding.reconciliatie_instelling.soort_standen` (JSONB, default '{}') = Beheerder-/systeem-overrides per
afwijkingssoort: {"<soort>": "meten" | "actie"}. De code-default per soort staat in `app/reconciliatie/soort_stand.py`
(registry: bestaande soorten van vóór 17-09 = actie, elke nieuwe soort = meten tot een expliciete promotie); de
explosie-rem (> 50 bevindingen van één soort in één run) schrijft hier "meten" terug. Geen RLS-wijziging (singleton).

Revision ID: 0153
Revises: 0152
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0153"
down_revision: str | None = "0152"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reconciliatie_instelling",
        sa.Column(
            "soort_standen",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_column("reconciliatie_instelling", "soort_standen", schema="boekhouding")
