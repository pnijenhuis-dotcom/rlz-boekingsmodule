"""Afwijzen-met-verplichte-reden: afwijzing-record per document (CLAUDE.md "Afwijzen =
verplichte reden, blijft zichtbaar", mockup #afwijsmodal).

Zelfde opzet als de vragenworkflow (migratie 0022): een afwijzing wordt nooit verwijderd (geen
DELETE-grant), afwijzen is een INSERT, heropenen zet status/velden op dezelfde rij (UPDATE) —
historie blijft volledig bewaard. Précies één OPEN afwijzing per document tegelijk (partiële
unique index); eerdere heropende afwijzingen blijven staan.

`reden` is óók op DB-niveau verplicht (CHECK niet-leeg): een afwijzing zonder reden bestaat
niet, in geen enkele laag. `status_voor_afwijzing` is de document-status van vóór de afwijzing
(te_controleren, handmatig_afmaken of klaar_om_te_boeken): heropenen herstelt exact díé
herkomst — zelfde status_voor_*-patroon als vraag.status_voor_vraag.

CHECK-constraints houden de rij intern consistent per status: open = geen heropend-velden;
heropend = heropend_door/op gevuld. RLS conform het standaardpatroon.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "afwijzing",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("afgewezen_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("afgewezen_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reden", sa.Text(), nullable=False),
        sa.Column("toegewezen_aan", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        # Bewust TEXT + CHECK i.p.v. de document_status-PG-enum — zelfde overweging als
        # vraag.status_voor_vraag (migratie 0022: ALTER TYPE ... ADD VALUE-beperking).
        sa.Column("status_voor_afwijzing", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("heropend_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("heropend_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('open', 'heropend')", name="afwijzing_status_geldig"),
        sa.CheckConstraint("btrim(reden) <> ''", name="afwijzing_reden_niet_leeg"),
        sa.CheckConstraint(
            "status_voor_afwijzing IN ('te_controleren', 'handmatig_afmaken', 'klaar_om_te_boeken')",
            name="afwijzing_herkomst_herstelbaar",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND heropend_door IS NULL AND heropend_op IS NULL)"
            " OR (status = 'heropend' AND heropend_door IS NOT NULL AND heropend_op IS NOT NULL)",
            name="afwijzing_heropening_consistent",
        ),
        schema="boekhouding",
    )
    # Eén open afwijzing per document tegelijk — op DB-niveau afgedwongen, niet alleen in de
    # service (twee gelijktijdige requests kunnen de service-check allebei passeren).
    op.create_index(
        "afwijzing_een_open_per_document",
        "afwijzing",
        ["document_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.execute("ALTER TABLE boekhouding.afwijzing ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.afwijzing FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY afwijzing_scope ON boekhouding.afwijzing
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.afwijzing TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.afwijzing FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS afwijzing_scope ON boekhouding.afwijzing")
    op.drop_index("afwijzing_een_open_per_document", table_name="afwijzing", schema="boekhouding")
    op.drop_table("afwijzing", schema="boekhouding")
