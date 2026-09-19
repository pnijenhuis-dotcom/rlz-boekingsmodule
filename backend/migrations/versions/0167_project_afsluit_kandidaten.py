"""Projecten: tab "Afsluiten? (N)" mét bulk-afsluiten en "Niet afsluiten" (opdracht Peter 19-09 — "welk project is afgesloten?
dat onderscheid maken wij nu nog niet"; BESLISSINGEN "PROJECTEN — TAB AFSLUITEN? MÉT BULK-AFSLUITEN EN NIET-AFSLUITEN (Peter 19-09)").

1. `platform.administratie.project_afsluit_stil_maanden` smallint NOT NULL default 6 — het stil-venster van de kandidatenmotor
   (geen inkoop/verkoop/uren/planning in N maanden), instelbaar per administratie (Beheerder + Boekhouding+Projecten).
2. `boekhouding.project_afsluit_uitstel` — "Niet afsluiten" per project mét VERPLICHTE reden, wie/wanneer en een snapshot van de
   laatste activiteit op dat moment: de kandidaat blijft weg tot er nieuwere activiteit is (`laatste_activiteit` verschuift), dan
   verschijnt hij opnieuw. Eén rij per project (PK project + administratie, FK naar project_cache); nooit verwijderd — intrekken
   gebeurt door opnieuw te beoordelen (afsluiten) of door nieuwe activiteit. RLS op administratie (0165-patroon), app-rol
   SELECT/INSERT/UPDATE (geen DELETE).
Schema-only, pure DDL; geen data-wijziging.

Revision ID: 0167
Revises: 0166
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0167"
down_revision: str | None = "0166"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABEL = "project_afsluit_uitstel"


def _rls_op_administratie(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("project_afsluit_stil_maanden", sa.SmallInteger(), nullable=False, server_default="6"),
        schema="platform",
    )
    op.create_table(
        TABEL,
        sa.Column("project_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("administratie_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("reden", sa.Text(), nullable=False),
        sa.Column("door", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("laatste_activiteit", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("project_id", "administratie_id", name="pk_project_afsluit_uitstel"),
        sa.ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_project_afsluit_uitstel_project",
        ),
        sa.ForeignKeyConstraint(
            ["administratie_id"], ["platform.administratie.id"], name="fk_project_afsluit_uitstel_administratie"
        ),
        sa.ForeignKeyConstraint(["door"], ["platform.gebruiker.id"], name="fk_project_afsluit_uitstel_door"),
        schema="boekhouding",
    )
    op.create_index("ix_project_afsluit_uitstel_administratie_id", TABEL, ["administratie_id"], schema="boekhouding")
    _rls_op_administratie(TABEL)


def downgrade() -> None:
    op.drop_index("ix_project_afsluit_uitstel_administratie_id", table_name=TABEL, schema="boekhouding")
    op.drop_table(TABEL, schema="boekhouding")
    op.drop_column("administratie", "project_afsluit_stil_maanden", schema="platform")
