"""Vastly-verkoop: administratie-id uit de UBL als eerste bron (Peter 01-10 "vastly facturen 100% auto zonder menselijke
tussenstap … hou het simpel"; koppelcontract §2d-notitie 01-10 avond `RLZ-ADMINISTRATIE:<platform administratie-uuid>`).

`boekhouding.vastly_entiteit_koppeling.bron` kent naast 'identiteit' en 'mens' (0172) de bron 'ubl': de rij die het
administratie-id uit de UBL op de primaire sleutel (KvK, anders naam) vastlegt. De mens-koppeling via de bevinding is per
01-10 vervallen; bestaande 'mens'-rijen blijven staan (lezen). Schema-only (CHECK verruimd), geen data-stap.

Revision ID: 0173
Revises: 0172
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0173"
down_revision: str | None = "0172"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_vastly_entiteit_koppeling_bron", "vastly_entiteit_koppeling", schema="boekhouding", type_="check"
    )
    op.create_check_constraint(
        "ck_vastly_entiteit_koppeling_bron",
        "vastly_entiteit_koppeling",
        "bron IN ('identiteit', 'mens', 'ubl')",
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_vastly_entiteit_koppeling_bron", "vastly_entiteit_koppeling", schema="boekhouding", type_="check"
    )
    op.create_check_constraint(
        "ck_vastly_entiteit_koppeling_bron",
        "vastly_entiteit_koppeling",
        "bron IN ('identiteit', 'mens')",
        schema="boekhouding",
    )
