"""Pro-rato-periode "heel jaar" (blok D4 fixrun 07-09, opdracht Peter; mockup projectverdeling-en-
regelvoorstellen.html notitie ⑩). Naast een kalendermaand kan de pro-rato-verdeling nu de omzet per project
over de AFGESLOTEN maanden van een kalenderjaar (huidig óf vorig jaar) als gewicht nemen. De bestaande kolom
`pro_rato_periode` is een DATE (eerste dag van de maand); een jaar wordt opgeslagen als 1 januari van dat jaar
+ de nieuwe soort-kolom — zo blijft januari ('maand', 01-01) ondubbelzinnig te onderscheiden van het hele jaar
('jaar', 01-01). Bestaande rijen zijn alle maanden (server_default 'maand'); geen backfill nodig.

Revision ID: 0119
Revises: 0118
Create Date: 2026-09-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0119"
down_revision: str | None = "0118"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projectverdeling",
        sa.Column("pro_rato_soort", sa.Text(), nullable=False, server_default="maand"),
        schema="boekhouding",
    )
    op.create_check_constraint(
        "ck_projectverdeling_pro_rato_soort",
        "projectverdeling",
        "pro_rato_soort IN ('maand', 'jaar')",
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_constraint("ck_projectverdeling_pro_rato_soort", "projectverdeling", schema="boekhouding", type_="check")
    op.drop_column("projectverdeling", "pro_rato_soort", schema="boekhouding")
