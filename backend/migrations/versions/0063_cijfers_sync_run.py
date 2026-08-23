"""Projectcijfers-sync als achtergrondrun (fix 504-crash 2026-08-23).

De sync-knop tegen een echte datamassa (Universal, 68 projecten) liep in één synchrone
HTTP-request tegen Cloud Runs request-timeout (300 s → 504, géén OOM — logbevinding
2026-08-23 in BESLISSINGEN). De knop start voortaan een achtergrondrun; deze tabel is de
wachtrij én het statusvenster dat de UI pollt (bezig/klaar/fout mét zichtbare foutreden).
Grants S/I/U (status-transities), geen DELETE — runs blijven als spoor staan.

Revision ID: 0063
Revises: 0062
Create Date: 2026-08-23

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0063'
down_revision: str | None = '0062'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table('project_cijfers_sync_run',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('administratie_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('aangevraagd_door', sa.UUID(), nullable=True),
    sa.Column('aangevraagd_op', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('gestart_op', sa.DateTime(timezone=True), nullable=True),
    sa.Column('laatst_actief_op', sa.DateTime(timezone=True), nullable=True),
    sa.Column('beeindigd_op', sa.DateTime(timezone=True), nullable=True),
    sa.Column('documenten', sa.Integer(), nullable=True),
    sa.Column('regels', sa.Integer(), nullable=True),
    sa.Column('verdwenen', sa.Integer(), nullable=True),
    sa.Column('leesfouten', sa.Integer(), nullable=True),
    sa.Column('fout_reden', sa.Text(), nullable=True),
    sa.CheckConstraint(
        "status IN ('wachtrij', 'bezig', 'klaar', 'fout')", name='ck_project_cijfers_sync_run_status'
    ),
    sa.ForeignKeyConstraint(['administratie_id'], ['platform.administratie.id'], ),
    sa.ForeignKeyConstraint(['aangevraagd_door'], ['platform.gebruiker.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='boekhouding'
    )
    op.create_index('ix_project_cijfers_sync_run_administratie_id', 'project_cijfers_sync_run', ['administratie_id'], unique=False, schema='boekhouding')
    op.create_index('ix_project_cijfers_sync_run_status', 'project_cijfers_sync_run', ['administratie_id', 'status'], unique=False, schema='boekhouding')

    op.execute("ALTER TABLE boekhouding.project_cijfers_sync_run ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.project_cijfers_sync_run FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY project_cijfers_sync_run_scope ON boekhouding.project_cijfers_sync_run
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.project_cijfers_sync_run TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index('ix_project_cijfers_sync_run_status', table_name='project_cijfers_sync_run', schema='boekhouding')
    op.drop_index('ix_project_cijfers_sync_run_administratie_id', table_name='project_cijfers_sync_run', schema='boekhouding')
    op.drop_table('project_cijfers_sync_run', schema='boekhouding')
