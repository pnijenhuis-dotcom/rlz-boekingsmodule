"""Blok B bundel 10-09 — bank historie-regel + AI-plausibiliteitstoets als poort (besluit Peter 10-09).

1. `boekhouding.bank_mutatie`: vier werkstaat-kolommen voor de AI-plausibiliteitstoets (uitkomst/reden/moment/
   invoer-hash) — de toets die vóór élke automatische bankboeking (vaste regel én historie-regel) loopt;
   twijfel = mutatie blijft open mét de reden als chip.
2. `boekhouding.bank_historie_boeking`: cache van eerdere direct-op-grootboek-boekingen (RLZ-historie via de
   PaymentReferenceList + eigen bank_boeking) — de bron van de historie-regel (IBAN + omschrijvingskern, ≥ 6
   maanden, ≥ 3 boekingen, 100 % = automatisch kandidaat). Uniek per (administratie, mutatie, rekening) mét
   NULL-rekening voor markeringsrijen; RLS 0071-patroon; GRANT zonder DELETE.
3. `platform.boeken_instelling.ai_toets_facturen_ingeschakeld` (default true): dezelfde toets als optionele
   extra poort op factuur-autoboekingen, platformbreed (Beheerder, Instellingen › Boeken).

Schema-only (pure DDL) — de eerste vulling van de historie-cache is de CLI `bank-historie-backfill`.

Revision ID: 0129
Revises: 0128
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0129"
down_revision: str | None = "0128"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def _rls(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    # 1. AI-toets-werkstaat op de bankmutatie (de sync raakt deze kolommen niet aan).
    op.add_column("bank_mutatie", sa.Column("ai_toets_uitkomst", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column("bank_mutatie", sa.Column("ai_toets_reden", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column(
        "bank_mutatie", sa.Column("ai_toets_op", sa.DateTime(timezone=True), nullable=True), schema="boekhouding"
    )
    op.add_column("bank_mutatie", sa.Column("ai_toets_invoer_hash", sa.Text(), nullable=True), schema="boekhouding")

    # 2. Historie-cache.
    op.create_table(
        "bank_historie_boeking",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("payment_transaction_id", sa.UUID(), nullable=False),
        sa.Column("datum", sa.Date(), nullable=True),
        sa.Column("tegenrekening_iban", sa.Text(), nullable=True),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        sa.Column("tegenpartij_naam", sa.Text(), nullable=True),
        sa.Column("ledger_id", sa.UUID(), nullable=True),
        sa.Column("taxrate_id", sa.UUID(), nullable=True),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("gelezen_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_bank_historie_boeking_administratie_id",
        "bank_historie_boeking",
        ["administratie_id"],
        schema="boekhouding",
    )
    op.create_index(
        "ux_bank_historie_boeking_per_mutatie_rekening",
        "bank_historie_boeking",
        [
            "administratie_id",
            "payment_transaction_id",
            sa.text("COALESCE(ledger_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
        ],
        unique=True,
        schema="boekhouding",
    )
    _rls("bank_historie_boeking")

    # 3. Platformbrede schakelaar op de bestaande singleton.
    op.add_column(
        "boeken_instelling",
        sa.Column("ai_toets_facturen_ingeschakeld", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("boeken_instelling", "ai_toets_facturen_ingeschakeld", schema="platform")
    op.drop_index(
        "ux_bank_historie_boeking_per_mutatie_rekening", table_name="bank_historie_boeking", schema="boekhouding"
    )
    op.drop_index("ix_bank_historie_boeking_administratie_id", table_name="bank_historie_boeking", schema="boekhouding")
    op.drop_table("bank_historie_boeking", schema="boekhouding")
    op.drop_column("bank_mutatie", "ai_toets_invoer_hash", schema="boekhouding")
    op.drop_column("bank_mutatie", "ai_toets_op", schema="boekhouding")
    op.drop_column("bank_mutatie", "ai_toets_reden", schema="boekhouding")
    op.drop_column("bank_mutatie", "ai_toets_uitkomst", schema="boekhouding")
