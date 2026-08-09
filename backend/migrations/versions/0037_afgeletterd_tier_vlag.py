"""Tier-vlag voor het factuur_afgeletterd-event (blok 3 grote opdracht 2026-08-09).

Koppelcontract §3 v1.11 punt 5 + platformbesluit 0018 (tier-model vastgoed↔RLZ): het
`factuur_afgeletterd`-event wordt uitsluitend verstuurd voor administraties met de
optie-2-vlag — een aparte kolom naast `is_vastgoed` (analoog patroon), default UIT.
De payload zelf is in dezelfde bouwstap omgebouwd naar de definitieve v1.11-velddefinitie
(schema_version 2.0, cumulatief betaald_bedrag + open_bedrag uit BaseRemainingAmount,
volgnummer, scenario-enum mét ont_afgeletterd); het event blijft UIT tot vastgoeds verwerker
er is (aflevering staat sowieso achter platform.webhook_instelling, default UIT).

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("afgeletterd_event_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "afgeletterd_event_ingeschakeld", schema="platform")
