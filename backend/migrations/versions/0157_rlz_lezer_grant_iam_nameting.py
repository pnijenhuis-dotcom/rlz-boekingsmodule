"""Leesreplica afronden (17-09, opdracht "leesreplica-afronden"): de IAM-databasegebruiker `nameting@rlz-boekhouding.iam`
krijgt de SELECT-only rol `rlz_lezer` (migratie 0154) — als MIGRATIE i.p.v. een owner-handeling in een terminal ("geen
Terminal-werk voor Peter meer"). Voorwaardelijk en idempotent: bestaat de IAM-rol niet in dit cluster (lokale dev-/test-DB,
of een primary zonder IAM-gebruiker), dan een NOTICE en niets doen — nooit falen op een omgeving zonder replica. Rollen en
grants repliceren mee naar `rlz-sql2-lees`. Downgrade = REVOKE onder dezelfde voorwaarde. Pure DDL/GRANT, geen tabellen.

Revision ID: 0157
Revises: 0156
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0157"
down_revision: str | None = "0156"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LEES_ROL = "rlz_lezer"
IAM_GEBRUIKER = "nameting@rlz-boekhouding.iam"


def _voorwaardelijk(actie: str) -> str:
    return f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{IAM_GEBRUIKER}')
               AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{LEES_ROL}') THEN
                EXECUTE '{actie} {LEES_ROL} {{richting}} "{IAM_GEBRUIKER}"';
            ELSE
                RAISE NOTICE 'IAM-rol {IAM_GEBRUIKER} of rol {LEES_ROL} ontbreekt in dit cluster — {actie} overgeslagen (geen replica-omgeving)';
            END IF;
        END
        $$;
    """


def upgrade() -> None:
    op.execute(_voorwaardelijk("GRANT").replace("{richting}", "TO"))


def downgrade() -> None:
    op.execute(_voorwaardelijk("REVOKE").replace("{richting}", "FROM"))
