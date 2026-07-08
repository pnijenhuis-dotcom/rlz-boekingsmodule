"""Credential-store (besluit 0001: gedeeld platform-fundament) + koppel-flow rechten-probe.

platform.rlz_credential: webservice-login per administratie, wachtwoord versleuteld at rest
(envelope-patroon, zelfde als totp_secret) — vervangt op termijn de .env-fallback in
app/rlz/credentials.py. platform.rlz_rechten_probe: laatste read-only rechten-check per
administratie (koppel-flow onboarding).

Geen RLS op beide tabellen: toegang wordt afgedwongen op applicatieniveau (Beheerder-only
endpoints voor rlz_credential; vereis_administratie_scope voor de probe), niet via
administratie-scoping — dit zijn platformbrede beheertabellen, geen multi-tenant leesdata zoals
grootboekrekening. Geen GRANT aan vastgoed_app: beide tabellen zijn zuiver RLZ-intern.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "rlz_credential",
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("webservice_username", sa.Text(), nullable=False),
        sa.Column("wachtwoord_ciphertext", BYTEA, nullable=False),
        sa.Column("wrapped_data_key", BYTEA, nullable=False),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="platform",
    )
    # Geen DELETE: credentials worden overschreven (upsert), nooit hard verwijderd — consistent
    # met het platformbrede principe, en een administratie zonder actief contract behoudt zo zijn
    # audit-spoor in plaats van dat de rij zomaar verdwijnt.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.rlz_credential TO {APP_ROLE}")

    op.create_table(
        "rlz_rechten_probe",
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("rapport", JSONB, nullable=False),
        sa.Column("uitgevoerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("uitgevoerd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="platform",
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.rlz_rechten_probe TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.rlz_rechten_probe FROM {APP_ROLE}")
    op.drop_table("rlz_rechten_probe", schema="platform")
    op.execute(f"REVOKE ALL ON platform.rlz_credential FROM {APP_ROLE}")
    op.drop_table("rlz_credential", schema="platform")
