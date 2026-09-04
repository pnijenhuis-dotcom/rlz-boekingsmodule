"""Regel-niveau GB-voorstel (blok D) + btw-default per administratie (blok E) — medewerker-wensen 04-09,
mockup `projectverdeling-en-regelvoorstellen.html` blok 2 + 3, ontwerpnotities ⑦ en ⑧ (akkoord Peter 04-09).

Blok D — Derks-casus: per boekvoorstel-regel een GB-voorstel uit de gelezen omschrijving. Het deterministische
regel-geheugen leest de BESTAANDE `boekhouding.boeking_observatie` (regel_sleutel = genormaliseerde
omschrijving) en heeft geen nieuwe tabel nodig. De AI-classificatie (alleen voor regels zónder geheugen-treffer,
achter de AI-gates + kostenmeter) moet daarentegen PERSISTENT per document zijn zodat herladen van het
controlescherm nooit een tweede call doet:
- `boekhouding.regel_gb_classificatie`: één rij per (document, regel-volgnummer) — de gekozen GB (NULL = het
  model koos "geen"), het aantal kandidaten (de historisch door deze leverancier gebruikte GB's), de
  regel_sleutel waarop de uitkomst hoort (her-extractie mét andere omschrijving = uitkomst ongeldig, opnieuw
  classificeren) en het model. Bewust een eigen tabel en géén kolom op `boekvoorstel_regel`: de prefill
  werkt juist vóór er een opgeslagen boekvoorstel bestaat, en het veldvoorstel-dict in de tijdlijn is
  append-only extractie-uitvoer die de bestaande extractie-flow niet mag muteren. RLS per administratie
  (patroon 0095/0107); GRANT zonder DELETE — een uitkomst wordt overschreven (upsert), nooit stil gewist.

Blok E — `platform.administratie.standaard_taxrate_id` (uuid, NULL): het standaard-btw-voorstel van de
administratie (steigerbouw: verlegd hoog). Vult in de prefill ALLEEN regels waar factuur én
leverancier-geheugen niets opleveren (chip "standaard administratie"). NULL = UIT — bestaande administraties
ongemoeid tot Peter activeert (⑧). Bewust geen FK naar `taxrate_cache`: de instelling moet een
sync-verdwijning overleven (zelfde overweging als leverancier_voorkeur); de service valideert tegen de cache.
Schema-only, geen backfill.

Revision ID: 0108
Revises: 0107
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0108"
down_revision: str | None = "0107"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    # Blok E — btw-default per administratie (NULL = uit).
    op.add_column(
        "administratie",
        sa.Column("standaard_taxrate_id", UUID(as_uuid=True), nullable=True),
        schema="platform",
    )

    # Blok D — persistente AI-classificatie-uitkomst per (document, regel).
    op.create_table(
        "regel_gb_classificatie",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("regel_volgnummer", sa.Integer(), nullable=False),
        sa.Column("regel_sleutel", sa.Text(), nullable=True),
        sa.Column("ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("kandidaten_n", sa.Integer(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", "regel_volgnummer", name="uq_regel_gb_classificatie_document_regel"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_regel_gb_classificatie_administratie_id",
        "regel_gb_classificatie",
        ["administratie_id"],
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.regel_gb_classificatie ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.regel_gb_classificatie FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY regel_gb_classificatie_scope ON boekhouding.regel_gb_classificatie
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.regel_gb_classificatie TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS regel_gb_classificatie_scope ON boekhouding.regel_gb_classificatie")
    op.drop_index(
        "ix_regel_gb_classificatie_administratie_id", table_name="regel_gb_classificatie", schema="boekhouding"
    )
    op.drop_table("regel_gb_classificatie", schema="boekhouding")
    op.drop_column("administratie", "standaard_taxrate_id", schema="platform")
