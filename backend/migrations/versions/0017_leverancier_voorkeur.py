"""Leverancier-voorkeur: regels samenvoegen per (administratie, crediteur).

Fix 3 (2026-07-10, Peters controle van een echte factuur met veel regels): het controlescherm
toont boekingsregels voortaan standaard als ÉÉN samengevoegde regel (mockup: "Regels samenvoegen
tot één boekingsregel — standaard aan · keuze wordt per leverancier onthouden"), met een vinkje
"splitsen per regel" voor de losse geëxtraheerde regels. Deze tabel onthoudt die keuze per
crediteur per administratie. Administraties met projectplicht blijven hard per-regel (project
per regel) — daarvoor wordt hier nooit een samenvoegen=true-rij gezet (afgedwongen in
app/documenten/boekvoorstel.py, niet met een DB-constraint: de toggle project_verplicht kan
later aan gaan en dan is een oude voorkeur-rij geen constraint-schending maar gewoon genegeerd).

Bewust géén FK naar vendor_cache: de voorkeur mag een sync-verdwenen crediteur overleven
(verdwenen_uit_bron_op-patroon — komt hij terug, geldt de voorkeur weer). RLS conform het
bestaande cache-patroon (migratie 0005).

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "leverancier_voorkeur",
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("vendor_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("regels_samenvoegen", sa.Boolean(), nullable=False),
        sa.Column(
            "gewijzigd_op",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.leverancier_voorkeur ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.leverancier_voorkeur FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY leverancier_voorkeur_scope ON boekhouding.leverancier_voorkeur
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.leverancier_voorkeur TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.leverancier_voorkeur FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS leverancier_voorkeur_scope ON boekhouding.leverancier_voorkeur")
    op.drop_table("leverancier_voorkeur", schema="boekhouding")
