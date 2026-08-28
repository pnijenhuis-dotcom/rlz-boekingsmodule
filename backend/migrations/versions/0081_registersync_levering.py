"""Registersync-koppelvlak voor Vastly (koppelcontract §8 v1.18, 2026-08-28).

boekhouding.registersync_levering: één rij per geleverde registersnapshot
(`GET /koppelvlak/vastgoed/register`). `nonce` DB-uniek = replay-verdediging bovenop het
timestamp-venster, over álle service-instanties heen (zelfde patroon als
boekhouding.projectaanvraag, migratie 0048); tegelijk het leveringslog (tijdstip, telling per
registerdeel, opbouwduur) — wat we uitleveren is herleidbaar. Append-only: GRANT zonder UPDATE
en zonder DELETE. Geen RLS op administratie: een levering omvat per definitie álle
administraties (platformbrede tabel, patroon ai_gebruik/0047). Schema-only.

Revision ID: 0081
Revises: 0080
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "registersync_levering",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("nonce", sa.Text(), nullable=False, unique=True),
        sa.Column("ontvangen_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aantal_administraties", sa.Integer(), nullable=False),
        sa.Column("aantal_grootboekrekeningen", sa.Integer(), nullable=False),
        sa.Column("duur_ms", sa.Integer(), nullable=False),
        schema="boekhouding",
    )
    op.execute(f"GRANT SELECT, INSERT ON boekhouding.registersync_levering TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("registersync_levering", schema="boekhouding")
