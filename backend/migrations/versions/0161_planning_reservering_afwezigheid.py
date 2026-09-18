"""Planning personeel v3 "dag-eerst" (mockup planning-v3-dag-eerst.html, AKKOORD Peter 18-09): reservering + afwezigheid.

- `boekhouding.planning_reservering`: kaart zonder ploeg (project × dag, UNIQUE per administratie) — het kantoor sleept
  een projecttegel naar een dag vóór de ploeg bekend is ("gereserveerd", grijs). Zodra er een planning_toewijzing op
  dezelfde (project, datum) staat, toont de UI de reservering niet meer apart; de rij blijft als drager (verwijderen =
  expliciete, geaudite handeling). RLS op administratie zoals planning_toewijzing (0060), FORCE; grants incl. DELETE.
- `boekhouding.veldwerker_afwezigheid`: "op deze dagen niet plannen" — [van, tot] inclusief, reden vrije tekst, nooit
  DELETE (beëindigen = tot vervroegen + beeindigd_op). Géén verlofadministratie/saldo/goedkeuring. RLS idem, geen
  DELETE-grant (niets verdwijnt stil).
Schema-only (pure DDL).

Revision ID: 0161
Revises: 0160
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0161"
down_revision: str | None = "0160"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
RESERVERING = "planning_reservering"
AFWEZIGHEID = "veldwerker_afwezigheid"


def _rls(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )


def upgrade() -> None:
    op.create_table(
        RESERVERING,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_planning_reservering_project_cache",
        ),
        sa.UniqueConstraint("administratie_id", "project_id", "datum", name="uq_planning_reservering_project_dag"),
        schema="boekhouding",
    )
    op.create_index(f"ix_{RESERVERING}_datum", RESERVERING, ["administratie_id", "datum"], schema="boekhouding")
    _rls(RESERVERING)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON boekhouding.{RESERVERING} TO {APP_ROLE}")

    op.create_table(
        AFWEZIGHEID,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("van", sa.Date(), nullable=False),
        sa.Column("tot", sa.Date(), nullable=False),
        sa.Column("reden", sa.Text(), nullable=True),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("beeindigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("tot >= van", name="ck_veldwerker_afwezigheid_periode"),
        schema="boekhouding",
    )
    op.create_index(
        f"ix_{AFWEZIGHEID}_gebruiker",
        AFWEZIGHEID,
        ["administratie_id", "gebruiker_id", "van", "tot"],
        schema="boekhouding",
    )
    _rls(AFWEZIGHEID)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{AFWEZIGHEID} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table(AFWEZIGHEID, schema="boekhouding")
    op.drop_table(RESERVERING, schema="boekhouding")
