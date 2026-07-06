"""Platform-basis auth: gebruiker (wachtwoord/rol/status), gebruiker_administratie (scope),
uitnodiging, totp_secret. RLS op gebruiker_administratie (administratie-gebonden, conventie:
geen uitzonderingen) + audit_event-triggers op elke rol-/scope-wijziging (besluit 0004).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import BYTEA, ENUM, UUID

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"

GEBRUIKER_ROL_VALUES = ("beheerder", "boekhouding_projecten", "boekhouding", "klant_accordeur")
GEBRUIKER_STATUS_VALUES = ("uitgenodigd", "wacht_op_totp", "actief", "geblokkeerd")


def upgrade() -> None:
    gebruiker_rol = ENUM(*GEBRUIKER_ROL_VALUES, name="gebruiker_rol", schema="platform")
    gebruiker_status = ENUM(*GEBRUIKER_STATUS_VALUES, name="gebruiker_status", schema="platform")
    gebruiker_rol.create(op.get_bind(), checkfirst=True)
    gebruiker_status.create(op.get_bind(), checkfirst=True)

    # --- gebruiker: auth-kolommen erbij (tabel is leeg in elke omgeving tot nu toe — fase 1 had
    # nog geen auth — dus NOT NULL zonder backfill-default is hier veilig). ------------------
    op.add_column("gebruiker", sa.Column("wachtwoord_hash", sa.Text(), nullable=True), schema="platform")
    op.add_column(
        "gebruiker",
        sa.Column("rol", ENUM(*GEBRUIKER_ROL_VALUES, name="gebruiker_rol", schema="platform", create_type=False), nullable=False),
        schema="platform",
    )
    op.add_column(
        "gebruiker",
        sa.Column(
            "status",
            ENUM(*GEBRUIKER_STATUS_VALUES, name="gebruiker_status", schema="platform", create_type=False),
            nullable=False,
            server_default="uitgenodigd",
        ),
        schema="platform",
    )

    # --- gebruiker_administratie: scope-koppeltabel (administratie-gebonden -> RLS verplicht) ---
    op.create_table(
        "gebruiker_administratie",
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="platform",
    )

    # --- uitnodiging: eenmalige token-hash, 72u vervaltijd ---------------------------------
    op.create_table(
        "uitnodiging",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verloopt_op", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gebruikt_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.create_index("ix_uitnodiging_gebruiker_id", "uitnodiging", ["gebruiker_id"], schema="platform")

    # --- totp_secret: envelope-versleuteld at rest (app/security/envelope.py) --------------
    op.create_table(
        "totp_secret",
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), primary_key=True),
        sa.Column("secret_ciphertext", BYTEA, nullable=False),
        sa.Column("wrapped_data_key", BYTEA, nullable=False),
        sa.Column("laatste_stap", sa.BigInteger(), nullable=True),
        sa.Column("bevestigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="platform",
    )

    # --- actor-context (zelfde SET LOCAL-patroon als current_administratie_id, migratie 0001) --
    op.execute(
        """
        CREATE FUNCTION platform.current_actor_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT nullif(current_setting('app.current_actor_id', true), '')::uuid
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.current_actor_is_beheerder() RETURNS boolean
        LANGUAGE sql STABLE AS $$
            SELECT EXISTS (
                SELECT 1 FROM platform.gebruiker g
                WHERE g.id = platform.current_actor_id()
                  AND g.rol = 'beheerder'
                  AND g.status = 'actief'
            )
        $$
        """
    )

    # --- RLS op gebruiker_administratie (administratie-gebonden, registers/conventies.md: geen
    # uitzonderingen). Een Beheerder-sessie is platform-breed (geen current_administratie_id),
    # dus krijgt een losse, op rol gebaseerde bypass i.p.v. de generieke BYPASSRLS-grant (die
    # ALLE RLS-tabellen zou omzeilen, niet alleen deze) — zie migratie 0001's toelichting bij
    # "een rol moet BYPASSRLS krijgen... wat een expliciete, aparte beslissing is". -----------
    op.execute("ALTER TABLE platform.gebruiker_administratie ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.gebruiker_administratie FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY gebruiker_administratie_scope ON platform.gebruiker_administratie
        USING (administratie_id = platform.current_administratie_id() OR platform.current_actor_is_beheerder())
        WITH CHECK (administratie_id = platform.current_administratie_id() OR platform.current_actor_is_beheerder())
        """
    )

    # --- audit_event-triggers: elke rol-/scope-wijziging append-only vastgelegd, altijd met een
    # bekende actor (anders faalt de trigger hard — "niets verdwijnt stil" geldt ook voor wie de
    # wijziging deed). administratie_id op het audit_event-record blijft hier bewust NULL (een
    # Beheerder-sessie is platform-breed scoped, dus een non-NULL administratie_id zou de
    # audit_event-RLS-WITH CHECK van migratie 0001 laten falen); de administratie staat al in
    # oude_waarde/nieuwe_waarde. ---------------------------------------------------------------
    op.execute(
        """
        CREATE FUNCTION platform.audit_gebruiker_rol_wijziging() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_actor uuid;
        BEGIN
            IF NEW.rol IS DISTINCT FROM OLD.rol THEN
                v_actor := platform.current_actor_id();
                IF v_actor IS NULL THEN
                    RAISE EXCEPTION 'app.current_actor_id niet gezet — rol-wijziging vereist een bekende actor voor audit_event';
                END IF;
                INSERT INTO platform.audit_event
                    (id, actor_id, module, tabel, record_id, actie, oude_waarde, nieuwe_waarde, correlatie_id)
                VALUES (
                    gen_random_uuid(), v_actor, 'platform', 'gebruiker', NEW.id, 'rol_wijziging',
                    jsonb_build_object('rol', OLD.rol), jsonb_build_object('rol', NEW.rol), gen_random_uuid()
                );
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_gebruiker_rol_wijziging
        AFTER UPDATE ON platform.gebruiker
        FOR EACH ROW EXECUTE FUNCTION platform.audit_gebruiker_rol_wijziging()
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.audit_gebruiker_administratie_wijziging() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_actor uuid;
            v_record uuid;
            v_actie text;
            v_oude jsonb;
            v_nieuwe jsonb;
        BEGIN
            v_actor := platform.current_actor_id();
            IF v_actor IS NULL THEN
                RAISE EXCEPTION 'app.current_actor_id niet gezet — scope-wijziging vereist een bekende actor voor audit_event';
            END IF;
            IF TG_OP = 'INSERT' THEN
                v_record := NEW.gebruiker_id;
                v_actie := 'scope_toegevoegd';
                v_nieuwe := jsonb_build_object('administratie_id', NEW.administratie_id);
                v_oude := NULL;
            ELSE
                v_record := OLD.gebruiker_id;
                v_actie := 'scope_verwijderd';
                v_oude := jsonb_build_object('administratie_id', OLD.administratie_id);
                v_nieuwe := NULL;
            END IF;
            INSERT INTO platform.audit_event
                (id, actor_id, module, tabel, record_id, actie, oude_waarde, nieuwe_waarde, correlatie_id)
            VALUES (gen_random_uuid(), v_actor, 'platform', 'gebruiker_administratie', v_record, v_actie, v_oude, v_nieuwe, gen_random_uuid());
            RETURN COALESCE(NEW, OLD);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_gebruiker_administratie_insert
        AFTER INSERT ON platform.gebruiker_administratie
        FOR EACH ROW EXECUTE FUNCTION platform.audit_gebruiker_administratie_wijziging()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_gebruiker_administratie_delete
        AFTER DELETE ON platform.gebruiker_administratie
        FOR EACH ROW EXECUTE FUNCTION platform.audit_gebruiker_administratie_wijziging()
        """
    )

    # --- GRANTs (least-privilege runtime-rol) ----------------------------------------------
    op.execute(f"GRANT SELECT, INSERT, DELETE ON platform.gebruiker_administratie TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.uitnodiging TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.totp_secret TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION platform.current_actor_id() TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION platform.current_actor_is_beheerder() TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE EXECUTE ON FUNCTION platform.current_actor_is_beheerder() FROM {APP_ROLE}")
    op.execute(f"REVOKE EXECUTE ON FUNCTION platform.current_actor_id() FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON platform.totp_secret FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON platform.uitnodiging FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON platform.gebruiker_administratie FROM {APP_ROLE}")

    op.execute("DROP TRIGGER IF EXISTS trg_audit_gebruiker_administratie_delete ON platform.gebruiker_administratie")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_gebruiker_administratie_insert ON platform.gebruiker_administratie")
    op.execute("DROP FUNCTION IF EXISTS platform.audit_gebruiker_administratie_wijziging()")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_gebruiker_rol_wijziging ON platform.gebruiker")
    op.execute("DROP FUNCTION IF EXISTS platform.audit_gebruiker_rol_wijziging()")

    op.execute("DROP POLICY IF EXISTS gebruiker_administratie_scope ON platform.gebruiker_administratie")
    op.execute("DROP FUNCTION IF EXISTS platform.current_actor_is_beheerder()")
    op.execute("DROP FUNCTION IF EXISTS platform.current_actor_id()")

    op.drop_table("totp_secret", schema="platform")
    op.drop_table("uitnodiging", schema="platform")
    op.drop_table("gebruiker_administratie", schema="platform")

    op.drop_column("gebruiker", "status", schema="platform")
    op.drop_column("gebruiker", "rol", schema="platform")
    op.drop_column("gebruiker", "wachtwoord_hash", schema="platform")

    op.execute("DROP TYPE IF EXISTS platform.gebruiker_status")
    op.execute("DROP TYPE IF EXISTS platform.gebruiker_rol")
