"""Vastly-verkoopfacturen volledig automatisch (Peter 28/29-09 "moet gewoon als omzet geboekt worden, punt";
BESLISSINGEN "VASTLY-VERKOOP VOLLEDIG AUTOMATISCH — ENTITEITENREGISTER, OMZETREKENING PER ADMINISTRATIE, GEEN
VERZAMELBAK (Peter 29-09)").

1. `boekhouding.vastly_entiteit_koppeling` — het entiteitenregister voor de verkoopkant: sleutel uit de UBL van de
   verhuurder (KvK van de AccountingSupplierParty, anders de genormaliseerde naam) → platform-administratie. Bron
   'identiteit' (afgeleid uit `administratie_identiteit.kvk`, precies één treffer), 'mens' (koppeling via de bevinding
   "Koppel aan administratie…"). Platformbreed (gelezen bij intake in scoped_session(None)) — RLS USING (true) als
   vangnet-structuur (patroon intake_bericht_verwerkt 0171); GRANT zonder DELETE.
2. `boekhouding.vastly_omzetrekening` — de vaste omzetrekening per (administratie, regelsoort huur/servicekosten/
   waarborg/overig): bron 'historie' (afgeleid uit de eigen geboekte Vastly-verkoopregels of het eenduidige
   rekeningschema) of 'mens' (Instellingen › Administratie › Vastgoed-koppeling, of de bevinding "Rekening kiezen").
   RLS op administratie (patroon verkoop_btw_voorkeur 0038); GRANT zonder DELETE.
Schema-only (pure DDL); de heraanbieding van de 23 + 9 open documenten is een losse job-executie
(`vastly-verkoop-heraanbieden --uitvoeren`).

Revision ID: 0172
Revises: 0171
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0172"
down_revision: str | None = "0171"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None
APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "vastly_entiteit_koppeling",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sleutel_soort", sa.Text(), nullable=False),
        sa.Column("sleutel", sa.Text(), nullable=False),
        sa.Column(
            "administratie_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform.administratie.id"),
            nullable=False,
        ),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("weergave", sa.Text(), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("aangemaakt_door", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("sleutel_soort IN ('kvk', 'naam')", name="ck_vastly_entiteit_koppeling_sleutel_soort"),
        sa.CheckConstraint("bron IN ('identiteit', 'mens')", name="ck_vastly_entiteit_koppeling_bron"),
        schema="boekhouding",
    )
    op.create_index(
        "ux_vastly_entiteit_koppeling_sleutel",
        "vastly_entiteit_koppeling",
        ["sleutel_soort", "sleutel"],
        unique=True,
        schema="boekhouding",
    )
    op.create_index(
        "ix_vastly_entiteit_koppeling_administratie_id",
        "vastly_entiteit_koppeling",
        ["administratie_id"],
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.vastly_entiteit_koppeling ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.vastly_entiteit_koppeling FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY vastly_entiteit_koppeling_scope ON boekhouding.vastly_entiteit_koppeling
        USING (true)
        WITH CHECK (true)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.vastly_entiteit_koppeling TO {APP_ROLE}")

    op.create_table(
        "vastly_omzetrekening",
        sa.Column(
            "administratie_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform.administratie.id"),
            primary_key=True,
        ),
        sa.Column("regelsoort", sa.Text(), primary_key=True),
        sa.Column("ledger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gewijzigd_door", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "regelsoort IN ('huur', 'servicekosten', 'waarborg', 'overig')", name="ck_vastly_omzetrekening_regelsoort"
        ),
        sa.CheckConstraint("bron IN ('historie', 'mens')", name="ck_vastly_omzetrekening_bron"),
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.vastly_omzetrekening ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.vastly_omzetrekening FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY vastly_omzetrekening_scope ON boekhouding.vastly_omzetrekening
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.vastly_omzetrekening TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS vastly_omzetrekening_scope ON boekhouding.vastly_omzetrekening")
    op.drop_table("vastly_omzetrekening", schema="boekhouding")
    op.execute("DROP POLICY IF EXISTS vastly_entiteit_koppeling_scope ON boekhouding.vastly_entiteit_koppeling")
    op.drop_index(
        "ix_vastly_entiteit_koppeling_administratie_id", table_name="vastly_entiteit_koppeling", schema="boekhouding"
    )
    op.drop_index("ux_vastly_entiteit_koppeling_sleutel", table_name="vastly_entiteit_koppeling", schema="boekhouding")
    op.drop_table("vastly_entiteit_koppeling", schema="boekhouding")
