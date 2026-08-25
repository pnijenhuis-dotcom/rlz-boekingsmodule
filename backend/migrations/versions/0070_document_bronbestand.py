"""Origineel brondocument naast de omgezette PDF (feedbackronde 25-08 deel 3, punt 2).

Afbeeldingen (JPEG/PNG/HEIC) worden bij binnenkomst deterministisch naar PDF omgezet zodat de
keten uniform PDF blijft; het origineel blijft als brondocument bewaard. Drie nullable kolommen op
`boekhouding.document`: `bron_opslag_pad` (sleutel in de documentopslag), `bron_bestandsnaam`
(zoals aangeleverd, bv. IMG_0412.HEIC) en `bron_content_type`. NULL = het opgeslagen bestand ís
het origineel (PDF/UBL, of een onbruikbare afbeelding die zelf in de verzamelbak ligt).

Geen nieuwe GRANTs (document heeft al SELECT/INSERT/UPDATE voor de app-rol, 0002/0003).

Revision ID: 0070
Revises: 0069
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document", sa.Column("bron_opslag_pad", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column("document", sa.Column("bron_bestandsnaam", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column("document", sa.Column("bron_content_type", sa.Text(), nullable=True), schema="boekhouding")


def downgrade() -> None:
    op.drop_column("document", "bron_content_type", schema="boekhouding")
    op.drop_column("document", "bron_bestandsnaam", schema="boekhouding")
    op.drop_column("document", "bron_opslag_pad", schema="boekhouding")
