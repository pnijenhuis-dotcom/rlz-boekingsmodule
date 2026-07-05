"""Fundament: schema's platform/boekhouding, audit_event (append-only), RLS op administratie-scope.

Koppelcontract v1.5 (platformbrede afspraken, RLZ-project = eigenaar van het fundament):
uniform audit_event-schema als bron voor de WORM-export; PII (platform.gebruiker) gescheiden
van financiële data (die uitsluitend in boekhouding leeft); Row-Level Security op
administratie-scope met een per-transactie SET LOCAL-equivalent (nooit sessie-breed, i.v.m.
connection pooling).

Revision ID: 0001
Revises:
Create Date: 2026-07-05

"""

import os
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Least-privilege runtime-rol van de applicatie (zie app/config.py: app_database_url).
APP_ROLE = "boekhouding_app"
_DEV_ENVIRONMENTS = ("dev", "local")


def _resolve_app_role_password(env: Mapping[str, str]) -> str:
    """Wachtwoord voor APP_ROLE. Het 'devpassword'-fallback mag nooit stilzwijgend in productie
    belanden: buiten dev/local moet APP_DB_PASSWORD (Cloud SQL: via Secret Manager) expliciet
    gezet zijn, anders faalt de migratie hard vóórdat er ook maar één DDL-statement draait."""
    password = env.get("APP_DB_PASSWORD")
    if password:
        return password
    environment = env.get("ENVIRONMENT", "dev")
    if environment not in _DEV_ENVIRONMENTS:
        raise RuntimeError(
            f"APP_DB_PASSWORD ontbreekt en ENVIRONMENT={environment!r} is geen dev-omgeving "
            f"({', '.join(_DEV_ENVIRONMENTS)}). Weiger het lokale-dev-fallback-wachtwoord te "
            "gebruiken buiten ontwikkeling — zet APP_DB_PASSWORD (Cloud SQL: via Secret Manager) "
            "vóórdat je deze migratie draait."
        )
    return "devpassword"


APP_ROLE_PASSWORD = _resolve_app_role_password(os.environ)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS platform")
    op.execute("CREATE SCHEMA IF NOT EXISTS boekhouding")

    op.create_table(
        "administratie",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("naam", sa.Text, nullable=False),
        sa.Column("rlz_admin_id", sa.Text, nullable=False, unique=True),
        sa.Column("actief", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="platform",
    )

    op.create_table(
        "gebruiker",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("naam", sa.Text, nullable=False),
        sa.Column("e_mail", sa.Text, nullable=False, unique=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # AVG-verwijderverzoek = dit veld zetten, nooit de rij hard verwijderen.
        sa.Column("gepseudonimiseerd_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
        comment="PII van platformgebruikers. Bevat nooit financiële velden — die leven uitsluitend "
        "in het boekhouding-schema.",
    )

    op.create_table(
        "audit_event",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tijdstip", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "actor_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False
        ),
        sa.Column("module", sa.Text, nullable=False),
        sa.Column("tabel", sa.Text, nullable=False),
        sa.Column("record_id", UUID(as_uuid=True), nullable=False),
        sa.Column("actie", sa.Text, nullable=False),
        sa.Column("oude_waarde", JSONB, nullable=True),
        sa.Column("nieuwe_waarde", JSONB, nullable=True),
        sa.Column("correlatie_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "administratie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.administratie.id"),
            nullable=True,
        ),
        schema="platform",
        comment="Append-only audit-log (bron voor de WORM-export). UPDATE/DELETE zijn niet "
        "gegrant aan de app-rol — zie GRANTs onderaan deze migratie.",
    )
    op.create_index(
        "ix_audit_event_administratie_id", "audit_event", ["administratie_id"], schema="platform"
    )
    op.create_index("ix_audit_event_tabel_record", "audit_event", ["tabel", "record_id"], schema="platform")
    # Documenttijdlijn (binnenkomst -> extractie -> vraag -> accordering -> boeking) is een kernquery.
    op.create_index("ix_audit_event_correlatie_id", "audit_event", ["correlatie_id"], schema="platform")
    # WORM-export batcht op tijd (bv. "alles sinds laatste export").
    op.create_index("ix_audit_event_tijdstip", "audit_event", ["tijdstip"], schema="platform")

    # --- Row-Level Security op administratie-scope -------------------------------------------
    #
    # De scope wordt per transactie gezet met set_config('app.current_administratie_id', ..., true)
    # — het functie-equivalent van SET LOCAL (zie app/db/session.py). Onbekende/ontbrekende scope
    # levert NULL op: het beleid toont dan uitsluitend platformbrede rijen (administratie_id IS
    # NULL), nooit alle administraties. "Open by default" is hier dus niet mogelijk — een rol moet
    # BYPASSRLS krijgen om cross-administratie te lezen, wat een expliciete, aparte beslissing is.
    op.execute(
        """
        CREATE FUNCTION platform.current_administratie_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT nullif(current_setting('app.current_administratie_id', true), '')::uuid
        $$
        """
    )
    op.execute("ALTER TABLE platform.audit_event ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.audit_event FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_event_administratie_scope ON platform.audit_event
        USING (administratie_id IS NULL OR administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id IS NULL OR administratie_id = platform.current_administratie_id())
        """
    )

    # --- Least-privilege runtime-rol --------------------------------------------------------
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_ROLE_PASSWORD}';
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA platform, boekhouding TO {APP_ROLE}")
    # audit_event is append-only: bewust geen UPDATE/DELETE.
    op.execute(f"GRANT SELECT, INSERT ON platform.audit_event TO {APP_ROLE}")
    # Referentietabellen: gewone mutatie toegestaan (bv. gepseudonimiseerd_op zetten), geen DELETE
    # — "nooit hard verwijderen" geldt ook voor platformgebruikers/administraties.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.administratie, platform.gebruiker TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION platform.current_administratie_id() TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.administratie, platform.gebruiker, platform.audit_event FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA platform, boekhouding FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS audit_event_administratie_scope ON platform.audit_event")
    op.execute("DROP FUNCTION IF EXISTS platform.current_administratie_id()")
    op.drop_table("audit_event", schema="platform")
    op.drop_table("gebruiker", schema="platform")
    op.drop_table("administratie", schema="platform")
    op.execute("DROP SCHEMA IF EXISTS boekhouding CASCADE")
    op.execute("DROP SCHEMA IF EXISTS platform CASCADE")
    # Rollen zijn cluster-breed in Postgres, niet database-lokaal — bewust GEEN DROP ROLE hier.
    # Als dezelfde clusterrol ook rechten heeft in een andere database (bv. dev + test lokaal op
    # hetzelfde Postgres-cluster), faalt DROP ROLE met "DependentObjectsStillExist" of erger, sloopt
    # hij per ongeluk een rol die een andere database nog gebruikt. Rolbeheer is een aparte,
    # cluster-niveau taak (buiten migraties om), niet iets om per downgrade() te reverten.
