"""Gebruiker archiveren/dearchiveren (feedbackronde 26-08 punt 1, besluit Peter 26-08).

Nieuwe status `gearchiveerd` naast `geblokkeerd` (0052-patroon hergebruikt): toegang per direct
dicht op álle paden (alle poorten toetsen `status == actief` — een gearchiveerde valt daar
automatisch buiten; sessies/refresh worden bij archiveren ingetrokken, passkeys blijven
geregistreerd maar zijn onbruikbaar), uit álle default-lijsten en tabs (op /gebruikers per tab
terug te vinden via het filter "gearchiveerd (N)"), historie/audit/akkoord-sporen onaangetast —
er wordt niets verwijderd. Dearchiveren zet exact de status van vóór archivering terug
(`status_voor_archivering`, óók 'geblokkeerd' als dat zo was).

Drie kolommen op platform.gebruiker, spiegel van 0052:
- gearchiveerd_op / gearchiveerd_door: wie heeft wanneer gearchiveerd (zichtbaar in de UI; de
  audit_event-rij blijft de append-only bron).
- status_voor_archivering: TEXT, status van vóór de archivering.

PG >= 12: ADD VALUE mag binnen een transactie zolang de waarde niet in dezelfde transactie
gebruikt wordt — deze migratie is schema-only (patroon 0040). Geen nieuwe GRANTs nodig
(platform.gebruiker heeft al SELECT/INSERT/UPDATE, 0001).

Revision ID: 0075
Revises: 0074
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE platform.gebruiker_status ADD VALUE IF NOT EXISTS 'gearchiveerd'")
    op.add_column(
        "gebruiker",
        sa.Column("gearchiveerd_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.add_column(
        "gebruiker",
        sa.Column(
            "gearchiveerd_door",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("platform.gebruiker.id"),
            nullable=True,
        ),
        schema="platform",
    )
    op.add_column(
        "gebruiker",
        sa.Column("status_voor_archivering", sa.Text(), nullable=True),
        schema="platform",
    )


def downgrade() -> None:
    # Een enum-waarde verwijderen kan PostgreSQL niet; de kolommen wel.
    op.drop_column("gebruiker", "status_voor_archivering", schema="platform")
    op.drop_column("gebruiker", "gearchiveerd_door", schema="platform")
    op.drop_column("gebruiker", "gearchiveerd_op", schema="platform")
