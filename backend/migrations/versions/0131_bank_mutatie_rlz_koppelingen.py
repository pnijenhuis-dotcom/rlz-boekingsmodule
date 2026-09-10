"""Blok 3 nachtrun 10/11-09 — deels afgeletterde bankmutaties: koppelingen uit RLZ op de mutatie-cache.

Aanleiding (bug Peter 10-09 avond, Zilver Beheer): mutatie 01-07 +5.023,09 was in RLZ al gekoppeld aan verkoopfactuur
2024840 (€ 2.512,04, RLZ-01-00000800) — open 2.511,05 — maar de module toonde, toetste en boekte het TOTAAL. Het open
bedrag (`bank_mutatie.open_bedrag`, RLZ `OpenAmount`) is sinds dit blok de maat voor voorstellen én boeken (code); deze
migratie voegt de tweede helft toe: WAARAAN de mutatie in RLZ al gekoppeld is.

`boekhouding.bank_mutatie.rlz_koppelingen JSONB NULL`: het leesspoor `PaymentReferenceList($expand=Document)` per
mutatie, systeemhulzen (DocumentType 19 + Status 1) uitgefilterd, per koppeling
`{document_id, boekstuknummer, referentie, bedrag, document_type, omschrijving}`. NULL = leesspoor nog niet gelezen
(de incrementele lijst-GET van de sync expandeert het niet; de verversronde over lokaal-open mutaties wél).
Cache-kolom (RLZ blijft de bron van waarheid) — de sync overschrijft 'm bij elke verversing.

Schema-only (pure DDL); de vulling komt vanzelf met de eerstvolgende bank-sync (verversronde), geen backfill nodig.

Revision ID: 0131
Revises: 0130
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0131"
down_revision: str | None = "0130"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bank_mutatie",
        sa.Column("rlz_koppelingen", JSONB(astext_type=sa.Text()), nullable=True),
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_column("bank_mutatie", "rlz_koppelingen", schema="boekhouding")
