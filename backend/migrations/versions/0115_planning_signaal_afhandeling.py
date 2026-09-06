"""Kantoor-signaal "geplande week zonder weekstaat" (mini-run 06-09 blok A — BESLISSINGEN "PLANNING-SIGNAAL
GEPLANDE WEEK ZONDER WEEKSTAAT"). De veld-app toont geplande weken maar `OPEN_WEKEN_VENSTER` (6) weken terug;
een geplande week zónder ingediende weekstaat die uit dat venster valt verdween stil. Het signaal zelf is
afgeleid (planning_toewijzing × weekstaat, geen eigen tabel); deze tabel legt uitsluitend de AFHANDELING vast:

- `soort = 'herinnerd'` — append-only, één rij per (combinatie, dag) = de dagrem (dossier_herinnering-patroon:
  claim vóór verzenden, status bezig/verzonden/mislukt/overgeslagen, kanaal push/mail).
- `soort = 'afgemeld'` — één ACTUELE afmelding per combinatie (partial unique op ingetrokken_op IS NULL), reden
  verplicht (CHECK), intrekken = kolom `ingetrokken_op/door` — nooit delete.

RLS per administratie (0107/0114-vorm), GRANT zonder DELETE. Schema-only, geen backfill.

Revision ID: 0115
Revises: 0114
Create Date: 2026-09-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0115"
down_revision: str | None = "0114"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
SCHEMA = "boekhouding"
TABEL = "planning_signaal_afhandeling"


def upgrade() -> None:
    op.create_table(
        TABEL,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("jaar", sa.SmallInteger(), nullable=False),
        sa.Column("weeknummer", sa.SmallInteger(), nullable=False),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("reden", sa.Text(), nullable=True),
        sa.Column("datum", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("kanaal", sa.Text(), nullable=True),
        sa.Column("detail", JSONB(), nullable=True),
        sa.Column("door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verzonden_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingetrokken_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("ingetrokken_op", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            [f"{SCHEMA}.project_cache.id", f"{SCHEMA}.project_cache.administratie_id"],
            name="fk_planning_signaal_afhandeling_project_cache",
        ),
        sa.CheckConstraint("soort IN ('afgemeld', 'herinnerd')", name="ck_planning_signaal_afhandeling_soort"),
        sa.CheckConstraint("weeknummer BETWEEN 1 AND 53", name="ck_planning_signaal_afhandeling_weeknummer"),
        sa.CheckConstraint(
            "soort != 'afgemeld' OR (reden IS NOT NULL AND length(btrim(reden)) >= 5)",
            name="ck_planning_signaal_afhandeling_afgemeld_reden",
        ),
        sa.CheckConstraint(
            "soort != 'herinnerd' OR (datum IS NOT NULL AND status IN ('bezig', 'verzonden', 'mislukt', 'overgeslagen'))",
            name="ck_planning_signaal_afhandeling_herinnerd_velden",
        ),
        sa.CheckConstraint(
            "(ingetrokken_op IS NULL) = (ingetrokken_door IS NULL)",
            name="ck_planning_signaal_afhandeling_ingetrokken_samen",
        ),
        schema=SCHEMA,
    )
    op.create_index(f"ix_{TABEL}_administratie_id", TABEL, ["administratie_id"], schema=SCHEMA)
    op.create_index(
        f"ix_{TABEL}_combinatie",
        TABEL,
        ["administratie_id", "gebruiker_id", "project_id", "jaar", "weeknummer"],
        schema=SCHEMA,
    )
    # Eén actuele afmelding per combinatie.
    op.create_index(
        "planning_signaal_afgemeld_actief_uniek",
        TABEL,
        ["administratie_id", "gebruiker_id", "project_id", "jaar", "weeknummer"],
        unique=True,
        postgresql_where=sa.text("soort = 'afgemeld' AND ingetrokken_op IS NULL"),
        schema=SCHEMA,
    )
    # Dagrem herinneringen: één rij per (combinatie, dag).
    op.create_index(
        "planning_signaal_herinnerd_dag_uniek",
        TABEL,
        ["administratie_id", "gebruiker_id", "project_id", "jaar", "weeknummer", "datum"],
        unique=True,
        postgresql_where=sa.text("soort = 'herinnerd'"),
        schema=SCHEMA,
    )
    op.execute(f"ALTER TABLE {SCHEMA}.{TABEL} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.{TABEL} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {TABEL}_scope ON {SCHEMA}.{TABEL}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.{TABEL} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON {SCHEMA}.{TABEL} FROM {APP_ROLE}")
    op.execute(f"DROP POLICY IF EXISTS {TABEL}_scope ON {SCHEMA}.{TABEL}")
    op.drop_index("planning_signaal_herinnerd_dag_uniek", table_name=TABEL, schema=SCHEMA)
    op.drop_index("planning_signaal_afgemeld_actief_uniek", table_name=TABEL, schema=SCHEMA)
    op.drop_index(f"ix_{TABEL}_combinatie", table_name=TABEL, schema=SCHEMA)
    op.drop_index(f"ix_{TABEL}_administratie_id", table_name=TABEL, schema=SCHEMA)
    op.drop_table(TABEL, schema=SCHEMA)
