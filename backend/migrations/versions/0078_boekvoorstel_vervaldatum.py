"""Vervaldatum op het boekvoorstel (C1 gecombineerde run 26-08, besluit Peter): nieuw kopveld op
het inkoop-controlescherm, vooraf ingevuld uit de AI-extractie (`vervaldatum` zat al in het
veldvoorstel maar werd nergens bewaard), deterministische checks (vervaldatum vóór factuurdatum =
blokkerend; termijn > 90 dagen = oranje signaal) en `DueDate` op de RLZ-PurchaseInvoice (STAP-0
26-08: PUT geaccepteerd, readback identiek). Schema-only.

Revision ID: 0078
Revises: 0077
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("boekvoorstel", sa.Column("vervaldatum", sa.Date(), nullable=True), schema="boekhouding")


def downgrade() -> None:
    op.drop_column("boekvoorstel", "vervaldatum", schema="boekhouding")
