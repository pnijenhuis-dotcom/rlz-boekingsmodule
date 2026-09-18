"""Veld-app 12 UX-verbeteringen, run A (akkoord Peter 18-09): omschrijving-chips per administratie.

`platform.administratie.uren_omschrijving_chips` JSONB NULL — de lijst snelkeuze-chips voor het omschrijvingsveld van
een weekstaat-regel in de veld-app (tekst-lijst, GEEN enum). NULL = de standaardlijst uit de code
(`app/uren/service.py::STANDAARD_OMSCHRIJVING_CHIPS`: opbouwen, afbreken, ombouwen, transport, overig). Beheerder-only
zetten via `PUT /uren/beheer/omschrijving-chips/{administratie_id}` (1–10 chips, uniek, ≤ 30 tekens), audit oud→nieuw.
Schema-only, pure DDL; geen RLS-wijziging (bestaande policies op platform.administratie blijven).

Revision ID: 0159
Revises: 0158
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0159"
down_revision: str | None = "0158"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("uren_omschrijving_chips", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "uren_omschrijving_chips", schema="platform")
