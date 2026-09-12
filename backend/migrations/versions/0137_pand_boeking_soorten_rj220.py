"""Run 2 Vastgoedgroep → Odoo (12-09-2026, blok 3) — pand_boeking.soort uitgebreid conform RJ 220 (besluit Peter 12-09):

- `aanbetaling` = vooruitbetaald op handelsvoorraad (balans), bij levering in de kostprijs van het pand;
- `vaste_lasten` = lasten die VGG voor de verkoper betaalt: W&V op factuur-/mutatiedatum, nooit activeren;
- `balans` = jaareinde-/balansboeking (31-12-memorialen) mét pand-adres: zichtbaar, nooit een aankoopdatum.

Schema-only (alleen de CHECK-constraint); bestaande waarden aankoop/verkoop/kosten/overhead blijven geldig.

Revision ID: 0137
Revises: 0136
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0137"
down_revision: str | None = "0136"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

SOORTEN_OUD = "('aankoop', 'verkoop', 'kosten', 'overhead')"
SOORTEN_NIEUW = "('aankoop', 'verkoop', 'kosten', 'overhead', 'aanbetaling', 'vaste_lasten', 'balans')"


def upgrade() -> None:
    op.drop_constraint("ck_pand_boeking_soort", "pand_boeking", schema="boekhouding", type_="check")
    op.create_check_constraint("ck_pand_boeking_soort", "pand_boeking", f"soort IN {SOORTEN_NIEUW}", schema="boekhouding")


def downgrade() -> None:
    op.execute(
        "DELETE FROM boekhouding.pand_boeking WHERE soort IN ('aanbetaling', 'vaste_lasten', 'balans')"
    )  # alleen bij downgrade (test-DB); productie downgrade't nooit
    op.drop_constraint("ck_pand_boeking_soort", "pand_boeking", schema="boekhouding", type_="check")
    op.create_check_constraint("ck_pand_boeking_soort", "pand_boeking", f"soort IN {SOORTEN_OUD}", schema="boekhouding")
