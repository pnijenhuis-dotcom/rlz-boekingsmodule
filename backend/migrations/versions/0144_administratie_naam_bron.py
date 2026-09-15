"""Administratienaam — bewerkbaar in de module + volgt de bron (opdracht Peter 15-09; casus Camping "Nieuwenhoven" →
in Odoo hernoemd naar "Strandpark Zilverduynen" ná het koppelen).

Kolommen op `platform.administratie`:
- `naam_bron` TEXT NOT NULL DEFAULT 'mens' — 'odoo' | 'rlz' | 'mens'. Bij ≠ 'mens' volgt de module de bronnaam
  automatisch bij élke stamgegevens-sync (audit `administratie_naam_gevolgd` oud→nieuw); bij 'mens' nooit overschrijven,
  wél de afwijkende bronnaam tonen mét "Naam overnemen". DB-default 'mens' = fail-closed (geen enkele bestaande naam
  wordt stil overschreven); de data-stap `administratie-naam-bron-backfill` (CLI, dry-run default) zet 'rlz'/'odoo' waar
  de huidige naam gelijk is aan de bronnaam.
- `bron_naam` TEXT NULL — de laatst gelezen naam in de bron (Odoo `res.company.name` / RLZ `Administrations.Name`);
- `bron_naam_gezien_op` TIMESTAMPTZ NULL — moment van die lezing;
- `naam_gevolgd_op` TIMESTAMPTZ NULL — moment waarop de module de naam voor het laatst uit de bron heeft overgenomen.
Schema-only (DDL); CHECK op de drie toegestane waarden.

Revision ID: 0144
Revises: 0143
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0144"
down_revision: str | None = "0143"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("naam_bron", sa.Text(), nullable=False, server_default="mens"),
        schema="platform",
    )
    op.add_column("administratie", sa.Column("bron_naam", sa.Text(), nullable=True), schema="platform")
    op.add_column(
        "administratie",
        sa.Column("bron_naam_gezien_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.add_column(
        "administratie",
        sa.Column("naam_gevolgd_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.create_check_constraint(
        "ck_administratie_naam_bron", "administratie", "naam_bron IN ('odoo', 'rlz', 'mens')", schema="platform"
    )


def downgrade() -> None:
    op.drop_constraint("ck_administratie_naam_bron", "administratie", schema="platform", type_="check")
    op.drop_column("administratie", "naam_gevolgd_op", schema="platform")
    op.drop_column("administratie", "bron_naam_gezien_op", schema="platform")
    op.drop_column("administratie", "bron_naam", schema="platform")
    op.drop_column("administratie", "naam_bron", schema="platform")
