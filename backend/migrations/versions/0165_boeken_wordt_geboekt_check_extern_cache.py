"""Boeken sneller (opdracht Peter 18-09, BESLISSINGEN "BOEKEN SNELLER — CHECKS-CACHE + ACHTERGROND-SCHRIJVER"):

1. PG-enumwaarde `wordt_geboekt` op `boekhouding.document_status` — tussenstatus tussen klaar_om_te_boeken en
   geboekt: de mens drukte op "Boeken in RLZ", het synchrone deel (poorten, harde checks, toggle, volumerem) was
   groen, de RLZ-write loopt op de achtergrond (worker). Uitgangen: → geboekt, → boeken_mislukt. Zelfde ADD VALUE-
   patroon als 0016/0028/0098/0122.
2. `boekhouding.check_extern_cache` — één rij per document: het EXTERNE deel van de harde checks (IBAN-seed uit
   RLZ-BankRelations, RLZ-/Odoo-duplicaatquery, kandidaten ± 60 d) als JSON, mét de vingerafdruk van de externe
   invoer (crediteur-cluster, referentie genormaliseerd, factuurdatum, totaal, factuur-IBAN, boek_cyclus) en het
   controlemoment. Geldig = zelfde vingerafdruk én ≤ 15 min; anders (of bij een boeken_mislukt-retry / autoboek-
   pad) altijd een verse externe run. RLS op administratie zoals de sync-tabellen (FORCE). Geen DELETE-grant: een
   nieuwe uitkomst overschrijft de rij (UPDATE).
3. `boekhouding.boek_wachtrij_claim` — de idempotency-key `boek-{document_id}-{boek_cyclus}` van de achtergrond-
   schrijver: INSERT = claim (twee verwerkers pakken nooit dezelfde boeking), `afgerond_op`/`uitkomst` ná de run;
   een claim zonder afronding > 10 min is een gestrande verwerker en mag door het herstel-vangnet opnieuw
   geclaimd worden (UPDATE). RLS op administratie (FORCE), geen DELETE-grant.
Schema-only, pure DDL; geen backfill.

Revision ID: 0165
Revises: 0164
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0165"
down_revision: str | None = "0164"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
CACHE = "check_extern_cache"
CLAIM = "boek_wachtrij_claim"


def _rls_op_administratie(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    # ADD VALUE mag sinds PG12 binnen een transactie zolang de waarde niet in dezelfde transactie gebruikt wordt.
    op.execute("ALTER TYPE boekhouding.document_status ADD VALUE IF NOT EXISTS 'wordt_geboekt' AFTER 'klaar_om_te_boeken'")

    op.create_table(
        CACHE,
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("boekhouding.document.id"),
            primary_key=True,
        ),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("vingerafdruk", sa.Text(), nullable=False),
        sa.Column("rapport", JSONB, nullable=False),
        sa.Column("gecontroleerd_op", sa.DateTime(timezone=True), nullable=False),
        sa.Column("backend", sa.Text(), nullable=False),
        schema="boekhouding",
    )
    op.create_index(f"ix_{CACHE}_administratie_id", CACHE, ["administratie_id"], schema="boekhouding")
    _rls_op_administratie(CACHE)

    op.create_table(
        CLAIM,
        sa.Column("sleutel", sa.Text(), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("boek_cyclus", sa.Integer(), nullable=False),
        sa.Column("geclaimd_op", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verwerker", sa.Text(), nullable=False),
        sa.Column("afgerond_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uitkomst", sa.Text(), nullable=True),
        schema="boekhouding",
    )
    op.create_index(f"ix_{CLAIM}_administratie_id", CLAIM, ["administratie_id"], schema="boekhouding")
    op.create_index(f"ix_{CLAIM}_document_id", CLAIM, ["document_id"], schema="boekhouding")
    _rls_op_administratie(CLAIM)


def downgrade() -> None:
    op.drop_table(CLAIM, schema="boekhouding")
    op.drop_table(CACHE, schema="boekhouding")
    # PostgreSQL kent geen DROP VALUE — de enum-waarde blijft bewust staan (zelfde keuze als 0028/0098/0122).
