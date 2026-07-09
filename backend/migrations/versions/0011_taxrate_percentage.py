"""Btw-percentage apart gemodelleerd op taxrate_cache (design-pass controlescherm, taak 3):
empirisch geverifieerd in de live sync-data dat RLZ's TaxRate.Percentage betrouwbaar aanwezig is
(0.21 voor 21% etc.), ondanks dat de officiële resource-documentatie destijds een serverfout gaf
(zie app/sync/models.py). Nodig om het btw-bedrag automatisch te kunnen afleiden (netto x
percentage) en als "code" in de btw-combobox. Backfill uit de al aanwezige `brondata` voor
bestaande rijen — niets verdwijnt stil, geen her-sync nodig.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "taxrate_cache",
        sa.Column("percentage", sa.Numeric(6, 4), nullable=True),
        schema="boekhouding",
    )
    op.execute(
        "UPDATE boekhouding.taxrate_cache "
        "SET percentage = (brondata->>'Percentage')::numeric(6,4) "
        "WHERE brondata->>'Percentage' IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("taxrate_cache", "percentage", schema="boekhouding")
