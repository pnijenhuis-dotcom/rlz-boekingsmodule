"""Versheid-probe-failsafe: fout-kolom op payment_account_cache (kliktest-fix 2026-08-08).

De LastBankImport-probe bleek de hele bank-sync te kunnen afbreken (`make bank-sync` → 0/3):
RLZ geeft `400 _InvalidData` op rekeningtypes zonder aanleverpad (kas 3, verrekeningen 4,
RC/privé 5) en op gearchiveerde rekeningen, en zelfs HTTP 200 mét een HTML-pagina op een
bankrekening die nooit een import zag. De fix behandelt die vormen als "geen aanlevering";
deze kolom is de failsafe voor al het overige: een onverwacht falende probe wordt zíchtbaar
op de rekening-rij gezet (NULL = probe ok, anders de fouttekst) terwijl de sync doordraait
en `laatste_import` zijn laatst-bekende waarde houdt.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_account_cache",
        sa.Column("laatste_import_probe_fout", sa.Text(), nullable=True),
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_column("payment_account_cache", "laatste_import_probe_fout", schema="boekhouding")
