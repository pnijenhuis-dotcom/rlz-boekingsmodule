"""Gebruiker blokkeren/heractiveren (beheer-mini, opdracht 2026-08-16).

De status `geblokkeerd` bestond al in de enum en wordt op álle login-/sessiepaden afgedwongen
(deps per request, refresh-rotatie, wachtwoord+TOTP én alle WebAuthn-paden) — wat ontbrak was
de beheeractie zelf. Drie kolommen op platform.gebruiker:

- geblokkeerd_op / geblokkeerd_door: wie heeft wanneer geblokkeerd (zichtbaar op
  Gebruikers & toegang; de audit_event-rij blijft de append-only bron).
- status_voor_blokkade: de status van vóór de blokkade, zodat heractiveren een gebruiker
  die nog midden in de activatie zat (uitgenodigd/wacht_op_totp/wacht_op_passkey) exact
  daarheen terugzet — nooit naar 'actief' zonder credentials.

Geen nieuwe GRANTs nodig: platform.gebruiker heeft al SELECT/INSERT/UPDATE (0001).

Revision ID: 0052
Revises: 0051
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "gebruiker",
        sa.Column("geblokkeerd_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.add_column(
        "gebruiker",
        sa.Column(
            "geblokkeerd_door",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("platform.gebruiker.id"),
            nullable=True,
        ),
        schema="platform",
    )
    op.add_column(
        "gebruiker",
        sa.Column("status_voor_blokkade", sa.Text(), nullable=True),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("gebruiker", "status_voor_blokkade", schema="platform")
    op.drop_column("gebruiker", "geblokkeerd_door", schema="platform")
    op.drop_column("gebruiker", "geblokkeerd_op", schema="platform")
