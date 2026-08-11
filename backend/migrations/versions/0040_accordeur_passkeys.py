"""Accordeur-PWA blok 1: passkeys (WebAuthn) + device-cadans + kill-switch + voorwaarden-akkoord.

Besluiten Peter 2026-08-11 (BESLISSINGEN "Mobiele bouwstenen accordeur-PWA" punt 2, herzien):
volledige login alléén bij eerste gebruik / nieuw apparaat / ná 7 dagen inactiviteit;
passkey-assertion één keer per app-opening; kantoor-kill-switch per accordeur/apparaat.

- `webauthn_credential`: publieke sleutel per GEBRUIKER+APPARAAT (device-registratie) — draagt
  meteen nieuw/onbekend-apparaat-detectie én de kill-switch (`ingetrokken_op`). `is_dev_stub`
  markeert de expliciete dev-fallback (auth_biometrie_dev_stub, alleen buiten productie —
  WebAuthn vereist een secure context, dus op een LAN-IP-kliktest is er geen echte passkey).
- `webauthn_challenge`: server-side éénmalige challenges (registratie/assertie) — nooit een
  challenge uit de client vertrouwen, en een challenge is na gebruik verbrand (replay).
- `refresh_token.apparaat_id`: bindt de sessie aan het geregistreerde apparaat; de kill-switch
  trekt credential + alle gebonden refresh-tokens in één klap in.
- `accordeur_akkoord`: vastlegging voorwaarden + privacyverklaring-akkoord (wie/wanneer/
  tekstversie — docs/avg/05 bijlage A; informatielaag, geen AVG-vervanging). Append-only.
- `gebruiker_status` krijgt 'wacht_op_passkey': de accordeur-activeringsflow vervangt de
  TOTP-stap door passkey-registratie (de passkey ís de tweede factor op het apparaat).

Platform-breed, niet administratie-gebonden (zelfde categorie als refresh_token/totp_secret)
-> geen RLS, conform migratie 0003.

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    # PG >= 12: ADD VALUE mag binnen een transactie zolang de waarde niet in dezelfde
    # transactie gebruikt wordt — deze migratie is schema-only, dus dat is geborgd.
    op.execute("ALTER TYPE platform.gebruiker_status ADD VALUE IF NOT EXISTS 'wacht_op_passkey'")

    op.create_table(
        "webauthn_credential",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        # WebAuthn credential-id (raw bytes) — uniek over het hele platform, zo detecteren we
        # ook een credential die per ongeluk bij twee accounts geregistreerd zou worden.
        sa.Column("credential_id", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("aaguid", sa.Text(), nullable=True),
        sa.Column("transports", JSONB(), nullable=True),
        sa.Column("apparaat_naam", sa.Text(), nullable=True),
        sa.Column("is_dev_stub", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("laatst_gebruikt_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingetrokken_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingetrokken_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True
        ),
        schema="platform",
    )
    op.create_index(
        "ix_webauthn_credential_gebruiker_id", "webauthn_credential", ["gebruiker_id"], schema="platform"
    )

    op.create_table(
        "webauthn_challenge",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("soort", sa.Text(), nullable=False),  # 'registratie' | 'assertie'
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verloopt_op", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gebruikt_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("soort IN ('registratie', 'assertie')", name="ck_webauthn_challenge_soort"),
        schema="platform",
    )
    op.create_index(
        "ix_webauthn_challenge_gebruiker_id", "webauthn_challenge", ["gebruiker_id"], schema="platform"
    )

    op.add_column(
        "refresh_token",
        sa.Column(
            "apparaat_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.webauthn_credential.id"),
            nullable=True,
        ),
        schema="platform",
    )
    op.create_index("ix_refresh_token_apparaat_id", "refresh_token", ["apparaat_id"], schema="platform")

    op.create_table(
        "accordeur_akkoord",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("tekst_versie", sa.Text(), nullable=False),
        sa.Column("akkoord_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Eén akkoord per gebruiker per tekstversie — een nieuwe tekstversie vraagt een nieuw
        # akkoord, een dubbele POST is idempotent af te vangen.
        sa.UniqueConstraint("gebruiker_id", "tekst_versie", name="uq_accordeur_akkoord_versie"),
        schema="platform",
    )

    # Append-only voor het akkoord (geen UPDATE/DELETE — intrekken bestaat niet, een nieuwe
    # tekstversie vraagt gewoon een nieuw akkoord); challenges hebben UPDATE nodig
    # (gebruikt_op = verbrand), credentials voor sign_count/laatst_gebruikt_op/kill-switch.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.webauthn_credential TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.webauthn_challenge TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON platform.accordeur_akkoord TO {APP_ROLE}")


def downgrade() -> None:
    # NB: de enum-waarde 'wacht_op_passkey' blijft staan (ALTER TYPE ... DROP VALUE bestaat
    # niet); onschadelijk zolang geen rij 'm draagt.
    op.execute(f"REVOKE ALL ON platform.accordeur_akkoord FROM {APP_ROLE}")
    op.drop_table("accordeur_akkoord", schema="platform")
    op.drop_index("ix_refresh_token_apparaat_id", table_name="refresh_token", schema="platform")
    op.drop_column("refresh_token", "apparaat_id", schema="platform")
    op.execute(f"REVOKE ALL ON platform.webauthn_challenge FROM {APP_ROLE}")
    op.drop_table("webauthn_challenge", schema="platform")
    op.execute(f"REVOKE ALL ON platform.webauthn_credential FROM {APP_ROLE}")
    op.drop_table("webauthn_credential", schema="platform")
