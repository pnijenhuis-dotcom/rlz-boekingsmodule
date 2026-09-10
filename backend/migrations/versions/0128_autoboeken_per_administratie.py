"""Blok A bundel 10-09 — autoboeken per administratie (schakelaar, uitzonderingen, reset-stand, drempel-default 3).

Besluit Peter 10-09 (herziet "kandidaten → mens klikt aan" van 01-09): één Beheerder-schakelaar per administratie
"Autoboeken (leren en boeken)", default UIT; het systeem activeert leveranciers zelf zodra ≥ N (platformbreed 3) op rij
exact hetzelfde door een MENS in de module is geboekt. De bestaande per-leverancier-lijst wordt een
uitzonderingenlijst; storno/correctie van een automatische boeking zet de leverancier terug op "leert 0/N".

- `platform.administratie.autoboeken_leren_ingeschakeld`     — de schakelaar (default false; Kempen-regel server-side:
                                                               doorbelasting_ingeschakeld → nooit aan).
- `boekhouding.leverancier_voorkeur.autoboeken_uitgezonderd`  — mens heeft deze leverancier uitgezonderd (systeem activeert nooit).
- `boekhouding.leverancier_voorkeur.autoboeken_uitzondering_reden` — de verplichte reden bij uitzonderen (leesbaar in de lijst).
- `boekhouding.leverancier_voorkeur.autoboeken_bron`          — 'mens' | 'systeem': wie zette de opt-in aan.
- `boekhouding.leverancier_voorkeur.autoboeken_gereset_op`    — reset-moment ná storno/correctie; de reeks telt alleen
                                                               mens-boekingen ná dit moment.
- `platform.autoboek_instelling.drempel_op_rij`               — server_default 5 → 3 (geen data-UPDATE: de productie-rij
                                                               staat op 5 en gaat via CLI `autoboek-drempel-zetten --drempel 3`
                                                               mét audit naar 3 — schema-only hier).

Schema-only (pure DDL); geen backfill.

Revision ID: 0128
Revises: 0127
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0128"
down_revision: str | None = "0127"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("autoboeken_leren_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )
    op.add_column(
        "leverancier_voorkeur",
        sa.Column("autoboeken_uitgezonderd", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="boekhouding",
    )
    op.add_column(
        "leverancier_voorkeur",
        sa.Column("autoboeken_uitzondering_reden", sa.Text(), nullable=True),
        schema="boekhouding",
    )
    op.add_column(
        "leverancier_voorkeur",
        sa.Column("autoboeken_bron", sa.Text(), nullable=True),
        schema="boekhouding",
    )
    op.add_column(
        "leverancier_voorkeur",
        sa.Column("autoboeken_gereset_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.alter_column(
        "autoboek_instelling",
        "drempel_op_rij",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default="3",
        schema="platform",
    )


def downgrade() -> None:
    op.alter_column(
        "autoboek_instelling",
        "drempel_op_rij",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default="5",
        schema="platform",
    )
    op.drop_column("leverancier_voorkeur", "autoboeken_gereset_op", schema="boekhouding")
    op.drop_column("leverancier_voorkeur", "autoboeken_bron", schema="boekhouding")
    op.drop_column("leverancier_voorkeur", "autoboeken_uitzondering_reden", schema="boekhouding")
    op.drop_column("leverancier_voorkeur", "autoboeken_uitgezonderd", schema="boekhouding")
    op.drop_column("administratie", "autoboeken_leren_ingeschakeld", schema="platform")
