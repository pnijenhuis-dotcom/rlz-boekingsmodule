"""Duplicaten-UI (blok 3, fixrun 08-09, feedback Peter — screenshot Universal Steigerbouw):
afgevoerde duplicaten stonden nog op de tab "Mogelijk duplicaat" en in "Afgewezen — ter controle"
omdat duplicaat-afvoer schreef naar `document_status = 'afgewezen'` (mét kruisverwijzing) i.p.v.
een eigen status. Eigen TERMINALE PG-enumwaarde `afgevoerd_duplicaat` — geen afwijzen-substatus.
Schema-only (geen backfill; de backfill is een losse data-stap, CLI `duplicaat-status-backfill`).

Revision ID: 0122
Revises: 0121
Create Date: 2026-09-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0122"
down_revision: str | None = "0121"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE mag sinds PG12 binnen een transactie zolang de waarde niet in dezelfde transactie
    # gebruikt wordt (zelfde patroon als migraties 0016/0028/0098).
    op.execute("ALTER TYPE boekhouding.document_status ADD VALUE IF NOT EXISTS 'afgevoerd_duplicaat' AFTER 'geaccordeerd'")


def downgrade() -> None:
    # PostgreSQL kent geen DROP VALUE — de enum-waarde blijft bewust staan (zelfde keuze als 0028/0098).
    pass
