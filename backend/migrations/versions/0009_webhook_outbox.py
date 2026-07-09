"""Webhook-stub "factuur geboekt" (koppelcontract §3, CLAUDE.md-taak 2.5): outbox-tabel zodat de
getekende payload (HMAC/timestamp/nonce/schema_version) bij elke boeking al vastligt, ook al
staat de daadwerkelijke aflevering (HTTP-push naar vastgoed) nog uit — "niets verdwijnt stil"
geldt ook voor een event dat nog niet afgeleverd is. `afgeleverd_op` blijft NULL totdat een
latere sessie de aflevering bouwt; deze migratie voegt geen achtergrondjob toe.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "webhook_uitgaand",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("afgeleverd_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_index("ix_webhook_uitgaand_document_id", "webhook_uitgaand", ["document_id"], schema="boekhouding")
    op.create_index(
        "ix_webhook_uitgaand_onafgeleverd",
        "webhook_uitgaand",
        ["afgeleverd_op"],
        schema="boekhouding",
        postgresql_where=sa.text("afgeleverd_op IS NULL"),
    )

    op.execute("ALTER TABLE boekhouding.webhook_uitgaand ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.webhook_uitgaand FORCE ROW LEVEL SECURITY")
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
    # Append-only vanaf de app-kant (net als document_gebeurtenis/audit_event) — een latere
    # aflevering-job zet UPDATE afgeleverd_op, dus UPDATE blijft gegrant i.t.t. audit_event.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.webhook_uitgaand TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.webhook_uitgaand FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS webhook_uitgaand_scope ON boekhouding.webhook_uitgaand")
    op.drop_table("webhook_uitgaand", schema="boekhouding")
