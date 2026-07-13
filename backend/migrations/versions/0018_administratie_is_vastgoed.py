"""Vastgoed-vlag per administratie (hardening-audit 2026-07-13): de webhook-outbox mag alleen
rijen aanmaken voor vastgoed-administraties (koppelcontract §3 — "wij pushen bij 'geboekt' een
webhook per inkoopfactuur van vastgoed-administraties"). Tot deze migratie ontstond er een
outbox-rij voor élke administratie; dat was latent onschuldig (er is nog geen afleveraar) maar
zou bij de bouw daarvan alle administraties naar vastgoed lekken. Expliciete eigenschap per
administratie, geen hardcode van admin-id's; default UIT (geen enkele bestaande administratie
is een vastgoed-administratie totdat een Beheerder dat expliciet zet).

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("is_vastgoed", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "is_vastgoed", schema="platform")
