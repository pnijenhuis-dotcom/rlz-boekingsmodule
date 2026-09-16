"""Genormaliseerde factuurreferentie op het boekvoorstel (Peter 16-09, Zenvoices-casus Hello Kitchen / Kempen Facilities):
`boekhouding.boekvoorstel.referentie_norm` = `app/documenten/referentie.py::normaliseer_referentie(referentie)` — één
vergelijkingsvorm voor de duplicaat-/RLZ-bestaanscheck, rlz_dubbel, de bank-matchmotor en de intercompany-factuurmatch.
Schema-only (pure DDL); de vulling van bestaande rijen is de losse data-stap `referentie-norm-backfill`.

Revision ID: 0147
Revises: 0146
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0147"
down_revision: str | None = "0146"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("boekvoorstel", sa.Column("referentie_norm", sa.Text(), nullable=True), schema="boekhouding")
    op.create_index(
        "ix_boekvoorstel_referentie_norm", "boekvoorstel", ["referentie_norm"], unique=False, schema="boekhouding"
    )


def downgrade() -> None:
    op.drop_index("ix_boekvoorstel_referentie_norm", table_name="boekvoorstel", schema="boekhouding")
    op.drop_column("boekvoorstel", "referentie_norm", schema="boekhouding")
