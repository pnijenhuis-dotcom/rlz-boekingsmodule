"""Instellingen › Administraties v2 — archiveren van een administratie (opdracht 30-08 blok A, mockup
instellingen-administraties-v2.html = bouwnorm, besluiten Peter 29-08; 0052-/0075-patroon van de
gebruikers-archivering hergebruikt):

- `platform.administratie.gearchiveerd_op` / `gearchiveerd_door`: wie heeft wanneer gearchiveerd.
  Archiveren zet daarnaast de bestaande vlag `actief` op false (álle RLZ-rakende jobs en de UI-lijsten
  filteren op `actief`), trekt de webservice-login uit de credential-store in (rij verwijderd — een
  geheim, geen boekhoudkundige data; de audit_event-rij blijft), laat documenten/historie onaangetast en
  is omkeerbaar (dearchiveren vereist een nieuwe webservice-login mét groene rechten-probe). NOOIT
  verwijderen. De registersync (§8) levert gearchiveerde rijen niet meer (verdwenen-semantiek,
  contract v1.19); niet-gearchiveerde `actief=false`-rijen blijven daar ongefilterd.
- `GRANT DELETE ON platform.rlz_credential` voor het intrekken (tot nu alleen SELECT/INSERT/UPDATE, 0006).
- Defaults `boeken_ingeschakeld`/`ai_extractie_ingeschakeld` AAN voor NIEUWE administraties zijn een
  code-default (onboarding), geen DB-default: bestaande rijen behouden hun waarde (mockup-beslispunt 1).
Schema-only, geen data-stap.

Revision ID: 0089
Revises: 0088
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.add_column(
        "administratie", sa.Column("gearchiveerd_op", sa.DateTime(timezone=True), nullable=True), schema="platform"
    )
    op.add_column(
        "administratie",
        sa.Column("gearchiveerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        schema="platform",
    )
    op.execute(f"GRANT DELETE ON platform.rlz_credential TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE DELETE ON platform.rlz_credential FROM {APP_ROLE}")
    op.drop_column("administratie", "gearchiveerd_door", schema="platform")
    op.drop_column("administratie", "gearchiveerd_op", schema="platform")
