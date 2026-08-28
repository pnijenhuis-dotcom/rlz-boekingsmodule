"""Atomaire activatie externe app-rollen (besluit Peter 28-08, mockup activatie-mobiel.html —
casus Haci: wachtwoord gezet op een pc zónder passkey-support → account half geactiveerd).

platform.uitnodiging.wachtwoord_hash_in_wacht: de wachtwoordstap van een EXTERNE gebruiker
(klant-accordeur/veldrol) parkeert de hash op de uitnodigings- of herstel-rij i.p.v. 'm op de
gebruiker te zetten; pas de geslaagde passkey-registratie (zelfde transactie) kopieert de hash
naar `gebruiker.wachtwoord_hash`, activeert het account en verbruikt de link. Mislukt de passkey,
dan is er niets half geregistreerd en blijft de link 72 u verzilverbaar. Kantoor-rollen
(wachtwoord + TOTP) ongewijzigd. Schema-only.

Revision ID: 0083
Revises: 0082
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "uitnodiging",
        sa.Column("wachtwoord_hash_in_wacht", sa.Text(), nullable=True),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("uitnodiging", "wachtwoord_hash_in_wacht", schema="platform")
