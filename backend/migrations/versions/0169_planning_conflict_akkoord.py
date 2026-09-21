"""Planning — conflictenpaneel mét handeling (opdracht Peter 21-09; BESLISSINGEN "PLANNING — CONFLICTENPANEEL MÉT HANDELING +
DUBBELE VELDWERKERS (Peter 21-09)").

`boekhouding.planning_conflict_akkoord`: het kantoor houdt een planningsconflict BEWUST ("Beide (halve dagen)" bij dubbel
gepland, "Tóch plannen" bij afwezig) mét verplichte reden. De rij draagt de planningsstand waarop het akkoord gold
(`project_ids` = gesorteerde project-id's van die persoon × dag als JSONB-lijst): wijzigt de planning, dan past de stand niet meer
en is het conflict weer zichtbaar — de rij blijft staan (historie, nooit DELETE). Soort: 'dubbel' | 'afwezig'. RLS op administratie
zoals planning_toewijzing (0060), FORCE; grants zonder DELETE (niets verdwijnt stil). Schema-only (pure DDL).

Revision ID: 0169
Revises: 0168
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0169"
down_revision: str | None = "0168"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABEL = "planning_conflict_akkoord"


def upgrade() -> None:
    op.create_table(
        TABEL,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("project_ids", JSONB(), nullable=False),
        sa.Column("reden", sa.Text(), nullable=False),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("soort IN ('dubbel', 'afwezig')", name="ck_planning_conflict_akkoord_soort"),
        sa.CheckConstraint("length(btrim(reden)) >= 3", name="ck_planning_conflict_akkoord_reden"),
        schema="boekhouding",
    )
    op.create_index(f"ix_{TABEL}_datum", TABEL, ["administratie_id", "datum"], schema="boekhouding")
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
