"""Administratieprofiel "Winkel / kassa" (blok G ProfX-opdracht, Peter 16-09): `platform.administratie.kassa_profiel`
(boolean, NULL = AFGELEID uit de aanwezigheid van een herkend kassarapport; true/false = Beheerder-override). Geen los
label maar een profiel dat de omzetbron-instellingen bundelt en zichtbaar maakt (chip + filter in de administratielijst,
profiel-blok op Boeken & AI). Schema-only.

Revision ID: 0150
Revises: 0149
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0150"
down_revision: str | None = "0149"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("administratie", sa.Column("kassa_profiel", sa.Boolean(), nullable=True), schema="platform")


def downgrade() -> None:
    op.drop_column("administratie", "kassa_profiel", schema="platform")
