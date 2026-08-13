"""Doorbelasting-spiegel-webhook (besluit Peter 2026-08-14, Platform/OPEN_ITEMS-item
doorbelasting-gaten-scan (b)): §3 geldt voor élke geboekte inkoopfactuur van een
vastgoed-administratie, óók de spiegel-inkoopfactuur die de doorbelastingsmotor búíten de
document-pipeline om in een doel-administratie boekt.

De outbox (webhook_uitgaand) scoped tot nu toe uitsluitend via het document (RLS-join +
afleveraar-query op document.administratie_id). Voor een spiegel-event klopt dat niet: het
bron-document leeft in de brón-administratie (Kempen Facilities), het event hoort bij de
dóél-administratie (bv. Rubicon). Daarom een expliciete, nullable `administratie_id`-kolom:

- NULL  = bestaand gedrag — de administratie is die van het document (inkoop/verkoop-pad);
- gevuld = de administratie waar het event over gaat (spiegel: de doel-administratie), terwijl
  `document_id` het bron-document blijft (traceerbaarheid + FK).

RLS: de bestaande document-join blijft (de bron-scope schrijft de spiegel-rij in dezelfde
transactie als de DoorbelastingBoeking), en een rij met gevulde kolom is dáárnaast zichtbaar
in de scope van die administratie (de afleveraar levert 'm onder de doel-administratie af).

Revision ID: 0046
Revises: 0045
Create Date: 2026-08-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "webhook_uitgaand",
        sa.Column(
            "administratie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.administratie.id"),
            nullable=True,
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ix_webhook_uitgaand_administratie_id",
        "webhook_uitgaand",
        ["administratie_id"],
        schema="boekhouding",
    )
    op.execute("DROP POLICY webhook_uitgaand_scope ON boekhouding.webhook_uitgaand")
    op.execute(
        """
        CREATE POLICY webhook_uitgaand_scope ON boekhouding.webhook_uitgaand
        USING (
            (
                webhook_uitgaand.administratie_id IS NOT NULL
                AND webhook_uitgaand.administratie_id = platform.current_administratie_id()
            )
            OR EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = webhook_uitgaand.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        WITH CHECK (
            (
                webhook_uitgaand.administratie_id IS NOT NULL
                AND webhook_uitgaand.administratie_id = platform.current_administratie_id()
            )
            OR EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = webhook_uitgaand.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY webhook_uitgaand_scope ON boekhouding.webhook_uitgaand")
    op.execute(
        """
        CREATE POLICY webhook_uitgaand_scope ON boekhouding.webhook_uitgaand
        USING (
            EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = webhook_uitgaand.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM boekhouding.document d
                WHERE d.id = webhook_uitgaand.document_id
                  AND (d.administratie_id IS NULL OR d.administratie_id = platform.current_administratie_id())
            )
        )
        """
    )
    op.drop_index("ix_webhook_uitgaand_administratie_id", "webhook_uitgaand", schema="boekhouding")
    op.drop_column("webhook_uitgaand", "administratie_id", schema="boekhouding")
