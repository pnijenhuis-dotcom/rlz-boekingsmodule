"""Eerste sync ná groene probe: 403 = herproberen (blok 3 run 11-09 middag).

Bevinding Peter 11-09 (Baard / Box Beheer / Kempen B.V.): RLZ zet de rechten van een verse API-koppeling met
vertraging door — probe groen om 11:5x, eerste sync 403 direct erna, RLZ-check groen de volgende ochtend. Een 403
op een route die de probe net groen had is daarom geen fout maar "RLZ zet rechten door": de run krijgt status
`rechten_onderweg` en wordt automatisch herprobeerd (5, 15, 60 min, daarna elk uur, max 24 u).

Twee kolommen op `boekhouding.administratie_sync_run` (schema-only, geen backfill nodig — bestaande rijen zijn
klaar/fout en hebben 0 pogingen) + de status-check `ck_administratie_sync_run_status` (0076) krijgt de nieuwe waarde:
  * `pogingen`            — aantal afgeronde pogingen van deze run (eerste poging = 1 zodra hij afgerond is);
  * `volgende_poging_op`  — wanneer de wekker (kwartier-job rlz-bewaking) de run opnieuw in de wachtrij zet;
                            alleen gevuld bij status `rechten_onderweg`.

Revision ID: 0133
Revises: 0132
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0133"
down_revision: str | None = "0132"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_STATUSSEN_OUD = "status IN ('wachtrij', 'bezig', 'klaar', 'fout')"
_STATUSSEN_NIEUW = "status IN ('wachtrij', 'bezig', 'klaar', 'fout', 'rechten_onderweg')"


def upgrade() -> None:
    op.drop_constraint(
        "ck_administratie_sync_run_status", "administratie_sync_run", schema="boekhouding", type_="check"
    )
    op.create_check_constraint(
        "ck_administratie_sync_run_status", "administratie_sync_run", _STATUSSEN_NIEUW, schema="boekhouding"
    )
    op.add_column(
        "administratie_sync_run",
        sa.Column("pogingen", sa.Integer(), nullable=False, server_default="0"),
        schema="boekhouding",
    )
    op.add_column(
        "administratie_sync_run",
        sa.Column("volgende_poging_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_administratie_sync_run_volgende_poging",
        "administratie_sync_run",
        ["status", "volgende_poging_op"],
        schema="boekhouding",
    )


def downgrade() -> None:
    # Een rij in `rechten_onderweg` moet vóór het terugdraaien handmatig op 'fout' gezet zijn (data-stap, niet hier).
    op.drop_constraint(
        "ck_administratie_sync_run_status", "administratie_sync_run", schema="boekhouding", type_="check"
    )
    op.create_check_constraint(
        "ck_administratie_sync_run_status", "administratie_sync_run", _STATUSSEN_OUD, schema="boekhouding"
    )
    op.drop_index(
        "ix_administratie_sync_run_volgende_poging", table_name="administratie_sync_run", schema="boekhouding"
    )
    op.drop_column("administratie_sync_run", "volgende_poging_op", schema="boekhouding")
    op.drop_column("administratie_sync_run", "pogingen", schema="boekhouding")
