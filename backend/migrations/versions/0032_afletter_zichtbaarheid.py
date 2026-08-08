"""Afletter-assist zichtbaar (kliktest Peter 2026-08-08: "lijkt niets te doen").

De klaargezette afletter-opdracht toont voortaan zijn levenscyclus in de UI. Daarvoor één
nieuw feit dat nu nergens vastligt: wanneer de verificatieronde een klaargezette opdracht
voor het laatst heeft gecontroleerd terwijl de mutatie in RLZ nog open stond — het eerlijke
verschil tussen "klaargezet (nog geen sync geweest)" en "wacht op verificatie (laatst
gecontroleerd om …, nog open in RLZ)". Verificatie-uitkomsten zelf stonden al in
verificatie_detail/geverifieerd_op.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bank_afletter_opdracht",
        sa.Column("laatste_verificatie_poging_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_column("bank_afletter_opdracht", "laatste_verificatie_poging_op", schema="boekhouding")
