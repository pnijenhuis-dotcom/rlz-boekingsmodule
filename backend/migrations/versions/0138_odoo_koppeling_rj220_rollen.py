"""Run 2 Vastgoedgroep → Odoo (12-09-2026, blok 4/5) — RJ-220-rollen + migratiedoel op `platform.odoo_koppeling`
(besluit Peter 12-09: vier rollen per administratie in de koppeling-rij, nooit hardcoden; migratie direct naar de live
database company 6 met harde company-pin).

- `rekening_voorraad_panden_id`, `rekening_vooruitbetaald_voorraad_id`, `rekening_opbrengst_panden_id`,
  `rekening_kostprijs_panden_id`: Odoo `account.account`-id's (int, nullable — leeg = rol nog niet vastgesteld, de
  replay meldt dat zichtbaar als "niet vertaalbaar").
- `analytic_overhead_id`: het ene vaste analytic account "Overhead" (plan Project) op de company.
- `migratie_doel`: deze koppeling-rij is het DOEL van een RLZ → Odoo-migratie terwijl `administratie.boekhoud_backend`
  nog 'rlz' is. `app/odoo/credentials.py::koppeling_voor` blijft zo'n rij weigeren voor de dagelijkse adapter; alleen
  `app/migratie/odoo_doel.py` mag 'm gebruiken (company-pin bovenop de client-poort).

Schema-only.

Revision ID: 0138
Revises: 0137
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0138"
down_revision: str | None = "0137"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

KOLOMMEN = (
    "rekening_voorraad_panden_id",
    "rekening_vooruitbetaald_voorraad_id",
    "rekening_opbrengst_panden_id",
    "rekening_kostprijs_panden_id",
    "analytic_overhead_id",
)


def upgrade() -> None:
    for kolom in KOLOMMEN:
        op.add_column("odoo_koppeling", sa.Column(kolom, sa.Integer(), nullable=True), schema="platform")
    op.add_column(
        "odoo_koppeling",
        sa.Column("migratie_doel", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("odoo_koppeling", "migratie_doel", schema="platform")
    for kolom in reversed(KOLOMMEN):
        op.drop_column("odoo_koppeling", kolom, schema="platform")
