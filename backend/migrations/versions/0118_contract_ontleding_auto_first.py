"""Contract-ontleding: kopvelden + AUTO-FIRST (blok D6, besluit Peter 06-09 — herziet de 22-08-regel
"bevestigen per regel"). Wat de ontleding leest wordt DIRECT ingevuld in project_specificatie en
project_staffel mét herkomst "uit contract" (corrigeerbaar → herkomst 'mens', audit oud→nieuw).

- `boekhouding.project_specificatie.veld_herkomst` (JSONB, NULL): per spec-veld de herkomst
  {"contract_m2": "contract", "soort_werk": "mens", …}. Ontbrekende sleutel/NULL = onbekend (rij van vóór
  0118 — wordt in de UI als "uit contract" getoond wanneer het veld gevuld is; geen backfill, beslispunt).
  Een veld met herkomst 'mens' wordt door een her-ontleding NOOIT overschreven.
- `boekhouding.project_staffel.herkomst` (Text, NULL: 'contract' | 'mens') +
  `herkomst_document_id` (UUID, NULL, FK project_document): welk contract/offerte de regel las — de
  her-ontleding van datzelfde document vervangt alleen zíjn eigen contract-regels; mens-regels blijven.
- `boekhouding.project_ontleding_regel`: CHECK-constraints verruimd — soort + 'soort_werk' (nieuw kopveld),
  status + 'overgenomen' (direct ingevuld), 'niet_aangetroffen' (expliciete sentinel-uitkomst van de AI),
  'ongeldig' (gelezen maar niet deterministisch te plaatsen, bv. onbekende eenheid — zichtbaar, niet
  ingevuld), 'mens_behouden' (gelezen, maar het spec-veld droeg al een mens-waarde — die wint, zichtbaar).
  De oude statussen voorstel/bevestigd/afgewezen blijven geldig voor bestaande rijen.

Schema-only DDL, geen backfill. RLS/GRANTs ongewijzigd (kolommen op bestaande tabellen).

Revision ID: 0118
Revises: 0117
Create Date: 2026-09-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0118"
down_revision: str | None = "0117"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

SCHEMA = "boekhouding"

_SOORTEN_OUD = "'contract_m2', 'looptijd', 'huurtijd', 'doorlopende_huur', 'opdrachtgever', 'werknummer', 'staffel', 'boete'"
_SOORTEN_NIEUW = _SOORTEN_OUD + ", 'soort_werk'"
_STATUS_OUD = "'voorstel', 'bevestigd', 'afgewezen'"
_STATUS_NIEUW = _STATUS_OUD + ", 'overgenomen', 'niet_aangetroffen', 'ongeldig', 'mens_behouden'"


def upgrade() -> None:
    op.add_column(
        "project_specificatie",
        sa.Column("veld_herkomst", JSONB(none_as_null=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column("project_staffel", sa.Column("herkomst", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column(
        "project_staffel",
        sa.Column("herkomst_document_id", UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_project_staffel_herkomst_document",
        "project_staffel",
        "project_document",
        ["herkomst_document_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.drop_constraint("ck_project_ontleding_regel_soort", "project_ontleding_regel", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "ck_project_ontleding_regel_soort", "project_ontleding_regel", f"soort IN ({_SOORTEN_NIEUW})", schema=SCHEMA
    )
    op.drop_constraint("ck_project_ontleding_regel_status", "project_ontleding_regel", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "ck_project_ontleding_regel_status", "project_ontleding_regel", f"status IN ({_STATUS_NIEUW})", schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_constraint("ck_project_ontleding_regel_status", "project_ontleding_regel", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "ck_project_ontleding_regel_status", "project_ontleding_regel", f"status IN ({_STATUS_OUD})", schema=SCHEMA
    )
    op.drop_constraint("ck_project_ontleding_regel_soort", "project_ontleding_regel", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "ck_project_ontleding_regel_soort", "project_ontleding_regel", f"soort IN ({_SOORTEN_OUD})", schema=SCHEMA
    )
    op.drop_constraint("fk_project_staffel_herkomst_document", "project_staffel", schema=SCHEMA, type_="foreignkey")
    op.drop_column("project_staffel", "herkomst_document_id", schema=SCHEMA)
    op.drop_column("project_staffel", "herkomst", schema=SCHEMA)
    op.drop_column("project_specificatie", "veld_herkomst", schema=SCHEMA)
