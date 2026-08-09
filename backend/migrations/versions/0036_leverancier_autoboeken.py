"""Autoboeken-opt-in per leverancier (blok 2 grote opdracht 2026-08-09).

De open poort uit CLAUDE.md ("Autoboeken opt-in per leverancier — vereist vóór het eerste
autoboeken van ínkoopfacturen"): één kolom op de bestaande boekhouding.leverancier_voorkeur
(migratie 0017, PK (administratie_id, vendor_id)) — default UIT, Beheerder-only muteerbaar
(server-side afgedwongen in de router), elke wijziging in audit_event. Het autoboek-pad zelf
(app/documenten/autoboeken.py) draait ná extractie de HARDE CHECKS onverkort en boekt alleen
bij: opt-in aan + checks groen + voorstel volledig uit bevestigd boekingsgeheugen (geen
oranje/seed-only velden) + geen open vraag/afwijzing; volumerem en boeken-toggle gelden
onverkort. NB bank-autoboeken (opt-in per administrátie, migratie 0026) staat hier los van.

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leverancier_voorkeur",
        sa.Column("autoboeken_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_column("leverancier_voorkeur", "autoboeken_ingeschakeld", schema="boekhouding")
