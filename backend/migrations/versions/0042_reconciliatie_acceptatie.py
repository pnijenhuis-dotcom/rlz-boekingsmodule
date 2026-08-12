"""Geauditeerde acceptatie van reconciliatie-afwijkingen (vangrail-hardening 2026-08-12).

Aanleiding: de dagelijkse reconciliatie meldde drie opgeruimde kliktest-documenten op de
test-administratie elke ochtend opnieuw. Terugkerende ruis in een vangrail is gevaarlijker dan
geen vangrail — je went aan rood. Een acceptatie onderdrukt niets (de regel blijft in het
rapport staan), maar haalt de afwijking uit de exit-code, mét verplichte reden, actor en
audit_event; intrekken kan altijd en verwijdert nooit een rij.

De unieke index is partieel op de actieve rijen: dezelfde afwijking kan door de tijd heen dus
meermaals geaccepteerd en ingetrokken worden zonder dat de historie verdwijnt.

Revision ID: 0042
Revises: 0041
Create Date: 2026-08-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "reconciliatie_acceptatie",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("record_id", UUID(as_uuid=True), nullable=False),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("vingerafdruk", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("reden", sa.Text(), nullable=False),
        sa.Column(
            "geaccepteerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False
        ),
        sa.Column("geaccepteerd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ingetrokken_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("ingetrokken_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "bron IN ('documenten', 'bank', 'omzet')", name="reconciliatie_acceptatie_bron_geldig"
        ),
        sa.CheckConstraint("length(btrim(reden)) >= 5", name="reconciliatie_acceptatie_reden_gevuld"),
        sa.CheckConstraint(
            "(ingetrokken_op IS NULL) = (ingetrokken_door IS NULL)",
            name="reconciliatie_acceptatie_intrekking_compleet",
        ),
        schema="boekhouding",
    )
    # Partieel uniek op de ACTIEVE rijen: precies de sleutel waarop de service zoekt
    # (administratie + bron + vingerafdruk), zodat een dubbele acceptatie onmogelijk is en de
    # lookup nooit meer dan één rij kan opleveren.
    op.create_index(
        "reconciliatie_acceptatie_actief_uniek",
        "reconciliatie_acceptatie",
        ["administratie_id", "bron", "vingerafdruk"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("ingetrokken_op IS NULL"),
    )
    op.execute("ALTER TABLE boekhouding.reconciliatie_acceptatie ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.reconciliatie_acceptatie FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY reconciliatie_acceptatie_scope ON boekhouding.reconciliatie_acceptatie
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    # Geen DELETE: intrekken is een UPDATE, niets verdwijnt (CLAUDE.md-kernprincipe 4).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.reconciliatie_acceptatie TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS reconciliatie_acceptatie_scope ON boekhouding.reconciliatie_acceptatie")
    op.drop_index(
        "reconciliatie_acceptatie_actief_uniek", table_name="reconciliatie_acceptatie", schema="boekhouding"
    )
    op.drop_table("reconciliatie_acceptatie", schema="boekhouding")
