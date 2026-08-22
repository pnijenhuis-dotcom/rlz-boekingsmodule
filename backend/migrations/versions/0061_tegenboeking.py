"""Tegenboek-pad (mockup tegenboek-mockup.html, akkoord Peter 2026-08-22; STAP-0
"Tegenboek-pad STAP 0" in verkenning/api-verkenning.md; besluit: géén suppletie-signaal).

1. boekvoorstel.boek_cyclus (default 0): elke "tegenboeken én opnieuw boeken" verhoogt de
   cyclus — de herboeking krijgt zo een eigen deterministisch RLZ-GUID (een her-PUT op het
   GUID van het origineel zou de DocumentLineList van het origineel vervangen).
2. boekhouding.tegenboeking: één rij per (document, boek_cyclus) — soort volledig/vervang,
   verplichte reden (>= 5 tekens), het RLZ-GUID + boekstuknummer van de tegenboeking en de
   betaalstatus van het origineel op dat moment (mockup-waarschuwing open creditpost).
   RLS op administratie (patroon 0056); grants SELECT + INSERT — append-only: terugdraaien
   van een tegenboeking is een RLZ-UI-handeling (actie 19), nooit een app-mutatie.

Revision ID: 0061
Revises: 0060
Create Date: 2026-08-22

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0061'
down_revision: str | None = '0060'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.add_column(
        'boekvoorstel',
        sa.Column('boek_cyclus', sa.Integer(), server_default=sa.text('0'), nullable=False),
        schema='boekhouding',
    )
    op.create_table('tegenboeking',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('boek_cyclus', sa.Integer(), nullable=False),
    sa.Column('administratie_id', sa.UUID(), nullable=False),
    sa.Column('soort', sa.Text(), nullable=False),
    sa.Column('reden', sa.Text(), nullable=False),
    sa.Column('rlz_tegenboeking_id', sa.UUID(), nullable=False),
    sa.Column('rlz_boekstuknummer', sa.Text(), nullable=True),
    sa.Column('origineel_betaald_bedrag', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('aangemaakt_door', sa.UUID(), nullable=False),
    sa.Column('aangemaakt_op', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("soort IN ('volledig', 'vervang')", name='ck_tegenboeking_soort'),
    sa.CheckConstraint('length(btrim(reden)) >= 5', name='ck_tegenboeking_reden'),
    sa.ForeignKeyConstraint(['administratie_id'], ['platform.administratie.id'], ),
    sa.ForeignKeyConstraint(['aangemaakt_door'], ['platform.gebruiker.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['boekhouding.document.id'], ),
    sa.PrimaryKeyConstraint('document_id', 'boek_cyclus'),
    schema='boekhouding'
    )
    op.create_index('ix_tegenboeking_administratie_id', 'tegenboeking', ['administratie_id'], unique=False, schema='boekhouding')

    # RLS + grants (patroon 0056): administratie-gebonden, append-only (geen UPDATE/DELETE).
    op.execute("ALTER TABLE boekhouding.tegenboeking ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.tegenboeking FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tegenboeking_scope ON boekhouding.tegenboeking
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT ON boekhouding.tegenboeking TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index('ix_tegenboeking_administratie_id', table_name='tegenboeking', schema='boekhouding')
    op.drop_table('tegenboeking', schema='boekhouding')
    op.drop_column('boekvoorstel', 'boek_cyclus', schema='boekhouding')
