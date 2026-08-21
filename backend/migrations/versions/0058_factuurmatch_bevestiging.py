"""Factuurmatch fase 2 — bevestiging van een match-afwijking (besluit 2, Peter 2026-08-21).

Boeken bij een match-afwijking mág, maar alleen mét expliciete bevestiging ("geboekt ondanks
match-afwijking"). De bevestiging wordt op de match-rij zelf vastgelegd (wie + wanneer) zodat
óók het accorderingspad — waar het boeken pas ná het laatste klant-akkoord door de systeem-
actor gebeurt — de poort deterministisch kan toetsen: bevestigd is bevestigd, ongeacht welke
motor uiteindelijk boekt. Een HERberekening wist de bevestiging (nieuwe cijfers = nieuwe
beslissing — de motor doet dat, app/uren/factuurmatch.py).

Revision ID: 0058
Revises: 0057
Create Date: 2026-08-21

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0058'
down_revision: str | None = '0057'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'factuurmatch',
        sa.Column('afwijking_bevestigd_door', sa.UUID(), nullable=True),
        schema='boekhouding',
    )
    op.add_column(
        'factuurmatch',
        sa.Column('afwijking_bevestigd_op', sa.DateTime(timezone=True), nullable=True),
        schema='boekhouding',
    )
    op.create_foreign_key(
        'fk_factuurmatch_bevestigd_door',
        'factuurmatch',
        'gebruiker',
        ['afwijking_bevestigd_door'],
        ['id'],
        source_schema='boekhouding',
        referent_schema='platform',
    )
    op.create_check_constraint(
        'ck_factuurmatch_bevestigd_samen',
        'factuurmatch',
        '(afwijking_bevestigd_door IS NULL) = (afwijking_bevestigd_op IS NULL)',
        schema='boekhouding',
    )


def downgrade() -> None:
    op.drop_constraint('ck_factuurmatch_bevestigd_samen', 'factuurmatch', schema='boekhouding')
    op.drop_constraint('fk_factuurmatch_bevestigd_door', 'factuurmatch', schema='boekhouding', type_='foreignkey')
    op.drop_column('factuurmatch', 'afwijking_bevestigd_op', schema='boekhouding')
    op.drop_column('factuurmatch', 'afwijking_bevestigd_door', schema='boekhouding')
