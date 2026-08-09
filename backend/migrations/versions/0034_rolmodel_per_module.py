"""Rolmodel-fundament per module (platformbesluit 0019 "Identiteit gedeeld, autorisatie per
module", Peter 2026-08-08; vastgoed-deadline ~22-08, OPEN_ITEMS GCP-uitrol-item punt 1).

Twee gedeelde tabellen, eigendom RLZ-project (platform-fundament, besluit 0006):

- `platform.gebruiker_module_rol` — de rol van een gebruiker binnen één module. Rol is TEXT
  met een CHECK per module (géén gedeelde enum — dat is precies het besluit): module
  'vastgoed' kent superadmin/eigenaar/kantoor. RLZ's eigen rol-enum op platform.gebruiker
  blijft ONGEWIJZIGD; convergentie-afspraak: RLZ migreert t.z.t. op eigen tempo (nieuwe
  module-waarden toevoegen = kleine vervolg-migratie op de CHECK).
- `platform.gebruiker_entiteit` — scope-koppeltabel voor vastgoed-eigendom (analoog aan
  gebruiker_administratie). `entiteit_id` heeft bewust GEEN FK: vastgoed-entiteiten leven in
  de vastgoed-database/-schema, niet in `platform` — de kolom draagt vastgoeds entiteit-UUID.

RLS (besluit 0004, SET LOCAL-patroon) met DB-niveau handhaving van de mutatieregels:
- lezen: eigen rijen (gebruiker_id = current_actor_id()) of module-beheerder;
- schrijven (insert/update/delete): uitsluitend de module-beheerder, en NOOIT op je eigen
  gebruiker_id — "niemand muteert zijn eigen rol/scope, ook een Beheerder niet" is hiermee
  ook op DB-niveau dicht, niet alleen in de app-laag.
- `platform.actor_is_module_beheerder(module)` is SECURITY DEFINER: (a) hij leest
  gebruiker_module_rol zelf (RLS-recursie vermijden) en platform.gebruiker (waar vastgoed_app
  terecht geen SELECT op heeft — PII, zie migratie 0005's toelichting); (b) de
  boekhouding-tak overbrugt RLZ's huidige enum (gebruiker.rol = 'beheerder') tot de
  convergentie. Op gebruiker_module_rol staat daarom ENABLE (niet FORCE) RLS: de
  definer-eigenaar moet ongescoped kunnen lezen; app-rollen vallen wél onder de policies.

Audit: append-only audit_event-trigger op élke mutatie (hard falen zonder actor — patroon
migratie 0002), als SECURITY DEFINER zodat vastgoed_app géén INSERT-grant op audit_event
nodig heeft (administratie_id blijft NULL, toegestaan door de 0001-policy).

Systeem-actor 00000000-…-0001: idempotent geseed (bestond al via migratie 0016; hier
herhaald zodat dit fundament self-contained is voor een verse gedeelde database).

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
VASTGOED_ROLE = "vastgoed_app"
SYSTEEM_ACTOR_ID = "00000000-0000-0000-0000-000000000001"

# Rolwaarden per module (CHECK-constraint). Uitbreiden = vervolg-migratie, bewust expliciet.
MODULE_ROLLEN = {
    "vastgoed": ("superadmin", "eigenaar", "kantoor"),
}


def _check_clausule() -> str:
    delen = [
        "(module = '{m}' AND rol IN ({r}))".format(m=m, r=", ".join(f"'{rol}'" for rol in rollen))
        for m, rollen in MODULE_ROLLEN.items()
    ]
    return " OR ".join(delen)


def upgrade() -> None:
    # --- systeem-actor (idempotent; zie module-docstring) -----------------------------------
    op.execute(
        f"""
        INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status)
        VALUES ('{SYSTEEM_ACTOR_ID}', 'Systeem (achtergrondverwerking)', 'systeem@platform.intern',
                'boekhouding', 'geblokkeerd')
        ON CONFLICT (id) DO NOTHING
        """
    )

    # --- gebruiker_module_rol ----------------------------------------------------------------
    op.create_table(
        "gebruiker_module_rol",
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), primary_key=True),
        sa.Column("module", sa.Text(), primary_key=True),
        sa.Column("rol", sa.Text(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(_check_clausule(), name="ck_gebruiker_module_rol_geldig"),
        schema="platform",
    )

    # --- gebruiker_entiteit (vastgoed-eigendomsscope; entiteit_id bewust zonder FK) ----------
    op.create_table(
        "gebruiker_entiteit",
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), primary_key=True),
        sa.Column("entiteit_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="platform",
    )
    op.create_index("ix_gebruiker_entiteit_entiteit_id", "gebruiker_entiteit", ["entiteit_id"], schema="platform")

    # --- module-beheerder-check (SECURITY DEFINER — zie module-docstring) --------------------
    op.execute(
        """
        CREATE FUNCTION platform.actor_is_module_beheerder(p_module text) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = platform, pg_temp
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM platform.gebruiker_module_rol r
                WHERE r.gebruiker_id = platform.current_actor_id()
                  AND r.module = p_module
                  AND r.rol = CASE p_module WHEN 'vastgoed' THEN 'superadmin' ELSE NULL END
            )
            OR (p_module = 'boekhouding' AND platform.current_actor_is_beheerder())
        $$
        """
    )

    # --- RLS -----------------------------------------------------------------------------------
    op.execute("ALTER TABLE platform.gebruiker_module_rol ENABLE ROW LEVEL SECURITY")
    # Bewust geen FORCE (enige uitzondering op het huispatroon, gemotiveerd in de docstring):
    # de SECURITY DEFINER-check moet deze tabel ongescoped kunnen lezen.
    op.execute(
        """
        CREATE POLICY gebruiker_module_rol_lees ON platform.gebruiker_module_rol FOR SELECT
        USING (gebruiker_id = platform.current_actor_id() OR platform.actor_is_module_beheerder(module))
        """
    )
    op.execute(
        """
        CREATE POLICY gebruiker_module_rol_insert ON platform.gebruiker_module_rol FOR INSERT
        WITH CHECK (platform.actor_is_module_beheerder(module)
                    AND gebruiker_id IS DISTINCT FROM platform.current_actor_id())
        """
    )
    op.execute(
        """
        CREATE POLICY gebruiker_module_rol_update ON platform.gebruiker_module_rol FOR UPDATE
        USING (platform.actor_is_module_beheerder(module)
               AND gebruiker_id IS DISTINCT FROM platform.current_actor_id())
        WITH CHECK (platform.actor_is_module_beheerder(module)
                    AND gebruiker_id IS DISTINCT FROM platform.current_actor_id())
        """
    )
    op.execute(
        """
        CREATE POLICY gebruiker_module_rol_delete ON platform.gebruiker_module_rol FOR DELETE
        USING (platform.actor_is_module_beheerder(module)
               AND gebruiker_id IS DISTINCT FROM platform.current_actor_id())
        """
    )

    op.execute("ALTER TABLE platform.gebruiker_entiteit ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.gebruiker_entiteit FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY gebruiker_entiteit_lees ON platform.gebruiker_entiteit FOR SELECT
        USING (gebruiker_id = platform.current_actor_id() OR platform.actor_is_module_beheerder('vastgoed'))
        """
    )
    op.execute(
        """
        CREATE POLICY gebruiker_entiteit_insert ON platform.gebruiker_entiteit FOR INSERT
        WITH CHECK (platform.actor_is_module_beheerder('vastgoed')
                    AND gebruiker_id IS DISTINCT FROM platform.current_actor_id())
        """
    )
    op.execute(
        """
        CREATE POLICY gebruiker_entiteit_delete ON platform.gebruiker_entiteit FOR DELETE
        USING (platform.actor_is_module_beheerder('vastgoed')
               AND gebruiker_id IS DISTINCT FROM platform.current_actor_id())
        """
    )

    # --- audit-triggers (SECURITY DEFINER — vastgoed_app hoeft audit_event niet te kunnen
    # schrijven; administratie_id NULL past binnen de 0001-policy) ----------------------------
    op.execute(
        """
        CREATE FUNCTION platform.audit_gebruiker_module_rol_wijziging() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = platform, pg_temp
        AS $$
        DECLARE
            v_actor uuid;
            v_module text;
            v_record uuid;
            v_actie text;
            v_oude jsonb;
            v_nieuwe jsonb;
        BEGIN
            v_actor := platform.current_actor_id();
            IF v_actor IS NULL THEN
                RAISE EXCEPTION 'app.current_actor_id niet gezet — module-rol-wijziging vereist een bekende actor voor audit_event';
            END IF;
            IF TG_OP = 'INSERT' THEN
                v_module := NEW.module; v_record := NEW.gebruiker_id; v_actie := 'module_rol_toegevoegd';
                v_oude := NULL; v_nieuwe := jsonb_build_object('module', NEW.module, 'rol', NEW.rol);
            ELSIF TG_OP = 'UPDATE' THEN
                v_module := NEW.module; v_record := NEW.gebruiker_id; v_actie := 'module_rol_gewijzigd';
                v_oude := jsonb_build_object('module', OLD.module, 'rol', OLD.rol);
                v_nieuwe := jsonb_build_object('module', NEW.module, 'rol', NEW.rol);
            ELSE
                v_module := OLD.module; v_record := OLD.gebruiker_id; v_actie := 'module_rol_verwijderd';
                v_oude := jsonb_build_object('module', OLD.module, 'rol', OLD.rol); v_nieuwe := NULL;
            END IF;
            INSERT INTO platform.audit_event
                (id, actor_id, module, tabel, record_id, actie, oude_waarde, nieuwe_waarde, correlatie_id)
            VALUES (gen_random_uuid(), v_actor, v_module, 'gebruiker_module_rol', v_record, v_actie,
                    v_oude, v_nieuwe, gen_random_uuid());
            RETURN COALESCE(NEW, OLD);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_gebruiker_module_rol
        AFTER INSERT OR UPDATE OR DELETE ON platform.gebruiker_module_rol
        FOR EACH ROW EXECUTE FUNCTION platform.audit_gebruiker_module_rol_wijziging()
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.audit_gebruiker_entiteit_wijziging() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = platform, pg_temp
        AS $$
        DECLARE
            v_actor uuid;
            v_record uuid;
            v_actie text;
            v_oude jsonb;
            v_nieuwe jsonb;
        BEGIN
            v_actor := platform.current_actor_id();
            IF v_actor IS NULL THEN
                RAISE EXCEPTION 'app.current_actor_id niet gezet — entiteit-scope-wijziging vereist een bekende actor voor audit_event';
            END IF;
            IF TG_OP = 'INSERT' THEN
                v_record := NEW.gebruiker_id; v_actie := 'entiteit_scope_toegevoegd';
                v_oude := NULL; v_nieuwe := jsonb_build_object('entiteit_id', NEW.entiteit_id);
            ELSE
                v_record := OLD.gebruiker_id; v_actie := 'entiteit_scope_verwijderd';
                v_oude := jsonb_build_object('entiteit_id', OLD.entiteit_id); v_nieuwe := NULL;
            END IF;
            INSERT INTO platform.audit_event
                (id, actor_id, module, tabel, record_id, actie, oude_waarde, nieuwe_waarde, correlatie_id)
            VALUES (gen_random_uuid(), v_actor, 'vastgoed', 'gebruiker_entiteit', v_record, v_actie,
                    v_oude, v_nieuwe, gen_random_uuid());
            RETURN COALESCE(NEW, OLD);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_gebruiker_entiteit
        AFTER INSERT OR DELETE ON platform.gebruiker_entiteit
        FOR EACH ROW EXECUTE FUNCTION platform.audit_gebruiker_entiteit_wijziging()
        """
    )

    # --- GRANTs --------------------------------------------------------------------------------
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON platform.gebruiker_module_rol TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON platform.gebruiker_entiteit TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION platform.actor_is_module_beheerder(text) TO {APP_ROLE}")
    # Vastgoed: voorwaardelijk (rol bestaat pas bij de GCP-uitrol — zelfde patroon als 0005).
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{VASTGOED_ROLE}') THEN
                GRANT USAGE ON SCHEMA platform TO {VASTGOED_ROLE};
                GRANT SELECT, INSERT, UPDATE, DELETE ON platform.gebruiker_module_rol TO {VASTGOED_ROLE};
                GRANT SELECT, INSERT, DELETE ON platform.gebruiker_entiteit TO {VASTGOED_ROLE};
                GRANT EXECUTE ON FUNCTION platform.current_actor_id() TO {VASTGOED_ROLE};
                GRANT EXECUTE ON FUNCTION platform.actor_is_module_beheerder(text) TO {VASTGOED_ROLE};
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.gebruiker_entiteit FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON platform.gebruiker_module_rol FROM {APP_ROLE}")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_gebruiker_entiteit ON platform.gebruiker_entiteit")
    op.execute("DROP FUNCTION IF EXISTS platform.audit_gebruiker_entiteit_wijziging()")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_gebruiker_module_rol ON platform.gebruiker_module_rol")
    op.execute("DROP FUNCTION IF EXISTS platform.audit_gebruiker_module_rol_wijziging()")
    # Tabellen éérst (dat ruimt de policies op die van de functie afhangen), dan pas de functie.
    op.drop_table("gebruiker_entiteit", schema="platform")
    op.drop_table("gebruiker_module_rol", schema="platform")
    op.execute("DROP FUNCTION IF EXISTS platform.actor_is_module_beheerder(text)")
    # systeem-actor blijft staan (gedeeld, ook door 0016 gebruikt)
