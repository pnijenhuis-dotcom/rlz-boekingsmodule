"""Projectverdeling pro rato omzet (medewerker-wens, besluit Peter 04-09 — blok C van de run "Medewerker-wensen
04-09"; mockup `projectverdeling-en-regelvoorstellen.html` blok 1 + ontwerpnotities ①–⑥; casussen Floorbeheer en
Derks-management: kosten zónder projectnummer in project-administraties zoals Universal).

Projectverdeling BINNEN de administratie — géén Kempen-doorbelasting. Een inkoopfactuur wordt over de actieve
projecten mét geboekte verkoopomzet in een gekozen kalendermaand verdeeld (grootste-rest-centen, som exact);
vaste regels (project + bedrag) gaan vóór, het restant gaat pro rato. Bij het boeken worden de omzetstanden
BEVROREN (①); een maandelijkse hercontrole rekent na met de actuele omzetstand van dezelfde periode en signaleert
boven de drempel (⑥) — herverdelen = de bestaande tegenboek-én-opnieuw-boeken-route, mens bevestigt.

- `boekhouding.leverancier_voorkeur.projectverdeling_pro_rato` (bool, default UIT, Beheerder-only): opt-in per
  leverancier — AAN = élk document van die crediteur krijgt automatisch een voorstel mét alleen de restant-regel (④).
- `platform.administratie.projectverdeling_drempel_pct` (numeric(5,2), default 5.00): hercontrole-drempel in %.
- `platform.administratie.inkoop_zonder_omzet_wachtweken` (integer, default 4): flankerend — het weekanalyse-signaal
  "inkoop zonder omzet" signaleert pas als de projectlooptijd ≥ N weken is (óf ná de eerste termijndatum).
- `boekhouding.projectverdeling`: één actuele rij per document (UNIQUE document_id, upsert) mét vaste regels,
  pro-rato-periode/-bedrag, de berekende verdeling, het omzet-snapshot, status voorstel/geboekt/vervallen, boek_cyclus
  en de hercontrole-uitkomst. RLS per administratie (patroon 0095); GRANT zonder DELETE — een verdeling vervalt
  (status), verdwijnt nooit stil.
Schema-only, geen backfill.

Revision ID: 0107
Revises: 0106
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0107"
down_revision: str | None = "0106"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.add_column(
        "leverancier_voorkeur",
        sa.Column("projectverdeling_pro_rato", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="boekhouding",
    )
    op.add_column(
        "administratie",
        sa.Column("projectverdeling_drempel_pct", sa.Numeric(5, 2), nullable=False, server_default="5.00"),
        schema="platform",
    )
    op.add_column(
        "administratie",
        sa.Column("inkoop_zonder_omzet_wachtweken", sa.Integer(), nullable=False, server_default="4"),
        schema="platform",
    )

    op.create_table(
        "projectverdeling",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("vaste_regels", JSONB(), nullable=False, server_default="[]"),
        sa.Column("pro_rato_periode", sa.Date(), nullable=True),
        sa.Column("pro_rato_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("verdeling", JSONB(), nullable=False, server_default="[]"),
        sa.Column("omzetstanden", JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.Text(), nullable=False, server_default="voorstel"),
        sa.Column("geboekt_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("boek_cyclus", sa.Integer(), nullable=True),
        sa.Column("hercontrole_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hercontrole_afwijking_pct", sa.Numeric(7, 2), nullable=True),
        sa.Column("hercontrole_verdeling", JSONB(), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('voorstel', 'geboekt', 'vervallen')", name="ck_projectverdeling_status"),
        sa.UniqueConstraint("document_id", name="uq_projectverdeling_document"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_projectverdeling_administratie_id", "projectverdeling", ["administratie_id"], schema="boekhouding"
    )
    # Hercontrole-leesroute: geboekte pro-rato-verdelingen mét een signaal (kantoorbrede lijst + rij-chip).
    op.create_index(
        "ix_projectverdeling_hercontrole_signaal",
        "projectverdeling",
        ["administratie_id", "hercontrole_afwijking_pct"],
        schema="boekhouding",
        postgresql_where=sa.text("status = 'geboekt' AND hercontrole_afwijking_pct IS NOT NULL"),
    )
    op.execute("ALTER TABLE boekhouding.projectverdeling ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.projectverdeling FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY projectverdeling_scope ON boekhouding.projectverdeling
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.projectverdeling TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS projectverdeling_scope ON boekhouding.projectverdeling")
    op.drop_index("ix_projectverdeling_hercontrole_signaal", table_name="projectverdeling", schema="boekhouding")
    op.drop_index("ix_projectverdeling_administratie_id", table_name="projectverdeling", schema="boekhouding")
    op.drop_table("projectverdeling", schema="boekhouding")
    op.drop_column("administratie", "inkoop_zonder_omzet_wachtweken", schema="platform")
    op.drop_column("administratie", "projectverdeling_drempel_pct", schema="platform")
    op.drop_column("leverancier_voorkeur", "projectverdeling_pro_rato", schema="boekhouding")
