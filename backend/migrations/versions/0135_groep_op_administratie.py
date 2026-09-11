"""Groepskenmerk op administratie: tabel groep + administratie.groep_id (blok 8 run 11-09 middag).

Opdracht Peter 11-09 (datalaag, schaalbaar — geen lijstonderhoud): een administratie kan tot hoogstens één GROEP
horen (bv. "Kempen groep"). De groep is een FILTER op kantoorbrede overzichten (klantenlijst, Inzicht › Reconciliatie,
Instellingen › Administraties) — nooit een poort (Kernprincipe 7). Consolidatie/eliminatie is bewust NIET deze laag
(liquiditeit-mockup, aparte run).

`platform.groep`: id, naam, code (kort, uniek, alleen hoofdletters/cijfers — CHECK), actief (archiveren = false, nooit
verwijderen), aangemaakt_op. RLS zoals de andere platformbrede referentietabellen mét Beheerder-mutatie
(patroon `detacheerder_koppeling`, 0056): SELECT voor elke ingelogde (de tabel is een naslag, net als
`platform.administratie` zelf — die heeft geen policy), INSERT/UPDATE uitsluitend `platform.current_actor_is_beheerder()`,
GEEN DELETE-policy en geen DELETE-grant (niets verdwijnt stil). ENABLE + FORCE zoals overal.
`platform.administratie.groep_id`: nullable FK naar groep + index (het filter leest erop).

Eerste groep "Kempen groep" wordt bewust NIET hier gevuld — Peter maakt 'm via de UI en kent de leden toe.
Schema-only (pure DDL), geen backfill.

Revision ID: 0135
Revises: 0134
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0135"
down_revision: str | None = "0134"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "groep",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("actief", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9]{2,12}$'", name="ck_groep_code_vorm"),
        sa.CheckConstraint("length(btrim(naam)) > 0", name="ck_groep_naam_niet_leeg"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_groep_code"),
        schema="platform",
    )
    op.execute("ALTER TABLE platform.groep ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.groep FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY groep_lees ON platform.groep FOR SELECT USING (true)")
    op.execute(
        """
        CREATE POLICY groep_toevoegen ON platform.groep
        FOR INSERT WITH CHECK (platform.current_actor_is_beheerder())
        """
    )
    op.execute(
        """
        CREATE POLICY groep_muteren ON platform.groep
        FOR UPDATE USING (platform.current_actor_is_beheerder())
        WITH CHECK (platform.current_actor_is_beheerder())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.groep TO {APP_ROLE}")

    op.add_column("administratie", sa.Column("groep_id", sa.UUID(), nullable=True), schema="platform")
    op.create_foreign_key(
        "fk_administratie_groep_id",
        "administratie",
        "groep",
        ["groep_id"],
        ["id"],
        source_schema="platform",
        referent_schema="platform",
    )
    op.create_index("ix_administratie_groep_id", "administratie", ["groep_id"], schema="platform")


def downgrade() -> None:
    op.drop_index("ix_administratie_groep_id", table_name="administratie", schema="platform")
    op.drop_constraint("fk_administratie_groep_id", "administratie", schema="platform", type_="foreignkey")
    op.drop_column("administratie", "groep_id", schema="platform")
    op.drop_table("groep", schema="platform")
