"""Intercompany-factuurmatch + rekening-courant-aansluiting (Peter 16-09): `administratie_identiteit`, `intercompany_relatie`,
`rc_koppeling`, `rc_stand` in `boekhouding` (RLS als referentietabel over administraties heen: lezen voor iedereen in de app-rol,
schrijven door systeem én Beheerder — mens-mutatiepoort server-side; geen DELETE) + `reconciliatie_acceptatie.bron` kent de
nieuwe blokken 'intercompany' en 'rekening_courant'. Schema-only (pure DDL); afleiding is de dagelijkse sync-stap.

Revision ID: 0148
Revises: 0147
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0148"
down_revision: str | None = "0147"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABELLEN = ("administratie_identiteit", "intercompany_relatie", "rc_koppeling", "rc_stand")


def _rls(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {tabel}_lees ON boekhouding.{tabel} FOR SELECT USING (true)")
    op.execute(f"CREATE POLICY {tabel}_toevoegen ON boekhouding.{tabel} FOR INSERT WITH CHECK (true)")
    op.execute(f"CREATE POLICY {tabel}_muteren ON boekhouding.{tabel} FOR UPDATE USING (true) WITH CHECK (true)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        "administratie_identiteit",
        sa.Column("administratie_id", sa.UUID(), sa.ForeignKey("platform.administratie.id"), primary_key=True),
        sa.Column("kvk", sa.Text(), nullable=True),
        sa.Column("btw", sa.Text(), nullable=True),
        sa.Column("naam", sa.Text(), nullable=True),
        sa.Column("naam_norm", sa.Text(), nullable=True),
        sa.Column("sbi", sa.Text(), nullable=True),
        sa.Column("afkortingen", JSONB(), nullable=True),
        sa.Column("bron", sa.Text(), server_default="rlz", nullable=False),
        sa.Column("gelezen_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("bron IN ('rlz', 'odoo', 'mens')", name="ck_administratie_identiteit_bron"),
        schema="boekhouding",
    )
    op.create_table(
        "intercompany_relatie",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("administratie_a_id", sa.UUID(), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("entity_in_a", sa.UUID(), nullable=False),
        sa.Column("entity_naam", sa.Text(), nullable=True),
        sa.Column("administratie_b_id", sa.UUID(), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("richting", sa.Text(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="afgeleid", nullable=False),
        sa.Column("bron", sa.Text(), server_default="afgeleid", nullable=False),
        sa.Column("reden", sa.Text(), nullable=True),
        sa.Column("gewijzigd_door", sa.UUID(), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("administratie_a_id", "entity_in_a", "administratie_b_id", name="uq_intercompany_relatie"),
        sa.CheckConstraint("richting IN ('crediteur', 'debiteur')", name="ck_intercompany_relatie_richting"),
        sa.CheckConstraint("basis IN ('kvk', 'btw', 'naam', 'doorbelasting')", name="ck_intercompany_relatie_basis"),
        sa.CheckConstraint("status IN ('afgeleid', 'bevestigd', 'uitgesloten')", name="ck_intercompany_relatie_status"),
        sa.CheckConstraint("bron IN ('afgeleid', 'mens')", name="ck_intercompany_relatie_bron"),
        schema="boekhouding",
    )
    op.create_index("ix_intercompany_relatie_a", "intercompany_relatie", ["administratie_a_id"], schema="boekhouding")
    op.create_index("ix_intercompany_relatie_b", "intercompany_relatie", ["administratie_b_id"], schema="boekhouding")
    op.create_table(
        "rc_koppeling",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("administratie_a_id", sa.UUID(), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("rekening_a", sa.UUID(), nullable=False),
        sa.Column("rekening_a_code", sa.Text(), nullable=True),
        sa.Column("rekening_a_naam", sa.Text(), nullable=True),
        sa.Column("administratie_b_id", sa.UUID(), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("rekening_b", sa.UUID(), nullable=True),
        sa.Column("rekening_b_code", sa.Text(), nullable=True),
        sa.Column("rekening_b_naam", sa.Text(), nullable=True),
        sa.Column("basis", sa.Text(), server_default="naam", nullable=False),
        sa.Column("status", sa.Text(), server_default="afgeleid", nullable=False),
        sa.Column("bron", sa.Text(), server_default="afgeleid", nullable=False),
        sa.Column("reden", sa.Text(), nullable=True),
        sa.Column("gewijzigd_door", sa.UUID(), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("administratie_a_id", "rekening_a", "administratie_b_id", name="uq_rc_koppeling"),
        sa.CheckConstraint("basis IN ('naam', 'afkorting', 'mens')", name="ck_rc_koppeling_basis"),
        sa.CheckConstraint("status IN ('afgeleid', 'bevestigd', 'uitgesloten')", name="ck_rc_koppeling_status"),
        sa.CheckConstraint("bron IN ('afgeleid', 'mens')", name="ck_rc_koppeling_bron"),
        schema="boekhouding",
    )
    op.create_index("ix_rc_koppeling_a", "rc_koppeling", ["administratie_a_id"], schema="boekhouding")
    op.create_table(
        "rc_stand",
        sa.Column("koppeling_id", sa.UUID(), sa.ForeignKey("boekhouding.rc_koppeling.id"), primary_key=True),
        sa.Column("datum", sa.Date(), primary_key=True),
        sa.Column("saldo_a", sa.Numeric(14, 2), nullable=True),
        sa.Column("saldo_b", sa.Numeric(14, 2), nullable=True),
        sa.Column("sluit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("gemeten_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="boekhouding",
    )
    for tabel in TABELLEN:
        _rls(tabel)
    op.drop_constraint(
        "reconciliatie_acceptatie_bron_geldig", "reconciliatie_acceptatie", schema="boekhouding", type_="check"
    )
    op.create_check_constraint(
        "reconciliatie_acceptatie_bron_geldig",
        "reconciliatie_acceptatie",
        "bron IN ('documenten', 'bank', 'omzet', 'doorbelasting', 'intercompany', 'rekening_courant')",
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_constraint(
        "reconciliatie_acceptatie_bron_geldig", "reconciliatie_acceptatie", schema="boekhouding", type_="check"
    )
    op.create_check_constraint(
        "reconciliatie_acceptatie_bron_geldig",
        "reconciliatie_acceptatie",
        "bron IN ('documenten', 'bank', 'omzet', 'doorbelasting')",
        schema="boekhouding",
    )
    for tabel in reversed(TABELLEN):
        op.execute(f"REVOKE ALL ON boekhouding.{tabel} FROM {APP_ROLE}")
        op.drop_table(tabel, schema="boekhouding")
