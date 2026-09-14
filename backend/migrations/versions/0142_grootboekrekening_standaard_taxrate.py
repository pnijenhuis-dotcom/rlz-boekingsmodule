"""Btw-default uit de RLZ-grootboekrekening (opdracht Peter 14-09, casus L.H.G. Holding "Kosten mobiele telefonie").

`platform.grootboekrekening.standaard_taxrate_id` (uuid, NULL): het standaard-btw-tarief dat de bron op de rekening
draagt — RLZ `Account.PreferentialTaxRate` (STAP-0 14-09: het veld staat op het Account-DTO en is via
`Ledgers?$expand=PreferentialTaxRate` leesbaar; api-verkenning "Ledgers — standaard btw-code, STAP-0 14-09"),
Odoo de enige inkoop-belasting in `account.account.tax_ids`. Gevuld door de bestaande Ledgers-sync (één leesroute,
app/rlz/leesroutes.py); backfill = de eerstvolgende `sync-alles`, geen aparte job. NULL = geen default in de bron.

Bewust geen FK naar `boekhouding.taxrate_cache` (zelfde overweging als 0108 `administratie.standaard_taxrate_id`): de
grootboek-sync loopt vóór de btw-sync en een in RLZ verdwenen tarief mag de rekening-rij nooit blokkeren — de prefill
(app/documenten/regel_prefill.py) toetst het tarief tegen de actuele cache. Schema-only (DDL), geen data.

Revision ID: 0142
Revises: 0141
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0142"
down_revision: str | None = "0141"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "grootboekrekening",
        sa.Column("standaard_taxrate_id", UUID(as_uuid=True), nullable=True),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("grootboekrekening", "standaard_taxrate_id", schema="platform")
