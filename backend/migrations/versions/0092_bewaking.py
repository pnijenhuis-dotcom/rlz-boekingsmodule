"""Synthetische bewaking + alerting (best-practice-besluit 1, 31-08).

- `bewaking_probe_run`: één statusrij per kwartierrun van de rlz-bewaking-job, mét de uitkomst
  per probesoort (health/database/documentopslag/mailkanaal/rlz/ai/extractie_foutratio) —
  nooit RLZ-writes.
- `bewaking_storing`: open/gesloten storing per probesoort; draagt de alert-idempotentie
  (kolom-is-None-patroon, aikosten-mechaniek): alert pas bij de 2e opeenvolgende fout,
  herstelmelding éénmalig. Hooguit één open storing per soort (partial unique).

Platform-breed (systeem-infrastructuur, niet administratie-gebonden) -> geen RLS, conform
migratie 0003/0040-categorie. Geen DELETE-grant: runs en storingen blijven spoor.

Revision ID: 0092
Revises: 0091
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0092"
down_revision: str | None = "0091"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "bewaking_probe_run",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gestart_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("beeindigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("met_ai", sa.Boolean(), nullable=False),
        sa.Column("uitkomsten", JSONB(), nullable=False),
        sa.Column("alles_ok", sa.Boolean(), nullable=False),
        schema="platform",
    )
    op.create_index("ix_bewaking_probe_run_gestart_op", "bewaking_probe_run", ["gestart_op"], schema="platform")

    op.create_table(
        "bewaking_storing",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("begonnen_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("opeenvolgende_fouten", sa.Integer(), nullable=False),
        sa.Column("laatste_fout_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("laatste_detail", sa.Text(), nullable=True),
        sa.Column("alert_verzonden_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hersteld_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("herstel_gemeld_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.create_index(
        "uq_bewaking_storing_open_soort",
        "bewaking_storing",
        ["soort"],
        unique=True,
        schema="platform",
        postgresql_where=sa.text("hersteld_op IS NULL"),
    )

    for tabel in ("bewaking_probe_run", "bewaking_storing"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.{tabel} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("bewaking_storing", schema="platform")
    op.drop_table("bewaking_probe_run", schema="platform")
