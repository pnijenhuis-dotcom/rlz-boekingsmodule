"""Run 2 Vastgoedgroep → Odoo, blok 7b (13-09-2026) — rol "Btw-afwikkeling historisch" op `platform.odoo_koppeling`.

Besluit Peter 13-09: Vastgoedgroep is NIET btw-plichtig; de 883 btw-regels in de RLZ-historie en de OB-aangifte-
bankregels (TEVEELBET/TERUGGAAF OB 3e/4e kwartaal 2025) zijn het gevolg van een foute registratie door de
Belastingdienst, later afgemeld. Elke RLZ-btw-regel gaat naar Odoo als gewone balansregel (zonder tax_ids) op één
rekening "Btw-afwikkeling historisch" (liability_current); de OB-bankmutaties letteren daar tegen af.

- `rekening_btw_afwikkeling_historisch_id`: Odoo `account.account`-id (int, nullable — leeg = rol nog niet vastgesteld,
  de replay meldt documenten mét btw-regels dan zichtbaar als "niet vertaalbaar").

Schema-only.

Revision ID: 0139
Revises: 0138
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0139"
down_revision: str | None = "0138"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

KOLOM = "rekening_btw_afwikkeling_historisch_id"


def upgrade() -> None:
    op.add_column("odoo_koppeling", sa.Column(KOLOM, sa.Integer(), nullable=True), schema="platform")


def downgrade() -> None:
    op.drop_column("odoo_koppeling", KOLOM, schema="platform")
