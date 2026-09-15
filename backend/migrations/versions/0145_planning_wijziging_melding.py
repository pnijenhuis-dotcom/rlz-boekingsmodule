"""Planning met terugwerkende kracht: bundelmelding "planning week N aangepast" (Peter/Haci 15-09).

`boekhouding.planning_wijziging_melding`: één open rij per (administratie, veldwerker, jaar, week) zodra het kantoor de
planning in een verstreken of lopende week wijzigt; de 10-min-job bundelt en zet `gemeld_op`/`kanaal`. RLS op
administratie zoals de andere uren-tabellen, FORCE; geen DELETE-grant (niets verdwijnt stil). Schema-only (pure DDL).

Revision ID: 0145
Revises: 0144
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0145"
down_revision: str | None = "0144"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABEL = "planning_wijziging_melding"


def upgrade() -> None:
    op.create_table(
        TABEL,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("jaar", sa.SmallInteger(), nullable=False),
        sa.Column("weeknummer", sa.SmallInteger(), nullable=False),
        sa.Column("aantal_wijzigingen", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gemeld_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kanaal", sa.Text(), nullable=True),
        sa.Column("detail", JSONB(), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        f"ix_{TABEL}_open", TABEL, ["administratie_id", "gebruiker_id", "jaar", "weeknummer"], schema="boekhouding"
    )
    op.execute(f"ALTER TABLE boekhouding.{TABEL} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{TABEL} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {TABEL}_scope ON boekhouding.{TABEL}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{TABEL} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table(TABEL, schema="boekhouding")
