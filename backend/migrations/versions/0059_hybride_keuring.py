"""Hybride keuring + afwijkings-logging (nazorg veld-app-kliktest, besluiten Peter 2026-08-22).

1. Correctievoorstel per dagregel bij het AFKEUREN van een week (hybride keuring — keuren
   blijft op weekniveau, het weekniveau-besluit van 21-08 blijft verder staan): drie
   voorstel-kolommen op boekhouding.weekstaat_dag (voorstel_uren / voorstel_m2 /
   voorstel_opmerking), gezet door de keurder bij de afkeuring. De keurder wijzigt nooit
   zelf de uren/m² van de ZZP'er — die ziet de voorstellen in zijn corrigeer-scherm en
   dient zelf opnieuw in.
2. boekhouding.weekstaat_correctie (afwijkings-logging): één rij per afkeuring mét
   correctievoorstel — ingediende vs. voorgestelde uren + delta, ná de definitieve
   goedkeuring aangevuld met het goedgekeurde totaal. Optelbaar per veldwerker, zichtbaar
   voor het kantoor (veldwerkers-paneel), nooit voor de veldwerker zelf. RLS op
   administratie (patroon 0033/0056); grants SELECT, INSERT, UPDATE — geen DELETE, de
   registratie verdwijnt nooit ("niets verdwijnt stil").

Revision ID: 0059
Revises: 0058
Create Date: 2026-08-22

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0059'
down_revision: str | None = '0058'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    # --- 1. correctievoorstel-velden op de dagregel -------------------------------------------
    op.add_column(
        'weekstaat_dag',
        sa.Column('voorstel_uren', sa.Numeric(precision=5, scale=2), nullable=True),
        schema='boekhouding',
    )
    op.add_column(
        'weekstaat_dag',
        sa.Column('voorstel_m2', sa.Numeric(precision=8, scale=2), nullable=True),
        schema='boekhouding',
    )
    op.add_column(
        'weekstaat_dag',
        sa.Column('voorstel_opmerking', sa.Text(), nullable=True),
        schema='boekhouding',
    )
    op.create_check_constraint(
        'ck_weekstaat_dag_voorstel_uren',
        'weekstaat_dag',
        'voorstel_uren IS NULL OR (voorstel_uren >= 0 AND voorstel_uren <= 24)',
        schema='boekhouding',
    )
    op.create_check_constraint(
        'ck_weekstaat_dag_voorstel_m2',
        'weekstaat_dag',
        'voorstel_m2 IS NULL OR voorstel_m2 >= 0',
        schema='boekhouding',
    )

    # --- 2. afwijkings-logging ------------------------------------------------------------------
    op.create_table('weekstaat_correctie',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('administratie_id', sa.UUID(), nullable=False),
    sa.Column('weekstaat_id', sa.UUID(), nullable=False),
    sa.Column('zzper_gebruiker_id', sa.UUID(), nullable=False),
    sa.Column('afgekeurd_door', sa.UUID(), nullable=False),
    sa.Column('afgekeurd_op', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ingediend_uren', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('voorgesteld_uren', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('delta_uren', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('goedgekeurd_uren', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('goedgekeurd_op', sa.DateTime(timezone=True), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint('(goedgekeurd_uren IS NULL) = (goedgekeurd_op IS NULL)', name='ck_weekstaat_correctie_goedgekeurd_samen'),
    sa.CheckConstraint('ingediend_uren >= 0', name='ck_weekstaat_correctie_ingediend'),
    sa.CheckConstraint('voorgesteld_uren >= 0', name='ck_weekstaat_correctie_voorgesteld'),
    sa.ForeignKeyConstraint(['administratie_id'], ['platform.administratie.id'], ),
    sa.ForeignKeyConstraint(['afgekeurd_door'], ['platform.gebruiker.id'], ),
    sa.ForeignKeyConstraint(['weekstaat_id'], ['boekhouding.weekstaat.id'], ),
    sa.ForeignKeyConstraint(['zzper_gebruiker_id'], ['platform.gebruiker.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='boekhouding'
    )
    op.create_index('ix_weekstaat_correctie_administratie_id', 'weekstaat_correctie', ['administratie_id'], unique=False, schema='boekhouding')
    op.create_index('ix_weekstaat_correctie_weekstaat_id', 'weekstaat_correctie', ['weekstaat_id'], unique=False, schema='boekhouding')
    op.create_index('ix_weekstaat_correctie_zzper', 'weekstaat_correctie', ['administratie_id', 'zzper_gebruiker_id'], unique=False, schema='boekhouding')

    # RLS + grants (patroon 0056): administratie-gebonden; UPDATE alleen voor het aanvullen van
    # het goedgekeurd-totaal, geen DELETE — de afwijkings-registratie verdwijnt nooit.
    op.execute("ALTER TABLE boekhouding.weekstaat_correctie ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.weekstaat_correctie FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY weekstaat_correctie_scope ON boekhouding.weekstaat_correctie
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.weekstaat_correctie TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index('ix_weekstaat_correctie_zzper', table_name='weekstaat_correctie', schema='boekhouding')
    op.drop_index('ix_weekstaat_correctie_weekstaat_id', table_name='weekstaat_correctie', schema='boekhouding')
    op.drop_index('ix_weekstaat_correctie_administratie_id', table_name='weekstaat_correctie', schema='boekhouding')
    op.drop_table('weekstaat_correctie', schema='boekhouding')
    op.drop_constraint('ck_weekstaat_dag_voorstel_m2', 'weekstaat_dag', schema='boekhouding')
    op.drop_constraint('ck_weekstaat_dag_voorstel_uren', 'weekstaat_dag', schema='boekhouding')
    op.drop_column('weekstaat_dag', 'voorstel_opmerking', schema='boekhouding')
    op.drop_column('weekstaat_dag', 'voorstel_m2', schema='boekhouding')
    op.drop_column('weekstaat_dag', 'voorstel_uren', schema='boekhouding')
