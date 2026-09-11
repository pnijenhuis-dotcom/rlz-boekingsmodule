"""Productie-nabootsing van de functie-eigenaar (blok 1 run 11-09 middag).

De test-DB migreert als superuser `postgres`: die omzeilt élk RLS-beleid, ook onder `FORCE ROW LEVEL SECURITY`,
zodat een SECURITY DEFINER-functie in de suite altijd "werkt" — de productiebug van 0080 (Cloud SQL: eigenaar zonder
superuser/BYPASSRLS) was daardoor onzichtbaar. Deze context manager zet de functie-eigenaar tijdelijk op een rol die
precies Cloud SQL's `postgres` nabootst: lid van de migratierol (erft tabelprivileges), maar GEEN superuser en GEEN
BYPASSRLS — rol-attributen erven niet mee via lidmaatschap. Conventies §RLS punt 6: een owner-/superuser-test bewijst
RLS niet; deze wél."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text

EIGENAAR = "rls_toets_eigenaar"
VERPLAATS_FUNCTIE = "boekhouding.verplaats_document(uuid, uuid, uuid)"


def maak_eigenaar_rol(admin_engine: Engine) -> None:
    with admin_engine.begin() as conn:
        migratierol = conn.execute(text("SELECT current_user")).scalar_one()
        conn.execute(
            text(
                f"""
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{EIGENAAR}') THEN
                        CREATE ROLE {EIGENAAR} NOLOGIN;
                    END IF;
                END $$
                """
            )
        )
        conn.execute(text(f"GRANT {migratierol} TO {EIGENAAR}"))
        rij = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :r"), {"r": EIGENAAR}
        ).one()
        assert rij == (False, False), "de toetsrol mag géén superuser/BYPASSRLS zijn — anders bewijst de test niets"


@contextmanager
def productie_eigenaar(admin_engine: Engine, functie: str = VERPLAATS_FUNCTIE) -> Iterator[str]:
    """Zet de eigenaar van `functie` tijdelijk op de niet-superuser-toetsrol; herstelt in finally."""
    maak_eigenaar_rol(admin_engine)
    with admin_engine.begin() as conn:
        oude_eigenaar = conn.execute(
            text(
                "SELECT pg_get_userbyid(p.proowner) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname || '.' || p.proname = :naam"
            ),
            {"naam": functie.split("(")[0]},
        ).scalar_one()
        conn.execute(text(f"ALTER FUNCTION {functie} OWNER TO {EIGENAAR}"))
    try:
        yield EIGENAAR
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text(f"ALTER FUNCTION {functie} OWNER TO {oude_eigenaar}"))
