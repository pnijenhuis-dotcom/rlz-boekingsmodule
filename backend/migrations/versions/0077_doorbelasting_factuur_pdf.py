"""Rechtsgeldige factuur-PDF bij de doorbelasting (blok A gecombineerde run 26-08, besluit Peter
26-08 — art. 35a Wet OB: het doel had als bijlage alleen de leveranciersbon op naam van de bron).

Vijf kolommen op `boekhouding.doorbelasting_boeking`: status ('aanwezig' | 'ontbreekt', NULL =
boeking van vóór deze migratie — kandidaat voor `make doorbelasting-facturen-herstel`), reden,
bestandsnaam, opslagpad van onze bewaarkopie en tijdstip. Schema-only; de backfill voor bestaande
GEBOEKTE runs is het expliciete herstel-commando (dry-run eerst, per run geauditeerd).

Revision ID: 0077
Revises: 0076
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("doorbelasting_boeking", sa.Column("factuur_pdf_status", sa.String(), nullable=True), schema="boekhouding")
    op.add_column("doorbelasting_boeking", sa.Column("factuur_pdf_reden", sa.String(), nullable=True), schema="boekhouding")
    op.add_column(
        "doorbelasting_boeking", sa.Column("factuur_pdf_bestandsnaam", sa.String(), nullable=True), schema="boekhouding"
    )
    op.add_column(
        "doorbelasting_boeking", sa.Column("factuur_pdf_opslag_pad", sa.String(), nullable=True), schema="boekhouding"
    )
    op.add_column(
        "doorbelasting_boeking", sa.Column("factuur_pdf_op", sa.DateTime(timezone=True), nullable=True), schema="boekhouding"
    )
    op.create_check_constraint(
        "doorbelasting_boeking_factuur_pdf_status",
        "doorbelasting_boeking",
        "factuur_pdf_status IS NULL OR factuur_pdf_status IN ('aanwezig', 'ontbreekt')",
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_constraint("doorbelasting_boeking_factuur_pdf_status", "doorbelasting_boeking", schema="boekhouding")
    for kolom in ("factuur_pdf_op", "factuur_pdf_opslag_pad", "factuur_pdf_bestandsnaam", "factuur_pdf_reden", "factuur_pdf_status"):
        op.drop_column("doorbelasting_boeking", kolom, schema="boekhouding")
