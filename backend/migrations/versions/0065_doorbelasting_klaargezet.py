"""Doorbelasting in de boekflow (besluit Peter 25-08, RLZ-feedbackronde punt A — herziet 13-08).

Een doorbelasting-run kon alleen op een GEBOEKT document starten (actie "Doorbelasten…").
Kliktest-bevinding 25-08: een medewerker was twee keer met dezelfde factuur bezig. Voortaan kan
de verdeling al op een NOG NIET geboekt document klaargezet worden (controlescherm-blok
"Doorbelasten na boeken"); de knop wordt "Boeken + doorbelasten" en ná de inkoopboeking draait
dezelfde motor onverkort. Twee nieuwe run-statussen:
- 'klaargezet' — verdeling opgeslagen aan een nog niet geboekt document (koppelfase);
- 'vervallen'  — het vinkje is vóór het boeken weer uitgezet (nooit een delete: de run blijft
  als spoor staan, geauditeerd). Telt als inactief in de één-actieve-run-per-document-index.

Revision ID: 0065
Revises: 0064
Create Date: 2026-08-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("doorbelasting_run_status", "doorbelasting_run", schema="boekhouding", type_="check")
    op.create_check_constraint(
        "doorbelasting_run_status",
        "doorbelasting_run",
        "status IN ('klaargezet', 'concept', 'geboekt', 'gestorneerd', 'vervallen')",
        schema="boekhouding",
    )
    op.drop_index("doorbelasting_run_document_actief_uniek", table_name="doorbelasting_run", schema="boekhouding")
    op.create_index(
        "doorbelasting_run_document_actief_uniek",
        "doorbelasting_run",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('gestorneerd', 'vervallen')"),
        schema="boekhouding",
    )


def downgrade() -> None:
    # Terug kan alleen zonder klaargezette/vervallen runs (CHECK stopt anders hard; mens beslist).
    op.drop_index("doorbelasting_run_document_actief_uniek", table_name="doorbelasting_run", schema="boekhouding")
    op.create_index(
        "doorbelasting_run_document_actief_uniek",
        "doorbelasting_run",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status != 'gestorneerd'"),
        schema="boekhouding",
    )
    op.drop_constraint("doorbelasting_run_status", "doorbelasting_run", schema="boekhouding", type_="check")
    op.create_check_constraint(
        "doorbelasting_run_status",
        "doorbelasting_run",
        "status IN ('concept', 'geboekt', 'gestorneerd')",
        schema="boekhouding",
    )
