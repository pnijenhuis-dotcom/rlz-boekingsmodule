"""Blok 3 18-09 (Peter 18-09): projectstatus lopend/afgesloten + projectnummer uniek.

`boekhouding.project_cache` krijgt een MODULE-status naast RLZ's `IsActive` (`is_actief` blijft de spiegel van de bron):
- `status` text NOT NULL default 'lopend' (CHECK lopend|afgesloten) — afsluiten zet RLZ `IsActive=false` (klant-loze PUT +
  terugleesverificatie) resp. Odoo `active=False` via de adapter, en pas dán de status; heropenen andersom.
- `afgesloten_op` timestamptz, `afgesloten_door` uuid (FK platform.gebruiker), `afsluit_reden` text — het audit-spoor op de rij
  (het volledige oud→nieuw-spoor staat in platform.audit_event).
- index (administratie_id, status) voor de lijst-/keuzelijstfilters.
Projectnummer-uniciteit is een codepoort (cijfer-prefix over cache + RLZ-lookup — RLZ kent géén codeveld, STAP-0 16-09) en
geen DB-constraint: de naam is vrije tekst en RLZ blijft de bron. Schema-only, pure DDL; RLS ongewijzigd (bestaande tabel).

Revision ID: 0160
Revises: 0159
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0160"
down_revision: str | None = "0159"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_cache",
        sa.Column("status", sa.Text(), nullable=False, server_default="lopend"),
        schema="boekhouding",
    )
    op.add_column("project_cache", sa.Column("afgesloten_op", sa.DateTime(timezone=True), nullable=True), schema="boekhouding")
    op.add_column(
        "project_cache",
        sa.Column(
            "afgesloten_door",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("platform.gebruiker.id", name="fk_project_cache_afgesloten_door"),
            nullable=True,
        ),
        schema="boekhouding",
    )
    op.add_column("project_cache", sa.Column("afsluit_reden", sa.Text(), nullable=True), schema="boekhouding")
    op.create_check_constraint(
        "ck_project_cache_status", "project_cache", "status IN ('lopend', 'afgesloten')", schema="boekhouding"
    )
    op.create_index(
        "ix_project_cache_administratie_status", "project_cache", ["administratie_id", "status"], schema="boekhouding"
    )


def downgrade() -> None:
    op.drop_index("ix_project_cache_administratie_status", table_name="project_cache", schema="boekhouding")
    op.drop_constraint("ck_project_cache_status", "project_cache", schema="boekhouding", type_="check")
    op.drop_column("project_cache", "afsluit_reden", schema="boekhouding")
    op.drop_column("project_cache", "afgesloten_door", schema="boekhouding")
    op.drop_column("project_cache", "afgesloten_op", schema="boekhouding")
    op.drop_column("project_cache", "status", schema="boekhouding")
