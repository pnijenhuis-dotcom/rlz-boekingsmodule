"""Native app — live updates (OTA) van de web-laag + minimum-versie-poort (besluit Peter 16-09: "zsm af van TestFlight, de
native app moet gewoon werken"). Schema-only, pure DDL:
`platform.app_bundel` — register van OTA-webbundels: `bundel_id` (uniek, git-sha + bouwmoment = `VITE_BUILD_ID`), `runtime`
  (de marketingversie van de schil waarvoor de bundel gebouwd is — een 1.1-schil krijgt nooit een 1.2-bundel), `platform`
  ('ios' | 'android' | 'alle'), `pad` (objectsleutel in de bundel-bucket), `sha256`, `bytes`, `verplicht` (direct toepassen),
  `actief` (deactiveren = terugtrekken, nooit verwijderen), wie/wanneer. Gevuld door de deploy-workflow via de CLI
  `app-bundel-registreren` op de job-image.
`platform.app_update_instelling` — singleton (Beheerder, Instellingen › Boeken › App-updates): `percentage` (cohort-uitrol,
  default 100), `uitgeschakeld` (kill-switch in de DB náást de env `OTA_UITGESCHAKELD`), wie/wanneer. Eén rij geseed.
`platform.webauthn_credential` + `app_versie`, `bundel_id`, `bundel_gezien_op` — wat het toestel bij zijn laatste request
  meldde (headers X-App-Versie / X-Bundel-Id), voor het Beheerder-blok "laatste toestellen mét bundel".
Geen RLS: platform-tabellen zonder administratie-scope (patroon uitnodiging/webauthn_credential).

Revision ID: 0152
Revises: 0151
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0152"
down_revision: str | None = "0151"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "app_bundel",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("bundel_id", sa.Text(), nullable=False),
        sa.Column("runtime", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), server_default="alle", nullable=False),
        sa.Column("pad", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("verplicht", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("actief", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("aangemaakt_door", sa.UUID(), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("bundel_id", name="uq_app_bundel_bundel_id"),
        sa.CheckConstraint("platform IN ('ios', 'android', 'alle')", name="ck_app_bundel_platform"),
        schema="platform",
    )
    op.create_index("ix_app_bundel_runtime_aangemaakt", "app_bundel", ["runtime", "aangemaakt_op"], schema="platform")
    op.create_table(
        "app_update_instelling",
        sa.Column("singleton", sa.Boolean(), primary_key=True),
        sa.Column("percentage", sa.Integer(), server_default="100", nullable=False),
        sa.Column("uitgeschakeld", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("gewijzigd_door", sa.UUID(), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("singleton", name="ck_app_update_instelling_singleton"),
        sa.CheckConstraint("percentage BETWEEN 0 AND 100", name="ck_app_update_instelling_percentage"),
        schema="platform",
    )
    op.execute("INSERT INTO platform.app_update_instelling (singleton) VALUES (true)")
    op.add_column("webauthn_credential", sa.Column("app_versie", sa.Text(), nullable=True), schema="platform")
    op.add_column("webauthn_credential", sa.Column("bundel_id", sa.Text(), nullable=True), schema="platform")
    op.add_column(
        "webauthn_credential", sa.Column("bundel_gezien_op", sa.DateTime(timezone=True), nullable=True), schema="platform"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.app_bundel TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON platform.app_update_instelling TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_column("webauthn_credential", "bundel_gezien_op", schema="platform")
    op.drop_column("webauthn_credential", "bundel_id", schema="platform")
    op.drop_column("webauthn_credential", "app_versie", schema="platform")
    op.drop_table("app_update_instelling", schema="platform")
    op.drop_index("ix_app_bundel_runtime_aangemaakt", table_name="app_bundel", schema="platform")
    op.drop_table("app_bundel", schema="platform")
