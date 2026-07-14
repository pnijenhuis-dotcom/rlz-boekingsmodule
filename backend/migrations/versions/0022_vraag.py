"""Vragenworkflow: vraag-record per document (CLAUDE.md domeinbeslissing "Vragenworkflow",
mockup #vragen + #vraagmodal).

Append-only in de zin van: een vraag wordt nooit verwijderd (geen DELETE-grant) en het stellen
is een INSERT; beantwoorden of intrekken zet status/velden op dezelfde rij (UPDATE) — de
historie blijft volledig bewaard, ook na boeken van het document. Précies één OPEN vraag per
document tegelijk (partiële unique index); eerdere beantwoorde/ingetrokken vragen blijven staan.

`status_voor_vraag` is de document-status van vóór de vraag (te_controleren, handmatig_afmaken
of klaar_om_te_boeken): beantwoorden én intrekken herstellen exact díé herkomst — nooit
hardgecodeerd te_controleren, anders verliest een handmatig_afmaken- of klaar_om_te_boeken-
document zijn context.

CHECK-constraints houden de rij intern consistent per status: open = geen antwoord- en geen
intrek-velden; beantwoord = alle drie de antwoordvelden, geen intrek-velden; ingetrokken =
ingetrokken_door/op gevuld (reden optioneel), geen antwoordvelden (zelfde patroon als
leverancier_iban's bevestigd_door-constraint, migratie 0019). RLS conform het standaardpatroon.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "vraag",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("gesteld_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("gesteld_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("vraag_tekst", sa.Text(), nullable=False),
        sa.Column("toegewezen_aan", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        # Bewust TEXT + CHECK i.p.v. de document_status-PG-enum: 'handmatig_afmaken' is in
        # migratie 0015 via ALTER TYPE ... ADD VALUE toegevoegd en Postgres weigert een nieuwe
        # enum-waarde in DDL binnen dezelfde (verse-database-)transactieketen
        # ("unsafe use of new value"). De servicelaag vertaalt van/naar DocumentStatus.
        sa.Column("status_voor_vraag", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("antwoord_tekst", sa.Text(), nullable=True),
        sa.Column("beantwoord_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("beantwoord_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingetrokken_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("ingetrokken_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingetrokken_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('open', 'beantwoord', 'ingetrokken')", name="vraag_status_geldig"),
        sa.CheckConstraint("btrim(vraag_tekst) <> ''", name="vraag_tekst_niet_leeg"),
        sa.CheckConstraint(
            "status_voor_vraag IN ('te_controleren', 'handmatig_afmaken', 'klaar_om_te_boeken')",
            name="vraag_herkomst_herstelbaar",
        ),
        sa.CheckConstraint(
            "(status = 'open'"
            " AND antwoord_tekst IS NULL AND beantwoord_door IS NULL AND beantwoord_op IS NULL"
            " AND ingetrokken_door IS NULL AND ingetrokken_op IS NULL AND ingetrokken_reden IS NULL)"
            " OR (status = 'beantwoord' AND btrim(antwoord_tekst) <> ''"
            " AND beantwoord_door IS NOT NULL AND beantwoord_op IS NOT NULL"
            " AND ingetrokken_door IS NULL AND ingetrokken_op IS NULL AND ingetrokken_reden IS NULL)"
            " OR (status = 'ingetrokken'"
            " AND ingetrokken_door IS NOT NULL AND ingetrokken_op IS NOT NULL"
            " AND antwoord_tekst IS NULL AND beantwoord_door IS NULL AND beantwoord_op IS NULL)",
            name="vraag_antwoord_consistent",
        ),
        schema="boekhouding",
    )
    # Eén open vraag per document tegelijk — op DB-niveau afgedwongen, niet alleen in de service
    # (twee gelijktijdige requests kunnen de service-check allebei passeren).
    op.create_index(
        "vraag_een_open_per_document",
        "vraag",
        ["document_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.execute("ALTER TABLE boekhouding.vraag ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.vraag FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY vraag_scope ON boekhouding.vraag
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.vraag TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.vraag FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS vraag_scope ON boekhouding.vraag")
    op.drop_index("vraag_een_open_per_document", table_name="vraag", schema="boekhouding")
    op.drop_table("vraag", schema="boekhouding")
