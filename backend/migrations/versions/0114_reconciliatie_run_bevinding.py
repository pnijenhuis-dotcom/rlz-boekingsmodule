"""Reconciliatie-melding + Inzicht › Reconciliatie (opdracht 06-09 — BESLISSINGEN "RECONCILIATIE-MELDING +
INZICHT"). De dagelijkse Cloud Run-job `rlz-reconciliatie` meldde alleen via de F3.2-policy op exit ≠ 0;
alles wat exit 0 gaf maar aandacht vroeg (LET-OP-regels, nieuwe GEACCEPTEERD-regels, deels overgeslagen
blokken) bleef onzichtbaar. Vier tabellen in het MODULE-schema boekhouding (module-data hoort niet in het
gedeelde platform-schema):

- `reconciliatie_run` — één rij per run (append-only; statuskolommen van een lopende run bijgewerkt,
  bank_sync_run-patroon). Platformbreed: geen administratie_id, geen RLS (0099-lijn). Draagt de
  samenvatting per blok, de exit-code en de mail-idempotentie (`mail_status`, hooguit één mail per run).
- `reconciliatie_bevinding` — één regel per bevinding (zelfde tekst als de CLI-regel) mét vingerafdruk
  ("nieuw sinds vorige run") en administratie. RLS in de 0004-vorm: administratie_id IS NULL (blokfout
  zonder administratie) óf = current_administratie_id().
- `reconciliatie_gezien` — "Gezien"-snooze op een LET-OP-bevinding (reden verplicht, vervalt ná
  `gezien_dagen`, intrekken = kolom, nooit delete). RLS op administratie_id.
- `reconciliatie_instelling` — Beheerder-singleton `gezien_dagen` (default 90).

Schema-only DDL; GRANT zonder DELETE (niets verdwijnt). Geen backfill: de eerste run vult de historie.

Revision ID: 0114
Revises: 0113
Create Date: 2026-09-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0114"
down_revision: str | None = "0113"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
SCHEMA = "boekhouding"


def upgrade() -> None:
    op.create_table(
        "reconciliatie_run",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="wachtend"),
        sa.Column("bron", sa.Text(), nullable=False, server_default="cli"),
        sa.Column("aangevraagd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("aangevraagd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gestart_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("laatst_actief_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("afgerond_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("samenvatting", JSONB(), nullable=True),
        sa.Column("fout_reden", sa.Text(), nullable=True),
        sa.Column("mail_status", sa.Text(), nullable=True),
        sa.Column("mail_detail", sa.Text(), nullable=True),
        sa.Column("mail_verzonden_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('wachtend', 'bezig', 'klaar', 'fout')", name="ck_reconciliatie_run_status"),
        sa.CheckConstraint("bron IN ('scheduler', 'cli', 'handmatig')", name="ck_reconciliatie_run_bron"),
        schema=SCHEMA,
    )
    op.create_index("ix_reconciliatie_run_status", "reconciliatie_run", ["status"], schema=SCHEMA)
    op.create_index("ix_reconciliatie_run_aangevraagd_op", "reconciliatie_run", ["aangevraagd_op"], schema=SCHEMA)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.reconciliatie_run TO {APP_ROLE}")

    op.create_table(
        "reconciliatie_bevinding",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.reconciliatie_run.id"), nullable=False),
        sa.Column("blok", sa.Text(), nullable=False),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=True),
        sa.Column("vingerafdruk", sa.Text(), nullable=False),
        sa.Column("tekst", sa.Text(), nullable=False),
        sa.Column("detail", JSONB(), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "soort IN ('afwijking', 'let_op', 'geaccepteerd', 'uitgesloten', 'fout')",
            name="ck_reconciliatie_bevinding_soort",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_reconciliatie_bevinding_run_id", "reconciliatie_bevinding", ["run_id"], schema=SCHEMA)
    op.create_index(
        "ix_reconciliatie_bevinding_vingerafdruk", "reconciliatie_bevinding", ["vingerafdruk"], schema=SCHEMA
    )
    op.create_index(
        "ix_reconciliatie_bevinding_administratie_id", "reconciliatie_bevinding", ["administratie_id"], schema=SCHEMA
    )
    op.execute(f"ALTER TABLE {SCHEMA}.reconciliatie_bevinding ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.reconciliatie_bevinding FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY reconciliatie_bevinding_scope ON {SCHEMA}.reconciliatie_bevinding
        USING (administratie_id IS NULL OR administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id IS NULL OR administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.reconciliatie_bevinding TO {APP_ROLE}")

    op.create_table(
        "reconciliatie_gezien",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("blok", sa.Text(), nullable=False),
        sa.Column("vingerafdruk", sa.Text(), nullable=False),
        sa.Column("reden_snapshot", sa.Text(), nullable=True),
        sa.Column("reden", sa.Text(), nullable=False),
        sa.Column("gezien_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("gezien_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("vervalt_op", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingetrokken_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("ingetrokken_op", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "reconciliatie_gezien_actief_uniek",
        "reconciliatie_gezien",
        ["administratie_id", "vingerafdruk"],
        unique=True,
        postgresql_where=sa.text("ingetrokken_op IS NULL"),
        schema=SCHEMA,
    )
    op.execute(f"ALTER TABLE {SCHEMA}.reconciliatie_gezien ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.reconciliatie_gezien FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY reconciliatie_gezien_scope ON {SCHEMA}.reconciliatie_gezien
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.reconciliatie_gezien TO {APP_ROLE}")

    op.create_table(
        "reconciliatie_instelling",
        sa.Column("singleton", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("gezien_dagen", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("gewijzigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("singleton", name="reconciliatie_instelling_singleton"),
        sa.CheckConstraint("gezien_dagen BETWEEN 1 AND 3650", name="ck_reconciliatie_instelling_gezien_dagen"),
        schema=SCHEMA,
    )
    op.execute(f"INSERT INTO {SCHEMA}.reconciliatie_instelling (singleton, gezien_dagen) VALUES (true, 90)")
    op.execute(f"GRANT SELECT, UPDATE ON {SCHEMA}.reconciliatie_instelling TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON {SCHEMA}.reconciliatie_instelling FROM {APP_ROLE}")
    op.drop_table("reconciliatie_instelling", schema=SCHEMA)
    op.execute(f"DROP POLICY IF EXISTS reconciliatie_gezien_scope ON {SCHEMA}.reconciliatie_gezien")
    op.drop_index("reconciliatie_gezien_actief_uniek", table_name="reconciliatie_gezien", schema=SCHEMA)
    op.drop_table("reconciliatie_gezien", schema=SCHEMA)
    op.execute(f"DROP POLICY IF EXISTS reconciliatie_bevinding_scope ON {SCHEMA}.reconciliatie_bevinding")
    op.drop_index("ix_reconciliatie_bevinding_administratie_id", table_name="reconciliatie_bevinding", schema=SCHEMA)
    op.drop_index("ix_reconciliatie_bevinding_vingerafdruk", table_name="reconciliatie_bevinding", schema=SCHEMA)
    op.drop_index("ix_reconciliatie_bevinding_run_id", table_name="reconciliatie_bevinding", schema=SCHEMA)
    op.drop_table("reconciliatie_bevinding", schema=SCHEMA)
    op.drop_index("ix_reconciliatie_run_aangevraagd_op", table_name="reconciliatie_run", schema=SCHEMA)
    op.drop_index("ix_reconciliatie_run_status", table_name="reconciliatie_run", schema=SCHEMA)
    op.drop_table("reconciliatie_run", schema=SCHEMA)
