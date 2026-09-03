"""Terugkerende facturen kantoorbreed (design-ronde 03-09 blok B1, mockup inzicht-kantoorbreed.html ③):
`boekhouding.terugkerend_herbereken_run` = statusrij van de kantoorbrede achtergrond-herberekening
("⟳ Herbereken alles", 202 + status-poll — het bank_sync_run-/project_cijfers_sync_run-patroon, maar
PLATFORMBREED: één run over álle actieve administraties, dus géén administratie_id en géén RLS-policy
(0092-patroon bewaking_probe_run); `resultaat` = tellers per administratie als JSON). Schema-only DDL;
GRANT zonder DELETE — runs verdwijnen nooit.

Revision ID: 0099
Revises: 0098
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0099"
down_revision: str | None = "0098"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "terugkerend_herbereken_run",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(), nullable=False, server_default="wachtend"),
        sa.Column("gestart_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("aangevraagd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gestart_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("laatst_actief_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("klaar_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aantal_administraties", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aantal_verwerkt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aantal_fouten", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("foutreden", sa.String(), nullable=True),
        sa.Column("resultaat", JSONB(), nullable=True),
        sa.CheckConstraint(
            "status IN ('wachtend', 'bezig', 'klaar', 'fout')", name="ck_terugkerend_herbereken_run_status"
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ix_terugkerend_herbereken_run_status", "terugkerend_herbereken_run", ["status"], schema="boekhouding"
    )
    op.create_index(
        "ix_terugkerend_herbereken_run_aangevraagd_op",
        "terugkerend_herbereken_run",
        ["aangevraagd_op"],
        schema="boekhouding",
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.terugkerend_herbereken_run TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index(
        "ix_terugkerend_herbereken_run_aangevraagd_op", table_name="terugkerend_herbereken_run", schema="boekhouding"
    )
    op.drop_index("ix_terugkerend_herbereken_run_status", table_name="terugkerend_herbereken_run", schema="boekhouding")
    op.drop_table("terugkerend_herbereken_run", schema="boekhouding")
