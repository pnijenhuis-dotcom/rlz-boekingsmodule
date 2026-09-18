"""Klant-accordering — leveranciersroute "bovenop de gewone route" (Peter 18-09, casus Bouwadvies Oost Nederland: drie
gewone lagen + een vierde laag voor twee leveranciers).

- `boekhouding.accordering_leverancier_route.modus` TEXT NOT NULL DEFAULT 'vervangt' — 'vervangt' = de route VERVANGT de
  administratieroute voor de aangevinkte leveranciers (bestaand gedrag, 17-09); 'bovenop' = de gewone lagen van de administratie
  op het moment van de ronde + de extra lagen van deze route op `positie`.
- `positie` TEXT NULL — 'voor' (vóór laag 1) of 'na' (ná de laatste gewone laag); alleen gevuld bij modus 'bovenop'.
Bestaande routes = 'vervangt' (server-default). Schema-only, pure DDL; geen RLS-wijziging (kolommen op een bestaande tabel).

Revision ID: 0164
Revises: 0163
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0164"
down_revision: str | None = "0163"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

TABEL = "accordering_leverancier_route"


def upgrade() -> None:
    op.add_column(
        TABEL,
        sa.Column("modus", sa.Text(), nullable=False, server_default="vervangt"),
        schema="boekhouding",
    )
    op.add_column(TABEL, sa.Column("positie", sa.Text(), nullable=True), schema="boekhouding")
    op.create_check_constraint(
        "ck_accordering_leverancier_route_modus", TABEL, "modus IN ('vervangt', 'bovenop')", schema="boekhouding"
    )
    op.create_check_constraint(
        "ck_accordering_leverancier_route_positie",
        TABEL,
        "positie IS NULL OR positie IN ('voor', 'na')",
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_constraint("ck_accordering_leverancier_route_positie", TABEL, schema="boekhouding", type_="check")
    op.drop_constraint("ck_accordering_leverancier_route_modus", TABEL, schema="boekhouding", type_="check")
    op.drop_column(TABEL, "positie", schema="boekhouding")
    op.drop_column(TABEL, "modus", schema="boekhouding")
