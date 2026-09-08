"""Betaalstatus inkoopfactuur + intake-kanaal (blok 3 bundel 08-09 avond; STAP-0 08-09 in api-verkenning "Betaalstatus
inkoopfactuur — STAP-0 08-09": RLZ's `QuickPaymentSelection` op de PurchaseInvoice is kaal zetbaar, vóór én ná boeken).

- `boekvoorstel.betaalstatus` (Text, nullable): één van de acht RLZ-waarden LETTERLIJK ("Nog te betalen", "Wordt automatisch
  geïncasseerd", "Betaald per bank", "Betaald met PIN", "Betaald met Creditcard", "Betaald - contant", "Verrekend met
  prive", "Verrekend met Rekening Courant") — app/documenten/betaalstatus.py is de bron; NULL = niets te zetten.
- `boekvoorstel.betaalstatus_herkomst` (Text, nullable): 'kanaal' (declaraties@-postvak → Betaald per bank) | 'factuur'
  (deterministische incasso-detectie / UBL PaymentMeansCode 59) | 'mens' (controlescherm, wint altijd).
- `boekvoorstel.verwachte_betaaldatum` (Date, nullable): de incassodatum uit de factuur — kolom voor de bankmatch (blok 2).
- `intake_bericht.kanaal` (Text, NOT NULL, server_default 'facturen'): het postvak waaruit het bericht kwam ('facturen' |
  'declaraties'); bestaande rijen = facturen@.

Schema-only; geen backfill (bestaande voorstellen krijgen de afleiding live bij het openen).

Revision ID: 0126
Revises: 0125
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0126"
down_revision: str | None = "0125"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("boekvoorstel", sa.Column("betaalstatus", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column("boekvoorstel", sa.Column("betaalstatus_herkomst", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column("boekvoorstel", sa.Column("verwachte_betaaldatum", sa.Date(), nullable=True), schema="boekhouding")
    op.create_check_constraint(
        "ck_boekvoorstel_betaalstatus_herkomst",
        "boekvoorstel",
        "betaalstatus_herkomst IS NULL OR betaalstatus_herkomst IN ('kanaal', 'factuur', 'mens')",
        schema="boekhouding",
    )
    op.add_column(
        "intake_bericht",
        sa.Column("kanaal", sa.Text(), nullable=False, server_default="facturen"),
        schema="boekhouding",
    )
    op.create_check_constraint(
        "ck_intake_bericht_kanaal",
        "intake_bericht",
        "kanaal IN ('facturen', 'declaraties')",
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_constraint("ck_intake_bericht_kanaal", "intake_bericht", schema="boekhouding", type_="check")
    op.drop_column("intake_bericht", "kanaal", schema="boekhouding")
    op.drop_constraint("ck_boekvoorstel_betaalstatus_herkomst", "boekvoorstel", schema="boekhouding", type_="check")
    for kolom in ("verwachte_betaaldatum", "betaalstatus_herkomst", "betaalstatus"):
        op.drop_column("boekvoorstel", kolom, schema="boekhouding")
