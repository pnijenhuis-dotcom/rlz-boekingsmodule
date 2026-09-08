"""Matchmotor bank — IBAN-geheugen (blok 2 bundel 08-09-2026).

`boekhouding.bank_relatie_iban`: geleerde koppeling tegenrekening-IBAN ↔ RLZ-entity per administratie,
gevoed door geslaagde afletteringen (app/bank/afletteren.py). Het "naam/IBAN"-been van de nieuwe
score (teken + naam/IBAN + nummer + bedrag) — een tegenpartij die onder een andere naam betaalt
("Hr P.W. N.-P." voor een B.V.) wordt zo alsnog herkend, maar pas ná een bevestigde aflettering.
Uniek per (administratie, iban, entity); herhaalde bevestigingen tellen op. Schema-only.

RLS per administratie (0071-patroon), GRANT zonder DELETE: geheugen verdwijnt nooit stil.

Revision ID: 0127
Revises: 0126
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0127"
down_revision: str | None = "0126"
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
    op.create_table(
        "bank_relatie_iban",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("iban", sa.Text(), nullable=False),
        sa.Column("entity_guid", sa.UUID(), nullable=False),
        sa.Column("entity_naam", sa.Text(), nullable=True),
        sa.Column("aantal_bevestigingen", sa.Integer(), nullable=False),
        sa.Column("eerste_bevestiging_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("laatste_bevestiging_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("laatste_opdracht_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_bank_relatie_iban_administratie_id", "bank_relatie_iban", ["administratie_id"], schema="boekhouding"
    )
    op.create_index(
        "ux_bank_relatie_iban_per_relatie",
        "bank_relatie_iban",
        ["administratie_id", "iban", "entity_guid"],
        unique=True,
        schema="boekhouding",
    )
    _rls("bank_relatie_iban")


def downgrade() -> None:
    op.drop_index("ux_bank_relatie_iban_per_relatie", table_name="bank_relatie_iban", schema="boekhouding")
    op.drop_index("ix_bank_relatie_iban_administratie_id", table_name="bank_relatie_iban", schema="boekhouding")
    op.drop_table("bank_relatie_iban", schema="boekhouding")
