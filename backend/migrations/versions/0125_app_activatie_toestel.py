"""App-auth zonder passkey en TOTP — toestelbinding + activatiecode (besluit Peter 08-09-2026).

De native accordeur-/veldwerker-app en de accordeur-PWA kennen nog één toegangspad: uitnodiging → activatie op dít
toestel (link óf 8-tekens activatiecode) → 5-cijferige toegangscode (lokaal anker, bereikt de server nooit). Deze
migratie legt het datamodel daarvoor neer — schema-only, pure DDL, geen backfill:

`platform.uitnodiging`
- `activatiecode_hash` (text, NULL) + unieke index — sha256-hex van de genormaliseerde code; alleen gevuld voor
  uitnodigingen/herstel-links van externe app-rollen. Plaintext verlaat de server via mail + Beheerder-respons.
- `activatiecode_pogingen` / `activatiecode_pogingen_vanaf` — rate-limit per uitnodiging (max 5 per uur).
- `demo_herbruikbaar` (bool, default false) — UITSLUITEND het review-demo-account (seed-script): de code verloopt
  niet en mag op meerdere toestellen; de server toetst de e-mail hard (`app_activatie.REVIEW_DEMO_EMAIL`).

`platform.webauthn_credential`
- `soort` ('passkey' | 'toestel', default 'passkey') — een toestel-rij hergebruikt het apparaat-record (kill-switch,
  RefreshToken.apparaat_id, per-request-toets in deps, push-subscripties) zonder publieke sleutel (`public_key` =
  b"toestel", zelfde truc als de dev-stub).
- `platform` ('ios' | 'android' | 'web', NULL) — herkomst van het toestel.
- `niet_meer_gebruikt_op` — markering "passkey van een app-gebruiker, niet meer in gebruik" (CLI
  `app-passkeys-markeren`); nooit verwijderen, `ingetrokken_op` blijft ongemoeid.

Nieuw `platform.activatiecode_poging` — rate-limit per IP over Cloud-Run-instanties heen (5 missers per uur);
rijen ouder dan een uur worden bij elke insert opgeruimd (DELETE-grant, 0041-patroon webauthn_challenge). Geen
RLS: platform-tabel zonder administratie-scope, zelfde patroon als `uitnodiging`/`webauthn_credential`.

Revision ID: 0125
Revises: 0124
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0125"
down_revision: str | None = "0124"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    # --- uitnodiging: activatiecode + rate-limit + demo-vlag -------------------------------------
    op.add_column("uitnodiging", sa.Column("activatiecode_hash", sa.Text(), nullable=True), schema="platform")
    op.add_column(
        "uitnodiging",
        sa.Column("activatiecode_pogingen", sa.Integer(), nullable=False, server_default="0"),
        schema="platform",
    )
    op.add_column(
        "uitnodiging",
        sa.Column("activatiecode_pogingen_vanaf", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.add_column(
        "uitnodiging",
        sa.Column("demo_herbruikbaar", sa.Boolean(), nullable=False, server_default="false"),
        schema="platform",
    )
    op.create_index(
        "uq_uitnodiging_activatiecode_hash", "uitnodiging", ["activatiecode_hash"], unique=True, schema="platform"
    )

    # --- webauthn_credential: soort toestel, platform, niet-meer-gebruikt-markering --------------
    op.add_column(
        "webauthn_credential",
        sa.Column("soort", sa.Text(), nullable=False, server_default="passkey"),
        schema="platform",
    )
    op.add_column("webauthn_credential", sa.Column("platform", sa.Text(), nullable=True), schema="platform")
    op.add_column(
        "webauthn_credential",
        sa.Column("niet_meer_gebruikt_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.create_check_constraint(
        "ck_webauthn_credential_soort",
        "webauthn_credential",
        "soort IN ('passkey', 'toestel')",
        schema="platform",
    )

    # --- activatiecode_poging: rate-limit per IP ------------------------------------------------
    op.create_table(
        "activatiecode_poging",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ip", sa.Text(), nullable=False),
        sa.Column("tijdstip", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="platform",
        comment="Mislukte app-activatiepogingen per IP (rate-limit 5/uur, 08-09). Geen PII buiten het IP; "
        "rijen ouder dan een uur worden bij elke insert opgeruimd.",
    )
    op.create_index(
        "ix_activatiecode_poging_ip_tijdstip", "activatiecode_poging", ["ip", "tijdstip"], schema="platform"
    )
    op.execute(f"GRANT SELECT, INSERT, DELETE ON platform.activatiecode_poging TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.activatiecode_poging FROM {APP_ROLE}")
    op.drop_index("ix_activatiecode_poging_ip_tijdstip", table_name="activatiecode_poging", schema="platform")
    op.drop_table("activatiecode_poging", schema="platform")

    op.drop_constraint("ck_webauthn_credential_soort", "webauthn_credential", schema="platform")
    op.drop_column("webauthn_credential", "niet_meer_gebruikt_op", schema="platform")
    op.drop_column("webauthn_credential", "platform", schema="platform")
    op.drop_column("webauthn_credential", "soort", schema="platform")

    op.drop_index("uq_uitnodiging_activatiecode_hash", table_name="uitnodiging", schema="platform")
    op.drop_column("uitnodiging", "demo_herbruikbaar", schema="platform")
    op.drop_column("uitnodiging", "activatiecode_pogingen_vanaf", schema="platform")
    op.drop_column("uitnodiging", "activatiecode_pogingen", schema="platform")
    op.drop_column("uitnodiging", "activatiecode_hash", schema="platform")
