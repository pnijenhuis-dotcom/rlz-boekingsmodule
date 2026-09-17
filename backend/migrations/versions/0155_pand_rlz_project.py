"""Blok 11 VGG → Odoo (Peter 17-09: "in RLZ staat alles als project geboekt" — project = pand): `pand.rlz_project_id` als
sleutel naar het RLZ-project (nullable; uniek per administratie waar gezet) + herkomst 'rlz_project' náást 'afgeleid'/'mens'.
Schema-only, pure DDL. Adres-clustering blijft de terugval voor documenten zonder project (mens wint, `herkomst='mens'`
wordt nooit overschreven — ongewijzigd). Geen RLS-wijziging (bestaande policy op administratie_id blijft gelden).

Revision ID: 0155
Revises: 0154
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0155"
down_revision: str | None = "0154"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pand", sa.Column("rlz_project_id", postgresql.UUID(as_uuid=True), nullable=True), schema="boekhouding")
    op.add_column("pand", sa.Column("rlz_project_naam", sa.Text(), nullable=True), schema="boekhouding")
    op.create_index(
        "ux_pand_rlz_project",
        "pand",
        ["administratie_id", "rlz_project_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("rlz_project_id IS NOT NULL"),
    )
    op.drop_constraint("ck_pand_herkomst", "pand", schema="boekhouding", type_="check")
    op.create_check_constraint(
        "ck_pand_herkomst", "pand", "herkomst IN ('afgeleid', 'mens', 'rlz_project')", schema="boekhouding"
    )


def downgrade() -> None:
    op.execute("UPDATE boekhouding.pand SET herkomst = 'afgeleid' WHERE herkomst = 'rlz_project'")
    op.drop_constraint("ck_pand_herkomst", "pand", schema="boekhouding", type_="check")
    op.create_check_constraint("ck_pand_herkomst", "pand", "herkomst IN ('afgeleid', 'mens')", schema="boekhouding")
    op.drop_index("ux_pand_rlz_project", table_name="pand", schema="boekhouding")
    op.drop_column("pand", "rlz_project_naam", schema="boekhouding")
    op.drop_column("pand", "rlz_project_id", schema="boekhouding")
