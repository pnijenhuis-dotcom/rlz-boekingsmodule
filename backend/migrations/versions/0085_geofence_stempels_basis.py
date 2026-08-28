"""Geofence-stempels BASIS (bouwrun 28-08 blok C, mockup geofence-stempels.html = bouwnorm; richting
akkoord Peter 27-08, jurist akkoord 28-08 — regeling via de algemene voorwaarden/privacyverklaring,
géén apart instemmingsscherm).

1. boekhouding.project_specificatie: `locatie_adres`, `locatie_lat`/`locatie_lon` (WGS84) en
   `zone_straal_m` — de projectzone. Zonder locatie = geen geofence voor dat project (stil).
2. boekhouding.werkstempel — APPEND-ONLY stempels {tijdstip, project, in/uit} van de veldwerker
   zelf (nooit namens); bron 'app' (later 'os_geofence'), apparaat-id ter herleiding. Uitsluitend
   een SIGNAALBRON voor de keurder (kolom "gestempeld aanwezig", oranje vlag bij > 1,0 u
   afwijking, markering "onvolledig paar") — nooit automatische korting (DBA-grens). Zichtbaar
   voor kantoor-keurders en de veldwerker zelf; bewaartermijn = weekstaten. RLS per administratie,
   GRANT SELECT + INSERT (geen UPDATE/DELETE: append-only).
De native achtergrondlocatie (manifest/permissies/OS-geofence-registratie) zit NIET in deze
migratie/run — eigen release-ronde ná de eerste Play-release. Schema-only.

Revision ID: 0085
Revises: 0084
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.add_column("project_specificatie", sa.Column("locatie_adres", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column(
        "project_specificatie", sa.Column("locatie_lat", sa.Numeric(9, 6), nullable=True), schema="boekhouding"
    )
    op.add_column(
        "project_specificatie", sa.Column("locatie_lon", sa.Numeric(9, 6), nullable=True), schema="boekhouding"
    )
    op.add_column(
        "project_specificatie", sa.Column("zone_straal_m", sa.SmallInteger(), nullable=True), schema="boekhouding"
    )
    op.create_check_constraint(
        "ck_project_specificatie_zone_straal",
        "project_specificatie",
        "zone_straal_m IS NULL OR (zone_straal_m >= 50 AND zone_straal_m <= 1000)",
        schema="boekhouding",
    )

    op.create_table(
        "werkstempel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tijdstip", sa.DateTime(timezone=True), nullable=False),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("bron", sa.Text(), nullable=False, server_default="app"),
        sa.Column("apparaat_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ontvangen_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("soort IN ('in', 'uit')", name="ck_werkstempel_soort"),
        sa.CheckConstraint("bron IN ('app', 'os_geofence')", name="ck_werkstempel_bron"),
        sa.UniqueConstraint("gebruiker_id", "project_id", "tijdstip", "soort", name="uq_werkstempel_moment"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_werkstempel_gebruiker_tijdstip", "werkstempel", ["gebruiker_id", "tijdstip"], schema="boekhouding"
    )
    op.create_index("ix_werkstempel_administratie_id", "werkstempel", ["administratie_id"], schema="boekhouding")
    op.execute("ALTER TABLE boekhouding.werkstempel ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.werkstempel FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY werkstempel_scope ON boekhouding.werkstempel
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    # Append-only: geen UPDATE, geen DELETE.
    op.execute(f"GRANT SELECT, INSERT ON boekhouding.werkstempel TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS werkstempel_scope ON boekhouding.werkstempel")
    op.drop_index("ix_werkstempel_administratie_id", table_name="werkstempel", schema="boekhouding")
    op.drop_index("ix_werkstempel_gebruiker_tijdstip", table_name="werkstempel", schema="boekhouding")
    op.drop_table("werkstempel", schema="boekhouding")
    op.drop_constraint("ck_project_specificatie_zone_straal", "project_specificatie", schema="boekhouding")
    op.drop_column("project_specificatie", "zone_straal_m", schema="boekhouding")
    op.drop_column("project_specificatie", "locatie_lon", schema="boekhouding")
    op.drop_column("project_specificatie", "locatie_lat", schema="boekhouding")
    op.drop_column("project_specificatie", "locatie_adres", schema="boekhouding")
