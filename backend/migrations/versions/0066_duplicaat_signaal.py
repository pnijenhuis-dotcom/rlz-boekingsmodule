"""Duplicaatsignaal eerder zichtbaar (besluit Peter 25-08, RLZ-feedbackronde deel 2 punt 6).

De duplicaatcheck-uitkomst (eigen RLZ-query op Entity+Reference+bedrag, besluit 0013) was tot nu
alleen zichtbaar op het controlescherm/boekmoment. Voortaan wordt die uitkomst ná extractie en
bij elke veldopslag berekend en op het document gecachet, zodat de werkvoorraad-documentenlijst
een chip "mogelijk duplicaat in RLZ" toont én erop kan filteren — zónder live RLZ-call per
lijstrij. Nieuwe tabel boekhouding.duplicaat_signaal: één rij per document (PK document_id),
uitkomst geen / mogelijk_duplicaat / niet_toetsbaar / onbekend, de getoetste kopgegevens en de
RLZ-treffers. Herberekenen = UPDATE (geen DELETE-grant: het spoor van de laatste toetsing
blijft staan — "niets verdwijnt stil"). De live check op het boekmoment blijft de bindende
poort; de cache is signalering.

RLS op administratie (bestaand patroon 0044/0057).

Revision ID: 0066
Revises: 0065
Create Date: 2026-08-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "duplicaat_signaal",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("uitkomst", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.UUID(), nullable=True),
        sa.Column("referentie", sa.Text(), nullable=True),
        sa.Column("totaalbedrag", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("treffers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("melding", sa.Text(), nullable=True),
        sa.Column("berekend_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "uitkomst IN ('geen', 'mogelijk_duplicaat', 'niet_toetsbaar', 'onbekend')",
            name="ck_duplicaat_signaal_uitkomst",
        ),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["boekhouding.document.id"]),
        sa.PrimaryKeyConstraint("document_id"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_duplicaat_signaal_administratie_uitkomst",
        "duplicaat_signaal",
        ["administratie_id", "uitkomst"],
        unique=False,
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.duplicaat_signaal ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.duplicaat_signaal FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY duplicaat_signaal_scope ON boekhouding.duplicaat_signaal
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    # Bewust zonder DELETE: herberekenen is een UPDATE, het spoor van de laatste toetsing blijft.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.duplicaat_signaal TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.duplicaat_signaal FROM {APP_ROLE}")
    op.drop_index("ix_duplicaat_signaal_administratie_uitkomst", table_name="duplicaat_signaal", schema="boekhouding")
    op.drop_table("duplicaat_signaal", schema="boekhouding")
