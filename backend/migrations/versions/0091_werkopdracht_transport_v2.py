"""Planning-uitbreiding 31-08 (mockup planning-werkopdracht-transport.html, akkoord Peter):

1. WERKOPDRACHT per project × periode: boekhouding.werkopdracht + werkopdracht_dag
   (dag-override) — APPEND-ONLY (GRANT zonder UPDATE/DELETE: wijzigen = nieuwe versie-rij,
   niets wordt overschreven), RLS per administratie (0074-patroon).
2. TRANSPORT-statusflow her-enum: gereserveerd (rood) → bevestigd (oranje) → definitief
   (groen) → geleverd (grijs). De CHECK laat de legacywaarde 'gepland' bewust toe: deze
   migratie is puur DDL (Alembic op Cloud SQL heeft geen BYPASSRLS — een data-UPDATE zou
   stil 0 rijen raken, 0088-les); de app behandelt 'gepland' overal als 'gereserveerd' en
   de omzetting is een expliciete app-stap (make transport-status-omzetting). Nieuwe
   kolommen: voertuig (combi|voorwagen, toezegging transport-contact bij bevestigen) en
   transportplanner (ingevuld bij definitief maken).
3. LEVERANCIER-contactpersonen: transport-contact (bevestig-mail) en materiaal-contact
   (materiaallijst + delta-mails) op materiaal_leverancier.
4. Nieuw fijnmazig module-recht 'veldwerkerbeheer' (0019-patroon): eigen module-sleutel
   'boekhouding.veldwerkerbeheer' in platform.gebruiker_module_rol — de PK is
   (gebruiker_id, module), dus een tweede recht naast 'meerwerk_urenstaten' vergt een eigen
   sleutel (één gebruiker kan beide rechten dragen). CHECK-uitbreiding + additieve verruiming
   van platform.actor_is_module_beheerder(): de RLZ-Beheerder-bypass geldt ook voor
   'boekhouding.%'-submodules (vastgoed-semantiek en bestaand boekhouding-gedrag ongewijzigd —
   platform-fundament-uitbreiding zonder vastgoed-impact). B+P mét dit recht mag uitsluitend
   veldwerkers aanmaken/archiveren binnen de eigen scope (poorten in app/auth, besluit 31-08).

Revision ID: 0091
Revises: 0090
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0091"
down_revision: str | None = "0090"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
SCHEMA = "boekhouding"

# Spiegel van 0056: het volledige module-rollen-register voor de CHECK op gebruiker_module_rol.
MODULE_ROLLEN = {
    "vastgoed": ("superadmin", "eigenaar", "kantoor"),
    "boekhouding": ("meerwerk_urenstaten",),
    "boekhouding.veldwerkerbeheer": ("veldwerkerbeheer",),
}
MODULE_ROLLEN_VOOR_0091 = {
    "vastgoed": ("superadmin", "eigenaar", "kantoor"),
    "boekhouding": ("meerwerk_urenstaten",),
}

# actor_is_module_beheerder: additieve verruiming — de RLZ-Beheerder-bypass dekt óók de
# 'boekhouding.%'-submodules (0091); de vastgoed-tak en het gedrag voor 'boekhouding' zelf
# zijn byte-voor-byte ongewijzigd (0034-origineel).
_FUNCTIE_0091 = """
CREATE OR REPLACE FUNCTION platform.actor_is_module_beheerder(p_module text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'platform', 'pg_temp'
    AS $$
        SELECT EXISTS (
            SELECT 1 FROM platform.gebruiker_module_rol r
            WHERE r.gebruiker_id = platform.current_actor_id()
              AND r.module = p_module
              AND r.rol = CASE p_module WHEN 'vastgoed' THEN 'superadmin' ELSE NULL END
        )
        OR ((p_module = 'boekhouding' OR p_module LIKE 'boekhouding.%') AND platform.current_actor_is_beheerder())
    $$
"""
_FUNCTIE_VOOR_0091 = """
CREATE OR REPLACE FUNCTION platform.actor_is_module_beheerder(p_module text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'platform', 'pg_temp'
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

TRANSPORT_STATUSSEN = ("gereserveerd", "bevestigd", "definitief", "geleverd", "geannuleerd", "gepland")
TRANSPORT_STATUSSEN_VOOR_0091 = ("gepland", "bevestigd", "geleverd", "geannuleerd")


def _check_clausule(module_rollen: dict[str, tuple[str, ...]]) -> str:
    delen = [
        "(module = '{m}' AND rol IN ({r}))".format(m=m, r=", ".join(f"'{rol}'" for rol in rollen))
        for m, rollen in module_rollen.items()
    ]
    return " OR ".join(delen)


def _rls_append_only(tabel: str) -> None:
    """RLS per administratie (0074-patroon) mét een strengere grant: alleen SELECT + INSERT —
    de append-only-eis (wijzigen = nieuwe versie) wordt zo óók op DB-niveau afgedwongen."""
    op.execute(f"ALTER TABLE {SCHEMA}.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON {SCHEMA}.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    # --- 1. werkopdracht + dag-override (append-only) ---------------------------------------
    op.create_table(
        "werkopdracht",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("groep_id", sa.UUID(), nullable=False),
        sa.Column("versie", sa.Integer(), nullable=False),
        sa.Column("van", sa.Date(), nullable=False),
        sa.Column("tot_en_met", sa.Date(), nullable=False),
        sa.Column("tekst", sa.Text(), nullable=False),
        sa.Column("aangemaakt_door", sa.UUID(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["aangemaakt_door"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_werkopdracht_project_cache",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("groep_id", "versie", name="uq_werkopdracht_groep_versie"),
        sa.CheckConstraint("van <= tot_en_met", name="ck_werkopdracht_periode"),
        sa.CheckConstraint("length(btrim(tekst)) > 0", name="ck_werkopdracht_tekst"),
        sa.CheckConstraint("versie >= 1", name="ck_werkopdracht_versie"),
        schema=SCHEMA,
    )
    op.create_index("ix_werkopdracht_administratie_id", "werkopdracht", ["administratie_id"], schema=SCHEMA)
    op.create_index("ix_werkopdracht_project", "werkopdracht", ["administratie_id", "project_id", "van"], schema=SCHEMA)
    op.create_index("ix_werkopdracht_groep", "werkopdracht", ["administratie_id", "groep_id"], schema=SCHEMA)
    _rls_append_only("werkopdracht")

    op.create_table(
        "werkopdracht_dag",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("groep_id", sa.UUID(), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("versie", sa.Integer(), nullable=False),
        sa.Column("tekst", sa.Text(), nullable=False),
        sa.Column("aangemaakt_door", sa.UUID(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["aangemaakt_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("groep_id", "datum", "versie", name="uq_werkopdracht_dag_versie"),
        sa.CheckConstraint("length(btrim(tekst)) > 0", name="ck_werkopdracht_dag_tekst"),
        sa.CheckConstraint("versie >= 1", name="ck_werkopdracht_dag_versie"),
        schema=SCHEMA,
    )
    op.create_index("ix_werkopdracht_dag_administratie_id", "werkopdracht_dag", ["administratie_id"], schema=SCHEMA)
    op.create_index(
        "ix_werkopdracht_dag_groep", "werkopdracht_dag", ["administratie_id", "groep_id", "datum"], schema=SCHEMA
    )
    _rls_append_only("werkopdracht_dag")

    # --- 2. transport: status her-enum + voertuig/transportplanner ---------------------------
    op.drop_constraint("ck_materiaal_transport_status", "materiaal_transport", schema=SCHEMA)
    op.create_check_constraint(
        "ck_materiaal_transport_status",
        "materiaal_transport",
        "status IN ({})".format(", ".join(f"'{s}'" for s in TRANSPORT_STATUSSEN)),
        schema=SCHEMA,
    )
    op.add_column("materiaal_transport", sa.Column("voertuig", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column("materiaal_transport", sa.Column("transportplanner", sa.Text(), nullable=True), schema=SCHEMA)
    op.create_check_constraint(
        "ck_materiaal_transport_voertuig",
        "materiaal_transport",
        "voertuig IS NULL OR voertuig IN ('combi', 'voorwagen')",
        schema=SCHEMA,
    )

    # --- 3. leverancier-contactpersonen -------------------------------------------------------
    op.add_column("materiaal_leverancier", sa.Column("transport_contact_naam", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column(
        "materiaal_leverancier", sa.Column("transport_contact_email", sa.Text(), nullable=True), schema=SCHEMA
    )
    op.add_column("materiaal_leverancier", sa.Column("materiaal_contact_naam", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column(
        "materiaal_leverancier", sa.Column("materiaal_contact_email", sa.Text(), nullable=True), schema=SCHEMA
    )

    # --- 4. module-recht 'veldwerkerbeheer' (CHECK-uitbreiding, 0056-patroon) ----------------
    op.drop_constraint("ck_gebruiker_module_rol_geldig", "gebruiker_module_rol", schema="platform")
    op.create_check_constraint(
        "ck_gebruiker_module_rol_geldig",
        "gebruiker_module_rol",
        _check_clausule(MODULE_ROLLEN),
        schema="platform",
    )
    op.execute(_FUNCTIE_0091)
    # Zelf-gepoorte SECURITY DEFINER-toets (verplaats_document-patroon): is de VOLLEDIGE
    # administratie-scope van de doelgebruiker een deelverzameling van die van de actor?
    # Nodig omdat RLS een niet-Beheerder de scope-rijen van een ander búiten de eigen
    # administraties niet laat zien — zonder deze functie is containment niet toetsbaar.
    # Poorten: alleen over de eigen actor (p_actor = current_actor_id()), en fail-closed
    # (doel zonder enige scope-rij = false). Lekt uitsluitend een boolean.
    op.execute(
        """
        CREATE FUNCTION platform.veldwerker_scope_binnen_actor(p_doel uuid, p_actor uuid) RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path TO 'platform', 'pg_temp'
            AS $$
                SELECT p_actor = platform.current_actor_id()
                   AND EXISTS (SELECT 1 FROM platform.gebruiker_administratie WHERE gebruiker_id = p_doel)
                   AND NOT EXISTS (
                       SELECT 1 FROM platform.gebruiker_administratie d
                       WHERE d.gebruiker_id = p_doel
                         AND d.administratie_id NOT IN (
                             SELECT a.administratie_id FROM platform.gebruiker_administratie a
                             WHERE a.gebruiker_id = p_actor
                         )
                   )
            $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS platform.veldwerker_scope_binnen_actor(uuid, uuid)")
    op.execute(_FUNCTIE_VOOR_0091)
    op.execute("DELETE FROM platform.gebruiker_module_rol WHERE module = 'boekhouding.veldwerkerbeheer'")
    op.drop_constraint("ck_gebruiker_module_rol_geldig", "gebruiker_module_rol", schema="platform")
    op.create_check_constraint(
        "ck_gebruiker_module_rol_geldig",
        "gebruiker_module_rol",
        _check_clausule(MODULE_ROLLEN_VOOR_0091),
        schema="platform",
    )
    op.drop_column("materiaal_leverancier", "materiaal_contact_email", schema=SCHEMA)
    op.drop_column("materiaal_leverancier", "materiaal_contact_naam", schema=SCHEMA)
    op.drop_column("materiaal_leverancier", "transport_contact_email", schema=SCHEMA)
    op.drop_column("materiaal_leverancier", "transport_contact_naam", schema=SCHEMA)
    op.drop_constraint("ck_materiaal_transport_voertuig", "materiaal_transport", schema=SCHEMA)
    op.drop_column("materiaal_transport", "transportplanner", schema=SCHEMA)
    op.drop_column("materiaal_transport", "voertuig", schema=SCHEMA)
    op.drop_constraint("ck_materiaal_transport_status", "materiaal_transport", schema=SCHEMA)
    op.create_check_constraint(
        "ck_materiaal_transport_status",
        "materiaal_transport",
        "status IN ({})".format(", ".join(f"'{s}'" for s in TRANSPORT_STATUSSEN_VOOR_0091)),
        schema=SCHEMA,
    )
    op.drop_table("werkopdracht_dag", schema=SCHEMA)
    op.drop_table("werkopdracht", schema=SCHEMA)
