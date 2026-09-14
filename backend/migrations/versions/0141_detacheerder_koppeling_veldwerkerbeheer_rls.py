"""Veldwerkers-run 14-09 — RLS op platform.detacheerder_koppeling óók voor houders van 'veldwerkerbeheer'.

Aanleiding (besluiten Peter 14-09 punt 1+2): een kantoormedewerker mét het recht 'veldwerkerbeheer' mag sinds 14-09
detacheerders aan ZZP'ers koppelen (incl. bureau-tarief). De router-poort verbreden is niet genoeg: de policies uit
0056/0057 laten uitsluitend een Beheerder (of de detacheerder zelf, of de systeem-actor) op deze persoonsniveau-tabel —
een rechthouder zou nul rijen zien en op INSERT/UPDATE/DELETE een RLS-weigering krijgen: een stille no-op (kernprincipe
7.6). Daarom hier de ENIGE schema-wijziging van de run:

- `platform.current_actor_heeft_veldwerkerbeheer()` — SECURITY DEFINER (zelfde patroon als actor_is_module_beheerder,
  0034/0091): true als de huidige actor een ACTIEVE kantoorrol is mét de rij ('boekhouding.veldwerkerbeheer',
  'veldwerkerbeheer') in gebruiker_module_rol. Lekt uitsluitend een boolean; externe rollen nooit.
- de vier policies op platform.detacheerder_koppeling (lees / toevoegen / muteren / verwijderen) krijgen
  `OR platform.current_actor_heeft_veldwerkerbeheer()`. De scope-begrenzing (beide veldwerkers binnen de scope van de
  actor) blijft server-side in de router (`_toets_scope_veldwerker` → `platform.veldwerker_scope_binnen_actor`).

De administratie-gebonden tabellen (veldwerker_crediteur, uren_project_toewijzing, dossier) zijn al op administratie
gescoped en vergen geen wijziging. Schema-only (DDL), geen data.

Revision ID: 0141
Revises: 0140
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0141"
down_revision: str | None = "0140"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
SYSTEEM_ACTOR_ID = "00000000-0000-0000-0000-000000000001"

FUNCTIE = """
CREATE OR REPLACE FUNCTION platform.current_actor_heeft_veldwerkerbeheer() RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'platform', 'pg_temp'
    AS $$
        SELECT EXISTS (
            SELECT 1
            FROM platform.gebruiker_module_rol r
            JOIN platform.gebruiker g ON g.id = r.gebruiker_id
            WHERE r.gebruiker_id = platform.current_actor_id()
              AND r.module = 'boekhouding.veldwerkerbeheer'
              AND r.rol = 'veldwerkerbeheer'
              AND g.status = 'actief'
              AND g.rol IN ('beheerder', 'boekhouding_projecten', 'boekhouding')
        )
    $$
"""

_RECHTHOUDER = "(platform.current_actor_is_beheerder() OR platform.current_actor_heeft_veldwerkerbeheer())"


def _policies(rechthouder: str) -> list[str]:
    return [
        "DROP POLICY IF EXISTS detacheerder_koppeling_lees ON platform.detacheerder_koppeling",
        f"""
        CREATE POLICY detacheerder_koppeling_lees ON platform.detacheerder_koppeling
        FOR SELECT USING (
            detacheerder_gebruiker_id = platform.current_actor_id()
            OR {rechthouder}
            OR platform.current_actor_id() = '{SYSTEEM_ACTOR_ID}'
        )
        """,
        "DROP POLICY IF EXISTS detacheerder_koppeling_toevoegen ON platform.detacheerder_koppeling",
        f"""
        CREATE POLICY detacheerder_koppeling_toevoegen ON platform.detacheerder_koppeling
        FOR INSERT WITH CHECK ({rechthouder})
        """,
        "DROP POLICY IF EXISTS detacheerder_koppeling_muteren ON platform.detacheerder_koppeling",
        f"""
        CREATE POLICY detacheerder_koppeling_muteren ON platform.detacheerder_koppeling
        FOR UPDATE USING ({rechthouder}) WITH CHECK ({rechthouder})
        """,
        "DROP POLICY IF EXISTS detacheerder_koppeling_verwijderen ON platform.detacheerder_koppeling",
        f"""
        CREATE POLICY detacheerder_koppeling_verwijderen ON platform.detacheerder_koppeling
        FOR DELETE USING ({rechthouder})
        """,
    ]


def upgrade() -> None:
    op.execute(FUNCTIE)
    op.execute(f"GRANT EXECUTE ON FUNCTION platform.current_actor_heeft_veldwerkerbeheer() TO {APP_ROLE}")
    for sql in _policies(_RECHTHOUDER):
        op.execute(sql)


def downgrade() -> None:
    for sql in _policies("platform.current_actor_is_beheerder()"):
        op.execute(sql)
    op.execute(f"REVOKE EXECUTE ON FUNCTION platform.current_actor_heeft_veldwerkerbeheer() FROM {APP_ROLE}")
    op.execute("DROP FUNCTION IF EXISTS platform.current_actor_heeft_veldwerkerbeheer()")
