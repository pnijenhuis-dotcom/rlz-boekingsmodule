"""Duplicaat-auto-afvoer STANDAARD AAN + platformbrede noodrem (besluit Peter 04-09, blok A1).

De per-administratie-opt-in `administratie.duplicaat_autoafvoer_ingeschakeld` (0105) vervalt als
gedrag en uit de UI — de kolom blijft staan (geen data-verlies, geen drop in een druk schema); het
automatische pad leest 'm niet meer. In plaats daarvan één platformbrede noodrem, zelfde
singleton-patroon als `boeken_instelling` (0008) / `intake_instelling` (0029): Beheerder-only aan/uit,
elke wijziging in het audit_event. Default AAN — "standaard aan voor de hele module", de noodrem is er
voor als het mis blijkt te gaan. Volumerem (20/dag/administratie) en de één-klik-actie staan hier los van.

Revision ID: 0109
Revises: 0108
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0109"
down_revision: str | None = "0108"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "duplicaat_afvoer_instelling",
        sa.Column("singleton", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("platformbreed_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("gewijzigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("singleton", name="duplicaat_afvoer_instelling_singleton"),
        schema="platform",
    )
    op.execute(
        "INSERT INTO platform.duplicaat_afvoer_instelling (singleton, platformbreed_ingeschakeld) VALUES (true, true)"
    )
    op.execute(f"GRANT SELECT, UPDATE ON platform.duplicaat_afvoer_instelling TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.duplicaat_afvoer_instelling FROM {APP_ROLE}")
    op.drop_table("duplicaat_afvoer_instelling", schema="platform")
