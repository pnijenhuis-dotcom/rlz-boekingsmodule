"""Intake: tweede facturenpostvak facturen@kempengroep.nl DIRECT gelezen + verwerkt-administratie op Message-ID
(Peter 22-09 "er zijn facturen gemaild die niet in onze module staan"; BESLISSINGEN "INTAKE — TWEEDE POSTVAK
KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)").

1. `intake_bericht.kanaal` krijgt de waarde 'facturen_kempengroep' (CHECK-constraint verruimd).
2. Nieuwe tabel `boekhouding.intake_bericht_verwerkt` (kanaal, message_id, uid, postvak_map, verwerkt_op, uitkomst,
   intake_bericht_id, detail): de fetch leest sinds 23-09 ALLE berichten in het venster (INBOX + spam-map) en slaat
   over wat hier of in `intake_bericht` staat — de IMAP-gelezen-vlag is geen verwerkt-administratie meer.
Schema-only (pure DDL); de herstelrun over 60 dagen is een losse job-executie (`intake-postvak-verwerken --sinds`).

Revision ID: 0171
Revises: 0170
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0171"
down_revision: str | None = "0170"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None
APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.drop_constraint("ck_intake_bericht_kanaal", "intake_bericht", schema="boekhouding", type_="check")
    op.create_check_constraint(
        "ck_intake_bericht_kanaal",
        "intake_bericht",
        "kanaal IN ('facturen', 'declaraties', 'facturen_kempengroep')",
        schema="boekhouding",
    )
    op.create_table(
        "intake_bericht_verwerkt",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kanaal", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("uid", sa.Text(), nullable=True),
        sa.Column("postvak_map", sa.Text(), nullable=False, server_default="INBOX"),
        sa.Column("verwerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("uitkomst", sa.Text(), nullable=False),
        sa.Column(
            "intake_bericht_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("boekhouding.intake_bericht.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "uitkomst IN ('verwerkt', 'al_bekend', 'niet_verwerkbaar')", name="ck_intake_bericht_verwerkt_uitkomst"
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ux_intake_bericht_verwerkt_kanaal_message_id",
        "intake_bericht_verwerkt",
        ["kanaal", "message_id"],
        unique=True,
        schema="boekhouding",
    )
    op.create_index(
        "ix_intake_bericht_verwerkt_verwerkt_op", "intake_bericht_verwerkt", ["verwerkt_op"], schema="boekhouding"
    )
    # RLS als bij intake_bericht (0028): platformbrede intake-tabel, policy USING (true) mét RLS+FORCE als
    # vangnet-structuur; toegang begrensd door de applicatielaag. GRANT zonder DELETE (niets verdwijnt).
    op.execute("ALTER TABLE boekhouding.intake_bericht_verwerkt ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.intake_bericht_verwerkt FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY intake_bericht_verwerkt_scope ON boekhouding.intake_bericht_verwerkt
        USING (true)
        WITH CHECK (true)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.intake_bericht_verwerkt TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_intake_bericht_verwerkt_verwerkt_op", table_name="intake_bericht_verwerkt", schema="boekhouding")
    op.drop_index(
        "ux_intake_bericht_verwerkt_kanaal_message_id", table_name="intake_bericht_verwerkt", schema="boekhouding"
    )
    op.drop_table("intake_bericht_verwerkt", schema="boekhouding")
    op.drop_constraint("ck_intake_bericht_kanaal", "intake_bericht", schema="boekhouding", type_="check")
    op.create_check_constraint(
        "ck_intake_bericht_kanaal", "intake_bericht", "kanaal IN ('facturen', 'declaraties')", schema="boekhouding"
    )
