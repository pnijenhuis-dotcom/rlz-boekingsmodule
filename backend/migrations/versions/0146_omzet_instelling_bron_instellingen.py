"""Omzetbronnen zonnestudio-dagstaat + pilates-betalingsexport (Peter 15-09): `boekhouding.omzet_instelling.bron_instellingen`
JSONB — per administratie de bron-instellingen (stores → administratie, productnaam → categorie, PSP, rekeningen).
Schema-only (pure DDL); leeg = code-defaults.

Revision ID: 0146
Revises: 0145
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0146"
down_revision: str | None = "0145"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("omzet_instelling", sa.Column("bron_instellingen", JSONB(), nullable=True), schema="boekhouding")


def downgrade() -> None:
    op.drop_column("omzet_instelling", "bron_instellingen", schema="boekhouding")
