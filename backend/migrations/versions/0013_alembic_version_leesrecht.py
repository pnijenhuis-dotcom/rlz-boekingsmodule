"""Migratie-guard bij startup (app/db/migratie_guard.py): de app draait met de least-privilege
`boekhouding_app`-rol (app_database_url), die tot nu toe geen rechten had op `alembic_version` —
zonder GRANT zou de startup-guard altijd een permission-fout geven in plaats van de bedoelde
duidelijke "database loopt achter"-melding. Alleen SELECT: de guard leest, migreert nooit.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.execute(f"GRANT SELECT ON public.alembic_version TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON public.alembic_version FROM {APP_ROLE}")
