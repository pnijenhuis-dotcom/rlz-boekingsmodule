"""Revocable refresh-tokens (Auth-0010-b punt 1): server-side token-hash-tabel i.p.v. stateless
JWT, zodat rotatie en hergebruik-detectie mogelijk zijn (intrekken van alle sessies van een
gebruiker kon tot nu toe niet — een refresh-JWT bleef geldig tot zijn 30-dagen-exp).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    # Platform-breed, niet administratie-gebonden (zelfde categorie als uitnodiging/totp_secret)
    # -> geen RLS-policy nodig, conform de bestaande twee tabellen.
    op.create_table(
        "refresh_token",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("voorganger_id", UUID(as_uuid=True), sa.ForeignKey("platform.refresh_token.id"), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verloopt_op", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gebruikt_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingetrokken_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.create_index("ix_refresh_token_gebruiker_id", "refresh_token", ["gebruiker_id"], schema="platform")

    # UPDATE nodig voor rotatie (gebruikt_op) en hergebruik-detectie (ingetrokken_op); geen DELETE
    # — rijen blijven staan als sessiegeschiedenis, net als uitnodiging/totp_secret.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.refresh_token TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.refresh_token FROM {APP_ROLE}")
    op.drop_table("refresh_token", schema="platform")
