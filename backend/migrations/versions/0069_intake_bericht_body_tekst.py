"""Mail-body bij het intake-bericht (feedbackronde 25-08 deel 3, punt 1a).

De e-mail-intake (.eml-upload én IMAP) bewaart voortaan de platte tekst van de mail-body op
`boekhouding.intake_bericht.body_tekst` (HTML → tekst, handtekening-/disclaimer-ruis
deterministisch gestript, begrensd op 20.000 tekens — app/intake/mailbody.py). Elk document uit
die mail deelt de body via de bestaande FK `document.intake_bericht_id` (één mail met meerdere
facturen = dezelfde body bij álle documenten). Geen backfill mogelijk: van eerder verwerkte
berichten is de body niet bewaard — kolom NULL = "niet beschikbaar (bericht van vóór 0069)".

Onderdeel van het documentdossier (7 jaar, AVG-register V2). Geen nieuwe GRANTs: de app-rol
heeft op intake_bericht al SELECT/INSERT/UPDATE (0028).

Revision ID: 0069
Revises: 0068
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("intake_bericht", sa.Column("body_tekst", sa.Text(), nullable=True), schema="boekhouding")


def downgrade() -> None:
    op.drop_column("intake_bericht", "body_tekst", schema="boekhouding")
