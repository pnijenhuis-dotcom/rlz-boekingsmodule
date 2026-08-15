"""Berichten-bouwsteen (accordeur-notificaties): push-subscripties + herinnering-idempotentielog.

- `push_subscriptie`: Web-Push-subscriptie per GEBRUIKER+APPARAAT, gebonden aan de bestaande
  apparaten-administratie (webauthn_credential, migratie 0040) zodat de kantoor-kill-switch die
  een apparaat intrekt óók de push-subscripties van dat apparaat intrekt — nooit een pushkanaal
  dat een ingetrokken apparaat overleeft.
- `accordeur_herinnering`: idempotentie-log van de dagelijkse 09:00-herinnering (mockup-besluit
  "dagelijkse push 09:00 alleen bij >0 open") — unique (gebruiker_id, datum): een herhaalde
  job-run mag nooit dubbel sturen.

Platform-breed (gebruiker-gebonden, niet administratie-gebonden) -> geen RLS, conform
migratie 0003/0040.

Revision ID: 0050
Revises: 0049
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "push_subscriptie",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column(
            "apparaat_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.webauthn_credential.id"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("laatst_gebruikt_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingetrokken_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingetrokken_reden", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "ingetrokken_reden IS NULL OR ingetrokken_reden IN ('gebruiker', 'kill_switch', 'vervallen')",
            name="ck_push_subscriptie_reden",
        ),
        schema="platform",
    )
    op.create_index("ix_push_subscriptie_gebruiker_id", "push_subscriptie", ["gebruiker_id"], schema="platform")
    op.create_index("ix_push_subscriptie_apparaat_id", "push_subscriptie", ["apparaat_id"], schema="platform")

    op.create_table(
        "accordeur_herinnering",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("aantal_open", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="bezig"),
        sa.Column("kanaal", sa.Text(), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verzonden_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", JSONB(), nullable=True),
        sa.CheckConstraint(
            "status IN ('bezig', 'verzonden', 'mislukt', 'overgeslagen')",
            name="ck_accordeur_herinnering_status",
        ),
        sa.CheckConstraint(
            "kanaal IS NULL OR kanaal IN ('push', 'e-mail')", name="ck_accordeur_herinnering_kanaal"
        ),
        sa.UniqueConstraint("gebruiker_id", "datum", name="uq_accordeur_herinnering_dag"),
        schema="platform",
    )

    # Subscripties: UPDATE nodig voor intrekken/laatst_gebruikt_op; herinneringen: UPDATE voor
    # de statusovergang bezig -> verzonden/mislukt/overgeslagen. Nooit DELETE (niets verdwijnt
    # stil — intrekken is een status, geen verwijdering).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.push_subscriptie TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.accordeur_herinnering TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.accordeur_herinnering FROM {APP_ROLE}")
    op.drop_table("accordeur_herinnering", schema="platform")
    op.execute(f"REVOKE ALL ON platform.push_subscriptie FROM {APP_ROLE}")
    op.drop_index("ix_push_subscriptie_apparaat_id", table_name="push_subscriptie", schema="platform")
    op.drop_index("ix_push_subscriptie_gebruiker_id", table_name="push_subscriptie", schema="platform")
    op.drop_table("push_subscriptie", schema="platform")
