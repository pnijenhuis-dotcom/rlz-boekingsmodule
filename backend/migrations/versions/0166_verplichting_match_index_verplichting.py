"""Offerte-verbruik telt onderweg-facturen mee (BUG Peter 18-09, casus Bouwadvies Oost Nederland; BESLISSINGEN
"OFFERTE-VERBRUIK = GEBOEKT + ONDERWEG (Peter 18-09)"):

Index `ix_verplichting_match_administratie_verplichting` op `boekhouding.verplichting_match (administratie_id,
verplichting_document_id)`. Het onderweg-verbruik (Σ bedrag van de nog niet geboekte gematchte facturen per verplichting)
wordt per toets berekend en de herberekening ná een statuswissel zoekt de andere open facturen op dezelfde verplichting —
beide per (administratie, verplichting), waar tot nu alleen een index op (administratie, uitkomst) bestond.
Schema-only, pure DDL; geen data-wijziging.

Revision ID: 0166
Revises: 0165
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0166"
down_revision: str | None = "0165"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_verplichting_match_administratie_verplichting",
        "verplichting_match",
        ["administratie_id", "verplichting_document_id"],
        unique=False,
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_verplichting_match_administratie_verplichting", table_name="verplichting_match", schema="boekhouding"
    )
