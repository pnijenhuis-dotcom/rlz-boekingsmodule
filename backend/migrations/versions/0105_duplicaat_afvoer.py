"""Duplicaat-auto-afvoer (medewerker-wens, besluit Peter 04-09 — blok A van de run "Medewerker-wensen
04-09"; kernprincipe 7 "minimale mens, maximale autonomie": signalering zonder handeling is niet af).

Bij een HARDE duplicaat-match (zelfde crediteur op btw-nummer + zelfde referentie + zelfde totaalbedrag,
origineel geboekt in RLZ/Odoo óf een ouder app-document in de werkvoorraad) voert het systeem het document
automatisch af naar Afgewezen met reden "Duplicaat van …" — nooit verwijderen, nooit stil; terughalen via de
bestaande heropenen-route.

- `platform.administratie.duplicaat_autoafvoer_ingeschakeld` (bool, default UIT, Beheerder-only): opt-in per
  administratie voor het automatische pad. De één-klik-variant "Afvoeren als duplicaat" werkt altijd.
- `boekhouding.afwijzing` krijgt de PERSISTENTE kruisverwijzing naar het origineel — zichtbaar op het afgevoerde
  document ("Duplicaat van … → open origineel") én op het origineel ("N duplicaten afgevoerd"):
  * `duplicaat_van_document_id` (uuid, NULL, FK document) — origineel als app-document (werkvoorraad of in de
    app geboekt);
  * `duplicaat_van_rlz_document_id` (uuid, NULL) — origineel als RLZ-/Odoo-document zonder app-document
    (treffer uit het gecachete duplicaatsignaal);
  * `duplicaat_van_referentie` (text, NULL) — leesbare referentie/boekstuk van het origineel;
  * `automatisch` (bool, NOT NULL, default false) — true = door het systeem afgevoerd (systeem-actor), false =
    door een mens (één-klik of gewoon afwijzen).
Een gewone afwijzing draagt op alle duplicaat-kolommen NULL. Schema-only, geen backfill.

Revision ID: 0105
Revises: 0104
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0105"
down_revision: str | None = "0104"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("duplicaat_autoafvoer_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )
    op.add_column(
        "afwijzing",
        sa.Column(
            "duplicaat_van_document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("boekhouding.document.id", name="afwijzing_duplicaat_van_document_id_fkey"),
            nullable=True,
        ),
        schema="boekhouding",
    )
    op.add_column(
        "afwijzing",
        sa.Column("duplicaat_van_rlz_document_id", UUID(as_uuid=True), nullable=True),
        schema="boekhouding",
    )
    op.add_column(
        "afwijzing",
        sa.Column("duplicaat_van_referentie", sa.Text(), nullable=True),
        schema="boekhouding",
    )
    op.add_column(
        "afwijzing",
        sa.Column("automatisch", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="boekhouding",
    )
    # Leesroute "welke duplicaten zijn van dít origineel afgevoerd" (origineel-kant van de kruisverwijzing).
    op.create_index(
        "afwijzing_duplicaat_van_document_idx",
        "afwijzing",
        ["duplicaat_van_document_id"],
        schema="boekhouding",
        postgresql_where=sa.text("duplicaat_van_document_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("afwijzing_duplicaat_van_document_idx", table_name="afwijzing", schema="boekhouding")
    op.drop_column("afwijzing", "automatisch", schema="boekhouding")
    op.drop_column("afwijzing", "duplicaat_van_referentie", schema="boekhouding")
    op.drop_column("afwijzing", "duplicaat_van_rlz_document_id", schema="boekhouding")
    op.drop_column("afwijzing", "duplicaat_van_document_id", schema="boekhouding")
    op.drop_column("administratie", "duplicaat_autoafvoer_ingeschakeld", schema="platform")
