"""Sync-laag per administratie (koppelcontract §2c, v1.8 definitief): platform.grootboekrekening
(gedeeld met vastgoed, RLZ-sync is enige schrijver) + boekhouding.taxrate_cache/vendor_cache/
project_cache (niet gedeeld, alleen voor het eigen controlescherm).

De GRANT aan `vastgoed_app` is voorwaardelijk (IF EXISTS): in deze lokale dev-/testomgeving
draaien alleen RLZ's eigen migraties, dus die rol bestaat hier niet — in de gedeelde productie-
Cloud SQL bestaat hij wél (via vastgoed's eigen migraties) en wordt de GRANT dan effectief.
**Aanname, nog te bevestigen door vastgoed:** de rolnaam `vastgoed_app`, naar analogie van
`boekhouding_app` (migratie 0001) — zie Platform/OPEN_ITEMS.md.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
VASTGOED_ROLE = "vastgoed_app"


def upgrade() -> None:
    # --- platform.grootboekrekening (gedeeld, koppelcontract §2c) --------------------------
    op.create_table(
        "grootboekrekening",
        sa.Column("ledger_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("soort", sa.SmallInteger(), nullable=False),
        sa.Column("is_totaalrekening", sa.Boolean(), nullable=False),
        sa.Column(
            "laatst_gesynchroniseerd", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("verdwenen_uit_bron_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.create_index(
        "ix_grootboekrekening_administratie_id", "grootboekrekening", ["administratie_id"], schema="platform"
    )

    op.execute("ALTER TABLE platform.grootboekrekening ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.grootboekrekening FORCE ROW LEVEL SECURITY")
    # Bewust GEEN current_actor_is_beheerder()-bypass hier (i.t.t. gebruiker_administratie_scope,
    # migratie 0002): die functie leest platform.gebruiker, en vastgoed_app krijgt daar terecht
    # geen SELECT op (PII van alle platformgebruikers, geen relatie tot Ledgers-leesrechten) —
    # de RLS-policy zou dan `permission denied for table gebruiker` geven zodra vastgoed_app
    # 'm evalueert. Een Beheerder-bypass kan later alsnog via een SECURITY DEFINER-variant van
    # die functie, in een eigen migratie, zodra er een concrete cross-administratie-leesbehoefte is.
    op.execute(
        """
        CREATE POLICY grootboekrekening_scope ON platform.grootboekrekening
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )

    # RLZ zelf: schrijft (sync) + leest (eigen controlescherm-dropdowns). Geen DELETE — nooit
    # hard verwijderen, dat is precies waarom verdwenen_uit_bron_op bestaat.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.grootboekrekening TO {APP_ROLE}")

    # Vastgoed: uitsluitend SELECT (§2c) — voorwaardelijk, zie moduledocstring.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{VASTGOED_ROLE}') THEN
                GRANT USAGE ON SCHEMA platform TO {VASTGOED_ROLE};
                GRANT SELECT ON platform.grootboekrekening TO {VASTGOED_ROLE};
                GRANT EXECUTE ON FUNCTION platform.current_administratie_id() TO {VASTGOED_ROLE};
            END IF;
        END
        $$
        """
    )

    # --- boekhouding.{taxrate,vendor,project}_cache (niet gedeeld) --------------------------
    op.create_table(
        "taxrate_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("naam", sa.Text(), nullable=True),
        sa.Column("brondata", JSONB, nullable=False),
        sa.Column(
            "laatst_gesynchroniseerd", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("verdwenen_uit_bron_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_table(
        "vendor_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("naam", sa.Text(), nullable=True),
        sa.Column("is_gearchiveerd", sa.Boolean(), nullable=True),
        sa.Column("brondata", JSONB, nullable=False),
        sa.Column(
            "laatst_gesynchroniseerd", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("verdwenen_uit_bron_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_table(
        "project_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("naam", sa.Text(), nullable=True),
        sa.Column("is_actief", sa.Boolean(), nullable=True),
        sa.Column("brondata", JSONB, nullable=False),
        sa.Column(
            "laatst_gesynchroniseerd", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("verdwenen_uit_bron_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )

    for tabel in ("taxrate_cache", "vendor_cache", "project_cache"):
        op.create_index(f"ix_{tabel}_administratie_id", tabel, ["administratie_id"], schema="boekhouding")
        op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
        # Zelfde afweging als grootboekrekening_scope hierboven: geen beheerder-bypass, want dat
        # vereist current_actor_is_beheerder() (leest platform.gebruiker) — hier niet nodig
        # zolang alleen boekhouding_app deze caches gebruikt, en zo blijft het consistent als dat
        # ooit verandert.
        op.execute(
            f"""
            CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
            USING (administratie_id = platform.current_administratie_id())
            WITH CHECK (administratie_id = platform.current_administratie_id())
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def downgrade() -> None:
    for tabel in ("taxrate_cache", "vendor_cache", "project_cache"):
        op.execute(f"REVOKE ALL ON boekhouding.{tabel} FROM {APP_ROLE}")
        op.execute(f"DROP POLICY IF EXISTS {tabel}_scope ON boekhouding.{tabel}")
        op.drop_table(tabel, schema="boekhouding")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{VASTGOED_ROLE}') THEN
                REVOKE ALL ON platform.grootboekrekening FROM {VASTGOED_ROLE};
                REVOKE EXECUTE ON FUNCTION platform.current_administratie_id() FROM {VASTGOED_ROLE};
            END IF;
        END
        $$
        """
    )
    op.execute(f"REVOKE ALL ON platform.grootboekrekening FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS grootboekrekening_scope ON platform.grootboekrekening")
    op.drop_table("grootboekrekening", schema="platform")
