"""Projectenmodule kantoor (mockup projecten-invoer.html, akkoord Peter 2026-08-22).

Drie tabellen:
1. boekhouding.project_regel_cache — leescache van RLZ-documentregels mét projectreferentie
   (PurchaseInvoices + SalesInvoices → /Lines?$expand=Account,Project), de rekenbron voor
   "resultaat per project" (analytische laag, nooit geboekt in RLZ). Grants S/I/U/D (cache).
2. boekhouding.project_ontleding_regel — contract-/offerte-ontleedvoorstel per regel (AI
   stelt voor, mens bevestigt/wijst af; bevestigen = deterministisch doorschrijven naar
   project_specificatie/project_staffel). Grants S/I/U/D (her-ontleding vervangt alleen de
   onbesliste voorstel-regels).
3. boekhouding.leverancier_werknummer — leverancier-werknummer ↔ project-mapping
   (praktijkles verkenning/12; eerste keer bevestigen, daarna automatisch). Grants S/I/U/D
   (koppel-/configuratietabel, patroon 0056).

Revision ID: 0062
Revises: 0061
Create Date: 2026-08-22

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '0062'
down_revision: str | None = '0061'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def _rls(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )


def upgrade() -> None:
    op.create_table('project_regel_cache',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('administratie_id', sa.UUID(), nullable=False),
    sa.Column('rlz_document_id', sa.UUID(), nullable=False),
    sa.Column('soort', sa.Text(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('ledger_id', sa.UUID(), nullable=True),
    sa.Column('netto_bedrag', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('btw_bedrag', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('datum', sa.Date(), nullable=True),
    sa.Column('referentie', sa.Text(), nullable=True),
    sa.Column('omschrijving', sa.Text(), nullable=True),
    sa.Column('laatst_gesynchroniseerd', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('verdwenen_uit_bron_op', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("soort IN ('inkoop', 'verkoop')", name='ck_project_regel_cache_soort'),
    sa.ForeignKeyConstraint(['administratie_id'], ['platform.administratie.id'], ),
    sa.PrimaryKeyConstraint('id', 'administratie_id'),
    schema='boekhouding'
    )
    op.create_index('ix_project_regel_cache_administratie_id', 'project_regel_cache', ['administratie_id'], unique=False, schema='boekhouding')
    op.create_index('ix_project_regel_cache_project', 'project_regel_cache', ['administratie_id', 'project_id'], unique=False, schema='boekhouding')
    op.create_index('ix_project_regel_cache_document', 'project_regel_cache', ['administratie_id', 'rlz_document_id'], unique=False, schema='boekhouding')

    op.create_table('project_ontleding_regel',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('administratie_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('project_document_id', sa.UUID(), nullable=False),
    sa.Column('soort', sa.Text(), nullable=False),
    sa.Column('omschrijving', sa.Text(), nullable=False),
    sa.Column('citaat', sa.Text(), nullable=True),
    sa.Column('waarde', JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('zekerheid', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('beslist_door', sa.UUID(), nullable=True),
    sa.Column('beslist_op', sa.DateTime(timezone=True), nullable=True),
    sa.Column('aangemaakt_op', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint(
        "soort IN ('contract_m2', 'looptijd', 'huurtijd', 'doorlopende_huur', 'opdrachtgever', "
        "'werknummer', 'staffel', 'boete')",
        name='ck_project_ontleding_regel_soort',
    ),
    sa.CheckConstraint("status IN ('voorstel', 'bevestigd', 'afgewezen')", name='ck_project_ontleding_regel_status'),
    sa.ForeignKeyConstraint(['administratie_id'], ['platform.administratie.id'], ),
    sa.ForeignKeyConstraint(['beslist_door'], ['platform.gebruiker.id'], ),
    sa.ForeignKeyConstraint(['project_document_id'], ['boekhouding.project_document.id'], ),
    sa.ForeignKeyConstraint(['project_id', 'administratie_id'], ['boekhouding.project_cache.id', 'boekhouding.project_cache.administratie_id'], name='fk_project_ontleding_regel_project_cache'),
    sa.PrimaryKeyConstraint('id'),
    schema='boekhouding'
    )
    op.create_index('ix_project_ontleding_regel_administratie_id', 'project_ontleding_regel', ['administratie_id'], unique=False, schema='boekhouding')
    op.create_index('ix_project_ontleding_regel_project', 'project_ontleding_regel', ['administratie_id', 'project_id'], unique=False, schema='boekhouding')

    op.create_table('leverancier_werknummer',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('administratie_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('vendor_id', sa.UUID(), nullable=False),
    sa.Column('werknummer', sa.Text(), nullable=False),
    sa.Column('bron', sa.Text(), nullable=False),
    sa.Column('bevestigd', sa.Boolean(), nullable=False),
    sa.Column('aangemaakt_door', sa.UUID(), nullable=False),
    sa.Column('aangemaakt_op', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('bevestigd_door', sa.UUID(), nullable=True),
    sa.Column('bevestigd_op', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['administratie_id'], ['platform.administratie.id'], ),
    sa.ForeignKeyConstraint(['aangemaakt_door'], ['platform.gebruiker.id'], ),
    sa.ForeignKeyConstraint(['bevestigd_door'], ['platform.gebruiker.id'], ),
    sa.ForeignKeyConstraint(['project_id', 'administratie_id'], ['boekhouding.project_cache.id', 'boekhouding.project_cache.administratie_id'], name='fk_leverancier_werknummer_project_cache'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('administratie_id', 'vendor_id', 'werknummer', name='uq_leverancier_werknummer'),
    schema='boekhouding'
    )
    op.create_index('ix_leverancier_werknummer_administratie_id', 'leverancier_werknummer', ['administratie_id'], unique=False, schema='boekhouding')
    op.create_index('ix_leverancier_werknummer_project', 'leverancier_werknummer', ['administratie_id', 'project_id'], unique=False, schema='boekhouding')

    for tabel in ("project_regel_cache", "project_ontleding_regel", "leverancier_werknummer"):
        _rls(tabel)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON boekhouding.{tabel} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index('ix_leverancier_werknummer_project', table_name='leverancier_werknummer', schema='boekhouding')
    op.drop_index('ix_leverancier_werknummer_administratie_id', table_name='leverancier_werknummer', schema='boekhouding')
    op.drop_table('leverancier_werknummer', schema='boekhouding')
    op.drop_index('ix_project_ontleding_regel_project', table_name='project_ontleding_regel', schema='boekhouding')
    op.drop_index('ix_project_ontleding_regel_administratie_id', table_name='project_ontleding_regel', schema='boekhouding')
    op.drop_table('project_ontleding_regel', schema='boekhouding')
    op.drop_index('ix_project_regel_cache_document', table_name='project_regel_cache', schema='boekhouding')
    op.drop_index('ix_project_regel_cache_project', table_name='project_regel_cache', schema='boekhouding')
    op.drop_index('ix_project_regel_cache_administratie_id', table_name='project_regel_cache', schema='boekhouding')
    op.drop_table('project_regel_cache', schema='boekhouding')
