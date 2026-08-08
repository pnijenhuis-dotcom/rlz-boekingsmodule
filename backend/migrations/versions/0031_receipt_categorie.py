"""Omzetmotor naar entity-loze Receipts (besluit Peter 2026-08-08): gecachte categorie-GUID.

De omzetmotor boekt kasomzet voortaan als entity-loze SalesInvoice (= Receipt, RLZ-UI
"Verkopen → Boekingen") in plaats van via de systeemdebiteur "Kasomzet". Daarvoor is de
administratie-specifieke DocumentCategory "Verkoopfactuur (Omzet)" nodig (Receipts-verkenning:
per administratie ophalen, nooit hardcoden) — deze kolom cachet dat GUID, zelfde patroon als
memoriaal_diary_id. De kolommen kasomzet_customer_id/kasomzet_naam blijven staan als
historisch spoor (gemarkeerd vervallen in het model) — bestaande rijen worden niet geraakt.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "omzet_instelling",
        sa.Column("verkoop_categorie_id", sa.Uuid(), nullable=True),
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_column("omzet_instelling", "verkoop_categorie_id", schema="boekhouding")
