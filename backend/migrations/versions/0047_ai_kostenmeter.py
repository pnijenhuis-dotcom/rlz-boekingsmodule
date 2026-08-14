"""AI-kostenmeter (besluit Peter 2026-08-14): deterministische maandlimiet op intake-AI-kosten.

Drie tabellen, conform "code voor cijfers":

- platform.ai_gebruik — append-only log van élke Anthropic-aanroep met de wérkelijke
  token-usage uit de API-response (input/output/cache-schrijf/cache-lees), het model, de
  document-/intake-bericht-referentie en de in code berekende kosten in EUR (gepinde
  prijstabel per model × gepinde USD→EUR-koers, app/aikosten/service.py). Geen UPDATE/DELETE
  gegrant (zelfde patroon als audit_event). De `maand`-kolom (eerste dag van de kalendermaand
  in Europe/Amsterdam, in code bepaald) draagt de maandcumulatie en de harde poort.

- platform.ai_kosten_instelling — Beheerder-only singleton met de maandlimiet (default € 100,
  besluit Peter 2026-08-14), zelfde patroon als intake_instelling (0029). Elke wijziging in
  het audit_event; de env-setting `ai_kosten_maandlimiet_eur` is uitsluitend fallback als de
  rij ontbreekt.

- platform.ai_kosten_maandstatus — eenmaligheid van de meldingen: 80%-waarschuwing en
  limiet-bereikt-melding hoogstens één keer per kalendermaand.

Tweede laag (geen code): Peter zet als failsafe óók een spend-limit (~$110 bij koers 1,00) in
de Anthropic-console — zie docs/BESLISSINGEN.md "AI-kostengrens intake".

Revision ID: 0047
Revises: 0046
Create Date: 2026-08-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "ai_gebruik",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tijdstip", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("maand", sa.Date(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("bron", sa.String(), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("intake_bericht_id", UUID(as_uuid=True), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_schrijf_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_lees_tokens", sa.BigInteger(), nullable=False),
        sa.Column("kosten_eur", sa.Numeric(12, 6), nullable=False),
        sa.CheckConstraint("kosten_eur >= 0", name="ai_gebruik_kosten_niet_negatief"),
        schema="platform",
    )
    op.create_index("ix_platform_ai_gebruik_maand", "ai_gebruik", ["maand"], schema="platform")

    op.create_table(
        "ai_kosten_instelling",
        sa.Column("singleton", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("maandlimiet_eur", sa.Numeric(12, 2), nullable=False, server_default=sa.text("100")),
        sa.Column("gewijzigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("singleton", name="ai_kosten_instelling_singleton"),
        sa.CheckConstraint("maandlimiet_eur >= 0", name="ai_kosten_instelling_limiet_niet_negatief"),
        schema="platform",
    )
    op.execute("INSERT INTO platform.ai_kosten_instelling (singleton, maandlimiet_eur) VALUES (true, 100)")

    op.create_table(
        "ai_kosten_maandstatus",
        sa.Column("maand", sa.Date(), primary_key=True),
        sa.Column("waarschuwing_80_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limiet_bereikt_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )

    # ai_gebruik is append-only: bewust geen UPDATE/DELETE (zelfde patroon als audit_event).
    op.execute(f"GRANT SELECT, INSERT ON platform.ai_gebruik TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON platform.ai_kosten_instelling TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.ai_kosten_maandstatus TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.ai_kosten_maandstatus FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON platform.ai_kosten_instelling FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON platform.ai_gebruik FROM {APP_ROLE}")
    op.drop_table("ai_kosten_maandstatus", schema="platform")
    op.drop_table("ai_kosten_instelling", schema="platform")
    op.drop_index("ix_platform_ai_gebruik_maand", table_name="ai_gebruik", schema="platform")
    op.drop_table("ai_gebruik", schema="platform")
