"""Maandagochtend-digest kantoor (best-practice-punt D2, 01-09): `platform.kantoor_digest` (één rij per
kantoormedewerker × ISO-week, claim-vóór-verzenden, unique → nooit dubbel) + `platform.gebruiker.digest_opt_out`
(opt-out per gebruiker, default mee). Alleen aangemaakt als er iets te melden was. Schema-only.

Revision ID: 0097
Revises: 0096
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0097"
down_revision: str | None = "0096"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.add_column(
        "gebruiker",
        sa.Column("digest_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )
    op.create_table(
        "kantoor_digest",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("iso_week", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="bezig"),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verzonden_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", JSONB(), nullable=True),
        sa.UniqueConstraint("gebruiker_id", "iso_week", name="uq_kantoor_digest_week"),
        schema="platform",
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.kantoor_digest TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.kantoor_digest FROM {APP_ROLE}")
    op.drop_table("kantoor_digest", schema="platform")
    op.drop_column("gebruiker", "digest_opt_out", schema="platform")
