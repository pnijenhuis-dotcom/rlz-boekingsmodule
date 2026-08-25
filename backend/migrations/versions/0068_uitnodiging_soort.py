"""Wachtwoord-herstel voor actieve externe gebruikers (RLZ-feedbackronde 25-08 deel 2, punt 7).

Gat uit de kliktest 25-08: kill-switch + wachtwoord kwijt = accordeur zit klem, want
`vernieuw_uitnodiging` weigert (terecht) een geactiveerd account een verse ACTIVATIElink. De
Beheerder krijgt daarom "Herstel-link sturen": een eenmalige 72-uurs link met exact dezelfde
token-mechaniek (hash-only opslag, één werkende link tegelijk) waarmee de gebruiker een NIEUW
wachtwoord zet en direct door kan naar apparaat-registratie — status, passkeys en akkoorden
blijven staan.

Eén kolom op platform.uitnodiging: `soort` ('uitnodiging' = activatie van een nieuw account,
'wachtwoord_herstel' = herstel van een bestaand account). De accept-flow vertakt hierop; de
gebruikerslijst kan een open herstel-link onderscheiden van een open uitnodiging. Bestaande
rijen zijn per definitie uitnodigingen (server_default). Geen selfservice "wachtwoord
vergeten" — het kantoor blijft de poortwachter (besluit Peter 25-08).

Geen nieuwe GRANTs: platform.uitnodiging heeft al SELECT/INSERT/UPDATE (0002).

Revision ID: 0068
Revises: 0067
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "uitnodiging",
        sa.Column("soort", sa.Text(), nullable=False, server_default="uitnodiging"),
        schema="platform",
    )
    op.create_check_constraint(
        "ck_uitnodiging_soort",
        "uitnodiging",
        "soort IN ('uitnodiging', 'wachtwoord_herstel')",
        schema="platform",
    )


def downgrade() -> None:
    op.drop_constraint("ck_uitnodiging_soort", "uitnodiging", schema="platform", type_="check")
    op.drop_column("uitnodiging", "soort", schema="platform")
