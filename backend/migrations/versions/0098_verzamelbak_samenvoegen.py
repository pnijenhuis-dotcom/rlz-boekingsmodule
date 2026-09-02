"""Verzamelbak "Samenvoegen" (diagnose intake 02-09 punt 2, blok B4): terminale documentstatus
`samengevoegd` + `document.samengevoegd_in_id` (FK naar het leidende document). Nooit verwijderen —
beide bestanden blijven terugvindbaar; ongedaan maken zet de rij terug in de verzamelbak. Schema-only.

Revision ID: 0098
Revises: 0097
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0098"
down_revision: str | None = "0097"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE mag sinds PG12 binnen een transactie zolang de waarde niet in dezelfde
    # transactie gebruikt wordt (zelfde patroon als migraties 0016/0028).
    op.execute("ALTER TYPE boekhouding.document_status ADD VALUE IF NOT EXISTS 'samengevoegd' AFTER 'gesplitst'")
    op.add_column(
        "document",
        sa.Column("samengevoegd_in_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_document_samengevoegd_in_id",
        "document",
        ["samengevoegd_in_id"],
        schema="boekhouding",
        postgresql_where=sa.text("samengevoegd_in_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_document_samengevoegd_in_id", table_name="document", schema="boekhouding")
    op.drop_column("document", "samengevoegd_in_id", schema="boekhouding")
    # De enum-waarde blijft bewust staan (PostgreSQL kent geen DROP VALUE; zelfde keuze als 0028).
