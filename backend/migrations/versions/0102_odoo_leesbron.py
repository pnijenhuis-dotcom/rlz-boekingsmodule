"""Odoo-adapter blok D — Odoo als LEESBRON voor de voorraad-uitstroom van een RLZ-administratie (casus
Universal Verkoop, company 3: factureert sinds de knip in Odoo, boekt verder in RLZ):

- `platform.odoo_koppeling.alleen_lezen` (default false): een koppeling die uitsluitend leest — mag óók bij
  een administratie met `boekhoud_backend = 'rlz'`; `odoo_client_voor` dwingt dan altijd `read_only=True`
  af (poort: nooit een write op company 3).
- `platform.odoo_koppeling.voorraad_knip_datum` (date, NULL): vanaf deze factuurdatum is Odoo de bron van
  de verkoop-uitstroom — de RLZ-leesroute registreert facturen ≥ knip niet meer, de Odoo-route leest vanaf
  de knip (dedup op factuurnummer als tweede vangnet). NULL = geen knip (alleen-lezen zonder voorraadrol,
  of een echte Odoo-administratie).
Schema-only, geen backfill (bestaande koppelingen blijven schrijvend, zonder knip).

Revision ID: 0102
Revises: 0101
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0102"
down_revision: str | None = "0101"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "odoo_koppeling",
        sa.Column("alleen_lezen", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="platform",
    )
    op.add_column("odoo_koppeling", sa.Column("voorraad_knip_datum", sa.Date(), nullable=True), schema="platform")


def downgrade() -> None:
    op.drop_column("odoo_koppeling", "voorraad_knip_datum", schema="platform")
    op.drop_column("odoo_koppeling", "alleen_lezen", schema="platform")
