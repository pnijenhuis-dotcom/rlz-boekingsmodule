"""Feiten eerst (besluit Peter 17-09): SELECT-only databaserol `rlz_lezer` voor analyses op de LEESREPLICA `rlz-sql2-lees`.

Pure DDL/GRANT, geen tabellen: rol `rlz_lezer` (NOLOGIN, groepsrol) mét USAGE op `platform`, `boekhouding`, `mi`, SELECT op
álle bestaande tabellen dáár en default-privileges voor toekomstige tabellen (van de migratie-eigenaar), EXECUTE op de
RLS-hulpfuncties (`platform.current_actor_id()` e.d.) zodat een lezer mét gezette actor-GUC onder RLS leest — géén
BYPASSRLS, géén INSERT/UPDATE/DELETE, géén DDL. Rollen repliceren mee naar een Cloud SQL-leesreplica; de IAM-databasegebruiker
`nameting@rlz-boekhouding.iam` krijgt de rol via `scripts/gcp/leesreplica.sh --apply` (owner: GRANT rlz_lezer TO "…") — dat is
bewust géén onderdeel van deze migratie (de IAM-gebruiker bestaat lokaal niet). Amendement op de regel van 08-09 ("geen lokaal
proces tegen de productiedatabase"): een SELECT-only rol op een replica kan niets schrijven en is daarmee geen proces tegen
productie — zie BESLISSINGEN "FEITEN EERST — LEES-ONLY DB-/RLZ-TOEGANG VOOR ANALYSES + KLIKPUNT-GUARD (Peter 17-09)".

Revision ID: 0154
Revises: 0153
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0154"
down_revision: str | None = "0153"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LEES_ROL = "rlz_lezer"
SCHEMAS = ("platform", "boekhouding", "mi")


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{LEES_ROL}') THEN
                CREATE ROLE {LEES_ROL} NOLOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOSUPERUSER NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    for schema in SCHEMAS:
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {LEES_ROL}")
        op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {LEES_ROL}")
        op.execute(f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {LEES_ROL}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {LEES_ROL}")
    # RLS-hulpfuncties: een lezer zet `app.current_actor_id` (READ ONLY-transactie) en leest binnen de policies.
    op.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA platform TO {LEES_ROL}")


def downgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE SELECT ON TABLES FROM {LEES_ROL}")
        op.execute(f"REVOKE SELECT ON ALL SEQUENCES IN SCHEMA {schema} FROM {LEES_ROL}")
        op.execute(f"REVOKE SELECT ON ALL TABLES IN SCHEMA {schema} FROM {LEES_ROL}")
        op.execute(f"REVOKE USAGE ON SCHEMA {schema} FROM {LEES_ROL}")
    op.execute(f"REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA platform FROM {LEES_ROL}")
    # De rol is CLUSTER-breed (dev-DB + test-DB + straks primary/replica): een downgrade trekt alleen de grants in déze
    # database terug en laat de rol staan — DROP ROLE faalt zodra een andere database er nog van afhangt (test-run 17-09) en
    # is een bewuste owner-handeling, geen migratiestap.
