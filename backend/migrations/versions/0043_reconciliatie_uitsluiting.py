"""Reconciliatie-uitsluiting per administratie (besluit Peter 2026-08-12).

De test-administratie draagt permanent testboekingen die een mens in de RLZ-UI opruimt; die
melden zich elke ochtend als afwijking. Uitsluiten haalt zo'n administratie uit de EXIT-CODE,
nooit uit het RAPPORT: de bevindingen worden nog steeds opgehaald en getoond onder de markering
UITGESLOTEN, zodat een echte fout in de test-administratie (waar wél schrijftests op draaien)
zichtbaar blijft.

Uitsluiten vereist een reden (DB-CHECK, niet alleen applicatielogica) en legt actor + moment
vast — zelfde discipline als de acceptatie uit 0042.

Revision ID: 0043
Revises: 0042
Create Date: 2026-08-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("reconciliatie_uitgesloten", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )
    op.add_column(
        "administratie",
        sa.Column("reconciliatie_uitsluiting_reden", sa.Text(), nullable=True),
        schema="platform",
    )
    op.add_column(
        "administratie",
        sa.Column("reconciliatie_uitgesloten_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.add_column(
        "administratie",
        sa.Column(
            "reconciliatie_uitgesloten_door",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.gebruiker.id"),
            nullable=True,
        ),
        schema="platform",
    )
    # Uitsluiten zonder reden bestaat niet — een stille uitsluiting is precies het soort
    # onzichtbare versoepeling waar dit register tegen beschermt.
    op.create_check_constraint(
        "administratie_reconciliatie_uitsluiting_reden",
        "administratie",
        "NOT reconciliatie_uitgesloten OR (reconciliatie_uitsluiting_reden IS NOT NULL "
        "AND length(btrim(reconciliatie_uitsluiting_reden)) >= 5)",
        schema="platform",
    )


def downgrade() -> None:
    op.drop_constraint(
        "administratie_reconciliatie_uitsluiting_reden", "administratie", schema="platform", type_="check"
    )
    for kolom in (
        "reconciliatie_uitgesloten_door",
        "reconciliatie_uitgesloten_op",
        "reconciliatie_uitsluiting_reden",
        "reconciliatie_uitgesloten",
    ):
        op.drop_column("administratie", kolom, schema="platform")
