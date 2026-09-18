"""Veld-app uitvoerder — feedback 18-09 blok B (opdracht Peter 18-09): keuze "Doorfactureren / Niet doorfactureren" per
weekstaat-REGEL (dag × project — beslispunt: regelniveau, niet de hele weekstaat). Kolom `weekstaat_dag.doorfactureren`
boolean NOT NULL DEFAULT true; bestaande regels krijgen true (het gedrag vóór 18-09: álle uren telden als door te
belasten). De default voor een NIEUWE regel leidt de service af uit het project (≥ 1 verrekenbare staffel uit de
contract-ontleding → Doorfactureren, anders Niet) — dat is applicatielogica, niet de kolom-default. Mens wint, audit
oud→nieuw op de dagregel. Schema-only, pure DDL; geen RLS-wijziging (bestaande policy op administratie_id blijft).

Revision ID: 0158
Revises: 0157
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0158"
down_revision: str | None = "0157"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "weekstaat_dag",
        sa.Column("doorfactureren", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_column("weekstaat_dag", "doorfactureren", schema="boekhouding")
