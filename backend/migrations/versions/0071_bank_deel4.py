"""Bank-verdieping feedbackronde 25-08 deel 4 (punten 2, 3, 4).

- `bank_sync_run`: achtergrond-verversing bij het openen van het bankscherm (cijfers-sync-
  patroon 0063: 202 + status-poll, stale-vertaling, nooit eeuwig 'bezig').
- `bank_relatie_boeking`: "koppel aan relatie" = aanbetalingsdocument (STAP-0 25-08: PurchaseInvoice/
  SalesInvoice op de relatie met één regel op 1403/1806) + afletteren; de per-relatie-
  administratie van de open aanbetaling (open → verrekend/gestorneerd) — RLZ kent 'm alleen als
  GB-saldo.
- `bank_splitsing` + `bank_splitsing_deel`: één mutatie over meerdere bestemmingen, geordende
  compositie van de bestaande motoren, half-verwerkt zichtbaar per deel.

RLS per administratie (deel-tabel via de eigen administratie_id-kolom — simpeler dan de
EXISTS-vorm van bank_boeking_regel), GRANT zonder DELETE: niets verdwijnt, stornering en
hervatting zijn UPDATE's.

Revision ID: 0071
Revises: 0070
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0071"
down_revision: str | None = "0070"
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
    # bank_boeking: grootboek-delen van een splitsing dragen deel_id; de één-per-mutatie-regel
    # geldt alleen voor volledige boekingen (deel_id IS NULL).
    op.add_column("bank_boeking", sa.Column("deel_id", sa.UUID(), nullable=True), schema="boekhouding")
    op.drop_index("ux_bank_boeking_actief_per_mutatie", table_name="bank_boeking", schema="boekhouding")
    op.create_index(
        "ux_bank_boeking_actief_per_mutatie",
        "bank_boeking",
        ["administratie_id", "payment_transaction_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status = 'geboekt' AND deel_id IS NULL"),
    )

    op.create_table(
        "bank_sync_run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("aangevraagd_door", sa.UUID(), nullable=True),
        sa.Column("aangevraagd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("gestart_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("laatst_actief_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("beeindigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resultaat", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fout_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('wachtrij', 'bezig', 'klaar', 'fout')", name="ck_bank_sync_run_status"),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["aangevraagd_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index("ix_bank_sync_run_administratie_id", "bank_sync_run", ["administratie_id"], schema="boekhouding")
    op.create_index(
        "ix_bank_sync_run_administratie_status", "bank_sync_run", ["administratie_id", "status"], schema="boekhouding"
    )
    _rls("bank_sync_run")

    op.create_table(
        "bank_relatie_boeking",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("payment_transaction_id", sa.UUID(), nullable=False),
        sa.Column("deel_id", sa.UUID(), nullable=True),
        sa.Column("relatie_soort", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("entity_naam", sa.Text(), nullable=True),
        sa.Column("bedrag", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("vooruit_ledger_id", sa.UUID(), nullable=False),
        sa.Column("taxrate_id", sa.UUID(), nullable=False),
        sa.Column("rlz_document_id", sa.UUID(), nullable=False),
        sa.Column("rlz_boekstuknummer", sa.Text(), nullable=True),
        sa.Column("rlz_payment_item_id", sa.UUID(), nullable=True),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("geboekt_door", sa.UUID(), nullable=False),
        sa.Column("geboekt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("verrekend_met_document_id", sa.UUID(), nullable=True),
        sa.Column("verrekend_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gestorneerd_door", sa.UUID(), nullable=True),
        sa.Column("gestorneerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("storno_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("relatie_soort IN ('crediteur', 'debiteur')", name="ck_bank_relatie_boeking_soort"),
        sa.CheckConstraint(
            "status IN ('geboekt', 'verrekend', 'gestorneerd')", name="ck_bank_relatie_boeking_status"
        ),
        sa.CheckConstraint(
            "status <> 'gestorneerd' OR (storno_reden IS NOT NULL AND length(btrim(storno_reden)) > 0)",
            name="ck_bank_relatie_boeking_storno_reden",
        ),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["geboekt_door"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(["gestorneerd_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_bank_relatie_boeking_administratie_id", "bank_relatie_boeking", ["administratie_id"], schema="boekhouding"
    )
    op.create_index(
        "ix_bank_relatie_boeking_entity",
        "bank_relatie_boeking",
        ["administratie_id", "entity_id", "status"],
        schema="boekhouding",
    )
    op.create_index(
        "ux_bank_relatie_boeking_actief_per_mutatie",
        "bank_relatie_boeking",
        ["administratie_id", "payment_transaction_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status IN ('geboekt', 'verrekend') AND deel_id IS NULL"),
    )
    _rls("bank_relatie_boeking")

    op.create_table(
        "bank_splitsing",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("payment_transaction_id", sa.UUID(), nullable=False),
        sa.Column("mutatie_bedrag", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("aangemaakt_door", sa.UUID(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("laatst_verwerkt_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gestorneerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('bezig', 'verwerkt', 'half_verwerkt', 'gestorneerd')", name="ck_bank_splitsing_status"
        ),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["aangemaakt_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index("ix_bank_splitsing_administratie_id", "bank_splitsing", ["administratie_id"], schema="boekhouding")
    op.create_index(
        "ux_bank_splitsing_actief_per_mutatie",
        "bank_splitsing",
        ["administratie_id", "payment_transaction_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status IN ('bezig', 'verwerkt', 'half_verwerkt')"),
    )
    _rls("bank_splitsing")

    op.create_table(
        "bank_splitsing_deel",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("splitsing_id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("volgnummer", sa.Integer(), nullable=False),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("bedrag", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("fout", sa.Text(), nullable=True),
        sa.Column("cyclus", sa.Integer(), nullable=False),
        sa.Column("bank_boeking_id", sa.UUID(), nullable=True),
        sa.Column("afletter_opdracht_id", sa.UUID(), nullable=True),
        sa.Column("relatie_boeking_id", sa.UUID(), nullable=True),
        sa.Column("verwerkt_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("soort IN ('grootboek', 'open_post', 'relatie')", name="ck_bank_splitsing_deel_soort"),
        sa.CheckConstraint(
            "status IN ('wacht', 'verwerkt', 'fout', 'gestorneerd')", name="ck_bank_splitsing_deel_status"
        ),
        sa.CheckConstraint("bedrag <> 0", name="ck_bank_splitsing_deel_bedrag"),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["splitsing_id"], ["boekhouding.bank_splitsing.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_bank_splitsing_deel_splitsing_id", "bank_splitsing_deel", ["splitsing_id"], schema="boekhouding"
    )
    _rls("bank_splitsing_deel")


def downgrade() -> None:
    for tabel in ("bank_splitsing_deel", "bank_splitsing", "bank_relatie_boeking", "bank_sync_run"):
        op.execute(f"REVOKE ALL ON boekhouding.{tabel} FROM {APP_ROLE}")
    op.drop_index("ix_bank_splitsing_deel_splitsing_id", table_name="bank_splitsing_deel", schema="boekhouding")
    op.drop_table("bank_splitsing_deel", schema="boekhouding")
    op.drop_index("ux_bank_splitsing_actief_per_mutatie", table_name="bank_splitsing", schema="boekhouding")
    op.drop_index("ix_bank_splitsing_administratie_id", table_name="bank_splitsing", schema="boekhouding")
    op.drop_table("bank_splitsing", schema="boekhouding")
    op.drop_index("ux_bank_relatie_boeking_actief_per_mutatie", table_name="bank_relatie_boeking", schema="boekhouding")
    op.drop_index("ix_bank_relatie_boeking_entity", table_name="bank_relatie_boeking", schema="boekhouding")
    op.drop_index("ix_bank_relatie_boeking_administratie_id", table_name="bank_relatie_boeking", schema="boekhouding")
    op.drop_table("bank_relatie_boeking", schema="boekhouding")
    op.drop_index("ix_bank_sync_run_administratie_status", table_name="bank_sync_run", schema="boekhouding")
    op.drop_index("ix_bank_sync_run_administratie_id", table_name="bank_sync_run", schema="boekhouding")
    op.drop_table("bank_sync_run", schema="boekhouding")
    op.drop_index("ux_bank_boeking_actief_per_mutatie", table_name="bank_boeking", schema="boekhouding")
    op.create_index(
        "ux_bank_boeking_actief_per_mutatie",
        "bank_boeking",
        ["administratie_id", "payment_transaction_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status = 'geboekt'"),
    )
    op.drop_column("bank_boeking", "deel_id", schema="boekhouding")
