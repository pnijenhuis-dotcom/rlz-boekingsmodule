"""Voorraad-uitstroom uit RLZ-verkoopfacturen (opdracht 29-08 blok A — STAP-0 groen, api-verkenning
"Voorraad-uitstroom STAP-0"): de feitenlaag `mi.voorraad_regel` krijgt een tweede uitstroom-bron náást
de in de app geboekte verkoopdocumenten — de regels van de EIGEN RLZ-verkoopfacturen van een
voorraad-administratie (Universal Verkoop factureert in RLZ, niet via de app).

Zo'n regel heeft geen lokaal `boekhouding.document`; daarom:
1. `document_id` wordt NULL-baar;
2. nieuw `rlz_document_id` (SalesInvoice-GUID) + `rlz_referentie` (RLZ-factuurnummer, leesbaar in de
   drill-down);
3. CHECK: precies één herkomst (document_id XOR rlz_document_id);
4. partiële unieke index op (rlz_document_id, richting, regel_volgnummer) — idempotente her-lezing per
   RLZ-factuur (vervangen per factuur, zelfde patroon als per document).
Geen RLZ-writes, geen data-backfill (de eerste sync vult zichzelf).

Revision ID: 0087
Revises: 0086
Create Date: 2026-08-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

SCHEMA = "mi"


def upgrade() -> None:
    op.alter_column("voorraad_regel", "document_id", existing_type=UUID(as_uuid=True), nullable=True, schema=SCHEMA)
    op.add_column("voorraad_regel", sa.Column("rlz_document_id", UUID(as_uuid=True), nullable=True), schema=SCHEMA)
    op.add_column("voorraad_regel", sa.Column("rlz_referentie", sa.Text(), nullable=True), schema=SCHEMA)
    op.create_check_constraint(
        "ck_voorraad_regel_herkomst",
        "voorraad_regel",
        "(document_id IS NOT NULL) <> (rlz_document_id IS NOT NULL)",
        schema=SCHEMA,
    )
    op.execute(
        f"CREATE UNIQUE INDEX uq_voorraad_regel_rlz_regel ON {SCHEMA}.voorraad_regel "
        "(rlz_document_id, richting, regel_volgnummer) WHERE rlz_document_id IS NOT NULL"
    )
    op.create_index(
        "ix_voorraad_regel_rlz_document_id", "voorraad_regel", ["rlz_document_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("ix_voorraad_regel_rlz_document_id", table_name="voorraad_regel", schema=SCHEMA)
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.uq_voorraad_regel_rlz_regel")
    op.drop_constraint("ck_voorraad_regel_herkomst", "voorraad_regel", schema=SCHEMA, type_="check")
    op.execute(f"DELETE FROM {SCHEMA}.voorraad_regel WHERE document_id IS NULL")
    op.drop_column("voorraad_regel", "rlz_referentie", schema=SCHEMA)
    op.drop_column("voorraad_regel", "rlz_document_id", schema=SCHEMA)
    op.alter_column("voorraad_regel", "document_id", existing_type=UUID(as_uuid=True), nullable=False, schema=SCHEMA)
