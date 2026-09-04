"""Odoo-adapter blok E — overstap van een BESTAANDE RLZ-administratie op Odoo (ingang B van de wizard,
mockup `odoo-koppeling-ui.html`; het Universal-migratiescenario):

- `platform.odoo_koppeling.overgangsdatum` (date, NULL): vanaf deze factuurdatum boekt de administratie in
  Odoo — de inkoop-adapter weigert een factuur mét factuurdatum vóór de overgangsdatum leesbaar (hoort nog in
  Reeleezee). NULL = geen poort (bestaande koppelingen / nieuwe Odoo-administraties zonder RLZ-verleden).
- `platform.odoo_koppeling.rlz_admin_id_voor_overstap` (text, NULL): het oude Reeleezee-administratie-id
  vóór de overstap — `administratie.rlz_admin_id` draagt daarna de Odoo-sentinel (RLZ-jobs slaan de
  administratie zichtbaar over), maar het oude id blijft herleidbaar (archief, RLZ-credential blijft staan).
Schema-only, geen backfill.

Revision ID: 0104
Revises: 0103
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0104"
down_revision: str | None = "0103"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("odoo_koppeling", sa.Column("overgangsdatum", sa.Date(), nullable=True), schema="platform")
    op.add_column(
        "odoo_koppeling", sa.Column("rlz_admin_id_voor_overstap", sa.Text(), nullable=True), schema="platform"
    )


def downgrade() -> None:
    op.drop_column("odoo_koppeling", "rlz_admin_id_voor_overstap", schema="platform")
    op.drop_column("odoo_koppeling", "overgangsdatum", schema="platform")
