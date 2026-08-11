"""Nazorg accordeur-PWA (2026-08-11): DELETE-grant op platform.webauthn_challenge.

Challenge-huishouding: verlopen challenge-rijen (verbruikt óf nooit gebruikt) worden bij elke
insert opgeruimd in webauthn_service._maak_challenge — daarvoor mist de app-rol het
DELETE-recht (0040 gaf bewust alleen SELECT/INSERT/UPDATE). De verruiming blijft beperkt tot
déze ene tabel: challenges zijn kortlevend werkmateriaal (TTL-seconden), geen audit-spoor —
het gebruik zelf wordt via audit_event vastgelegd. "Niets verdwijnt stil" gaat over
domeindata, niet over verlopen crypto-nonces.

Revision ID: 0041
Revises: 0040
Create Date: 2026-08-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.execute(f"GRANT DELETE ON platform.webauthn_challenge TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE DELETE ON platform.webauthn_challenge FROM {APP_ROLE}")
