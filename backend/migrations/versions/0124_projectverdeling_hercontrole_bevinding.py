"""Hercontrole projectverdeling — bevinding "omzetcijfers ontbreken" (blok 10 herstelrun "Basis eerst" 08-09-2026).

Bevinding Universal Steigerbouw 08-09 (5 "signalen" met 0 % en een lege nieuwe verdeling): de motor schreef bij het
BOEKEN `hercontrole_verdeling = None` via een JSONB-kolom zónder `none_as_null` → JSON `null` i.p.v. SQL NULL, waardoor
`IS NOT NULL` (lijst-chip + Inzicht › Projectverdeling) élke pas geboekte verdeling als signaal aanmerkte. De kolomtype-fix
zit in het model (`JSONB(none_as_null=True)`, geen DDL); de lezers toetsen sindsdien op `jsonb_typeof = 'array'`.

Déze migratie: `boekhouding.projectverdeling.hercontrole_bevinding` (text, NULL; CHECK 'omzet_ontbreekt') — een
ontbrekende omzetstand voor de referentieperiode is sinds blok 10 GEEN herverdeling maar een eigen, zichtbare bevinding
mét actie "cijfers-sync starten" (herverdelen geblokkeerd tot er cijfers zijn). Schema-only, geen backfill: de
eerstvolgende hercontrole-ronde normaliseert de bestaande JSON-null-rijen zelf.

Revision ID: 0124
Revises: 0123
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0124"
down_revision: str | None = "0123"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projectverdeling",
        sa.Column("hercontrole_bevinding", sa.Text(), nullable=True),
        schema="boekhouding",
    )
    op.create_check_constraint(
        "ck_projectverdeling_hercontrole_bevinding",
        "projectverdeling",
        "hercontrole_bevinding IS NULL OR hercontrole_bevinding IN ('omzet_ontbreekt')",
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_constraint("ck_projectverdeling_hercontrole_bevinding", "projectverdeling", schema="boekhouding")
    op.drop_column("projectverdeling", "hercontrole_bevinding", schema="boekhouding")
