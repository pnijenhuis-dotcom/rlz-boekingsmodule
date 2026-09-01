"""Wizard: RLZ zonder facturatiemodule toestaan (spoedopdracht 01-09 blok A, casus A.Y. Holding 2 +
Abbegaa — bevestigd door Peter in de RLZ-UI):

- `platform.administratie.verkoopmodule_afwezig`: persistent kenmerk "facturatiemodule niet
  afgenomen". Sommige RLZ-administraties hebben de facturatie-/verkoopmodule niet actief; de
  SalesInvoices-collectie geeft dan 403 ongeacht de gebruikersrechten. De rechten-probe behandelt
  UITSLUITEND die 403 als niet-blokkerende uitkomst (wizard sluit aan mét waarschuwing); het kenmerk
  schakelt álle verkoop-rakende leesroutes uit (voorraad-RLZ-uitstroom, SalesInvoices-collectie in de
  projectcijfers-sync) — nooit stil laten falen op de 403. Een latere herprobe mét SalesInvoices "ok"
  haalt het kenmerk weer weg (beide kanten geauditeerd, oud→nieuw).

Schema-only, geen data-stap: bestaande administraties hebben de module (server_default false).

Revision ID: 0093
Revises: 0092
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0093"
down_revision: str | None = "0092"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("verkoopmodule_afwezig", sa.Boolean(), nullable=False, server_default="false"),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "verkoopmodule_afwezig", schema="platform")
