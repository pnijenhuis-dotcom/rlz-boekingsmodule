"""Btw-default per grootboekrekening AFGELEID UIT DE HISTORIE (vervolg-opdracht Cowork/Peter 14-09 op 0142).

STAP-0 14-09: `Account.PreferentialTaxRate` is in álle gemeten administraties null — de RLZ-default van 0142 vult in de
praktijk niets en Peter vult dat niet in RLZ in voor 71 administraties. Daarom leidt de module de default zelf af uit
de inkoopregels in het boekingsgeheugen (`boekhouding.boeking_observatie`: RLZ-seed + app-boekingen, laatste 24
maanden): per administratie × grootboekrekening de verdeling van het btw-tarief; ≥ 5 regels én één tarief op ≥ 90 % =
historie-default. Deterministisch (code, geen AI), nachtelijk in `sync-alles` en ná de eerste sync.

Kolommen op `platform.grootboekrekening`:
- `historie_taxrate_id` UUID NULL — het afgeleide tarief; NULL = geen (te weinig regels of te verdeeld);
- `historie_taxrate_n` INTEGER NULL — aantal inkoopregels in het venster (ook gevuld als er géén default uit volgt, zodat
  het rapport "geen — 10 regels, hoogste 80 %" kan zeggen);
- `historie_taxrate_aandeel` NUMERIC(5,4) NULL — aandeel van het MEEST voorkomende tarief (0–1);
- `historie_berekend_op` TIMESTAMPTZ NULL — moment van de laatste afleiding.
Bewust geen FK naar `taxrate_cache` (zelfde overweging als 0108/0142): de prefill toetst het tarief tegen de cache.
Schema-only (DDL); de vulling is de eerstvolgende `sync-alles`.

Revision ID: 0143
Revises: 0142
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0143"
down_revision: str | None = "0142"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "grootboekrekening", sa.Column("historie_taxrate_id", UUID(as_uuid=True), nullable=True), schema="platform"
    )
    op.add_column("grootboekrekening", sa.Column("historie_taxrate_n", sa.Integer(), nullable=True), schema="platform")
    op.add_column(
        "grootboekrekening",
        sa.Column("historie_taxrate_aandeel", sa.Numeric(5, 4), nullable=True),
        schema="platform",
    )
    op.add_column(
        "grootboekrekening",
        sa.Column("historie_berekend_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("grootboekrekening", "historie_berekend_op", schema="platform")
    op.drop_column("grootboekrekening", "historie_taxrate_aandeel", schema="platform")
    op.drop_column("grootboekrekening", "historie_taxrate_n", schema="platform")
    op.drop_column("grootboekrekening", "historie_taxrate_id", schema="platform")
