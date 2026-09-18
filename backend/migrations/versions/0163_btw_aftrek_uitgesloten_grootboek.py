"""Btw-bedrag volgt het tarief — aftrek-uitgesloten grootboekrekeningen (opdracht Peter 18-09, casus Rituals 88-186308,
BUA: representatie, relatiegeschenken, personeelsvoorzieningen, kantine).

`platform.grootboekrekening.btw_aftrek_uitgesloten` BOOLEAN NOT NULL DEFAULT false + `btw_aftrek_uitgesloten_op`
TIMESTAMPTZ NULL: kenmerk per administratie × grootboekrekening "op deze rekening is de btw niet aftrekbaar" — de
prefill zet dan 0 %/geen btw én de factuur-btw in de kosten (`regel_prefill.py` stap `grootboek_aftrek_uitgesloten`,
vóór "factuur berekend"). Kolom op de bestaande sync-tabel (zelfde plek als `standaard_taxrate_id` 0142 en de
historie-default 0143) i.p.v. een aparte kenmerk-tabel: het is een eigenschap van precies die (administratie, rekening),
de RLS-policy `grootboekrekening_scope` (0005) dekt 'm al, en de Ledgers-sync schrijft uitsluitend zijn eigen kolommen
(`_grootboek_waarden`) — het kenmerk overleeft élke sync. Beheerder zet 'm via `PUT /administraties/{id}/btw-aftrek-
uitgesloten` (voorstel-lijst mét vinkjes, nooit stil aangezet; audit oud→nieuw). Schema-only, pure DDL; geen data.

Revision ID: 0163
Revises: 0162
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0163"
down_revision: str | None = "0162"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "grootboekrekening",
        sa.Column("btw_aftrek_uitgesloten", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )
    op.add_column(
        "grootboekrekening",
        sa.Column("btw_aftrek_uitgesloten_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("grootboekrekening", "btw_aftrek_uitgesloten_op", schema="platform")
    op.drop_column("grootboekrekening", "btw_aftrek_uitgesloten", schema="platform")
