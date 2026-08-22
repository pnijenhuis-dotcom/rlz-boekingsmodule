"""Planning-agenda steigerbouw (mockup planning-steigerbouw.html, definitief akkoord Peter
2026-08-22 — ontwerpronde-besluiten A/B/C + failsafe, BESLISSINGEN "PLANNING-AGENDA").

boekhouding.planning_toewijzing: het kantoor plant ZZP'ers/uitvoerders per dag op actieve
projecten (weekgrid, sleepbare kaartjes). De samengestelde PK (administratie, gebruiker,
project, datum) ís de harde failsafe: dezelfde persoon nooit 2× op dezelfde dag op hetzélfde
project; meerdere personen per project/dag en (via het dagdeel heel/half) meerdere projecten
per persoon/dag blijven geldig. RLS op administratie (patroon 0056); grants SELECT, INSERT,
UPDATE, DELETE — weghalen uit de planning mag (werkplanning, geen financiële registratie),
maar élke mutatie loopt via de service mét audit_event (app/uren/planning.py).

Revision ID: 0060
Revises: 0059
Create Date: 2026-08-22

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0060'
down_revision: str | None = '0059'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table('planning_toewijzing',
    sa.Column('administratie_id', sa.UUID(), nullable=False),
    sa.Column('gebruiker_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('datum', sa.Date(), nullable=False),
    sa.Column('dagdeel', sa.Text(), nullable=False),
    sa.Column('toegevoegd_door', sa.UUID(), nullable=False),
    sa.Column('aangemaakt_op', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('bijgewerkt_op', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("dagdeel IN ('heel', 'half')", name='ck_planning_toewijzing_dagdeel'),
    sa.ForeignKeyConstraint(['administratie_id'], ['platform.administratie.id'], ),
    sa.ForeignKeyConstraint(['gebruiker_id'], ['platform.gebruiker.id'], ),
    sa.ForeignKeyConstraint(['project_id', 'administratie_id'], ['boekhouding.project_cache.id', 'boekhouding.project_cache.administratie_id'], name='fk_planning_toewijzing_project_cache'),
    sa.ForeignKeyConstraint(['toegevoegd_door'], ['platform.gebruiker.id'], ),
    sa.PrimaryKeyConstraint('administratie_id', 'gebruiker_id', 'project_id', 'datum'),
    schema='boekhouding'
    )
    op.create_index('ix_planning_toewijzing_administratie_id', 'planning_toewijzing', ['administratie_id'], unique=False, schema='boekhouding')
    op.create_index('ix_planning_toewijzing_datum', 'planning_toewijzing', ['administratie_id', 'datum'], unique=False, schema='boekhouding')
    op.create_index('ix_planning_toewijzing_gebruiker', 'planning_toewijzing', ['administratie_id', 'gebruiker_id', 'datum'], unique=False, schema='boekhouding')

    # RLS + grants (patroon 0056): administratie-gebonden; DELETE mag — een planningskaartje
    # weghalen/verplaatsen is werkplanning, geen financiële registratie. Elke mutatie loopt
    # via de service mét audit_event.
    op.execute("ALTER TABLE boekhouding.planning_toewijzing ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.planning_toewijzing FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY planning_toewijzing_scope ON boekhouding.planning_toewijzing
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON boekhouding.planning_toewijzing TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index('ix_planning_toewijzing_gebruiker', table_name='planning_toewijzing', schema='boekhouding')
    op.drop_index('ix_planning_toewijzing_datum', table_name='planning_toewijzing', schema='boekhouding')
    op.drop_index('ix_planning_toewijzing_administratie_id', table_name='planning_toewijzing', schema='boekhouding')
    op.drop_table('planning_toewijzing', schema='boekhouding')
