"""Vragenworkflow wordt een dialoog (besluit Peter 25-08, RLZ-feedbackronde punt B).

Een vraag is voortaan een thread: vraagsteller → collega → antwoord → terug, onbeperkt heen en
weer. Elke bijdrage staat als eigen rij in `vraag_bericht` (append-only: alleen SELECT + INSERT
voor de app-rol — geen UPDATE/DELETE, een bijdrage wordt nooit herschreven of weggehaald). De
vraag blijft het boeken blokkeren tot de OORSPRONKELIJKE vraagsteller op "Afgehandeld" drukt —
niet al bij het eerste antwoord (was: status 'beantwoord' herstelde het document meteen).

Wijzigingen op `vraag`:
- nieuwe eindstatus 'afgehandeld' (+ `afgehandeld_door`/`afgehandeld_op`); 'beantwoord' blijft
  als LEGACY-waarde geldig voor bestaande rijen (historie herschrijven we niet — de servicelaag
  toont het oude antwoord als laatste bericht van de thread);
- `aan_de_beurt`: wie er in de dialoog aan zet is (de bestaande melding = Document.toegewezen_aan
  volgt dit veld). NULL op bestaande rijen = toegewezen_aan (schema-only migratie, geen backfill;
  de servicelaag valt terug op toegewezen_aan).

Revision ID: 0064
Revises: 0063
Create Date: 2026-08-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"

_OUDE_STATUS_CHECK = "status IN ('open', 'beantwoord', 'ingetrokken')"
_NIEUWE_STATUS_CHECK = "status IN ('open', 'beantwoord', 'ingetrokken', 'afgehandeld')"

_OUDE_CONSISTENT = (
    "(status = 'open'"
    " AND antwoord_tekst IS NULL AND beantwoord_door IS NULL AND beantwoord_op IS NULL"
    " AND ingetrokken_door IS NULL AND ingetrokken_op IS NULL AND ingetrokken_reden IS NULL)"
    " OR (status = 'beantwoord' AND btrim(antwoord_tekst) <> ''"
    " AND beantwoord_door IS NOT NULL AND beantwoord_op IS NOT NULL"
    " AND ingetrokken_door IS NULL AND ingetrokken_op IS NULL AND ingetrokken_reden IS NULL)"
    " OR (status = 'ingetrokken'"
    " AND ingetrokken_door IS NOT NULL AND ingetrokken_op IS NOT NULL"
    " AND antwoord_tekst IS NULL AND beantwoord_door IS NULL AND beantwoord_op IS NULL)"
)

_NIEUWE_CONSISTENT = (
    "(status = 'open'"
    " AND antwoord_tekst IS NULL AND beantwoord_door IS NULL AND beantwoord_op IS NULL"
    " AND ingetrokken_door IS NULL AND ingetrokken_op IS NULL AND ingetrokken_reden IS NULL"
    " AND afgehandeld_door IS NULL AND afgehandeld_op IS NULL)"
    " OR (status = 'beantwoord' AND btrim(antwoord_tekst) <> ''"
    " AND beantwoord_door IS NOT NULL AND beantwoord_op IS NOT NULL"
    " AND ingetrokken_door IS NULL AND ingetrokken_op IS NULL AND ingetrokken_reden IS NULL"
    " AND afgehandeld_door IS NULL AND afgehandeld_op IS NULL)"
    " OR (status = 'ingetrokken'"
    " AND ingetrokken_door IS NOT NULL AND ingetrokken_op IS NOT NULL"
    " AND antwoord_tekst IS NULL AND beantwoord_door IS NULL AND beantwoord_op IS NULL"
    " AND afgehandeld_door IS NULL AND afgehandeld_op IS NULL)"
    " OR (status = 'afgehandeld'"
    " AND afgehandeld_door IS NOT NULL AND afgehandeld_op IS NOT NULL"
    " AND antwoord_tekst IS NULL AND beantwoord_door IS NULL AND beantwoord_op IS NULL"
    " AND ingetrokken_door IS NULL AND ingetrokken_op IS NULL AND ingetrokken_reden IS NULL)"
)


def upgrade() -> None:
    op.add_column(
        "vraag",
        sa.Column("aan_de_beurt", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        schema="boekhouding",
    )
    op.add_column(
        "vraag",
        sa.Column("afgehandeld_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        schema="boekhouding",
    )
    op.add_column("vraag", sa.Column("afgehandeld_op", sa.DateTime(timezone=True), nullable=True), schema="boekhouding")
    op.drop_constraint("vraag_status_geldig", "vraag", schema="boekhouding", type_="check")
    op.create_check_constraint("vraag_status_geldig", "vraag", _NIEUWE_STATUS_CHECK, schema="boekhouding")
    op.drop_constraint("vraag_antwoord_consistent", "vraag", schema="boekhouding", type_="check")
    op.create_check_constraint("vraag_antwoord_consistent", "vraag", _NIEUWE_CONSISTENT, schema="boekhouding")

    op.create_table(
        "vraag_bericht",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("vraag_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.vraag.id"), nullable=False),
        sa.Column("auteur_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("tekst", sa.Text(), nullable=False),
        sa.Column("geplaatst_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("btrim(tekst) <> ''", name="vraag_bericht_tekst_niet_leeg"),
        schema="boekhouding",
    )
    op.create_index("ix_vraag_bericht_vraag_id", "vraag_bericht", ["vraag_id"], unique=False, schema="boekhouding")
    op.execute("ALTER TABLE boekhouding.vraag_bericht ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.vraag_bericht FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY vraag_bericht_scope ON boekhouding.vraag_bericht
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    # Append-only: bijdragen worden nooit herschreven of verwijderd (kernprincipe 4).
    op.execute(f"GRANT SELECT, INSERT ON boekhouding.vraag_bericht TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.vraag_bericht FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS vraag_bericht_scope ON boekhouding.vraag_bericht")
    op.drop_index("ix_vraag_bericht_vraag_id", table_name="vraag_bericht", schema="boekhouding")
    op.drop_table("vraag_bericht", schema="boekhouding")
    # Afgehandelde vragen passen niet in het oude model — terugdraaien kan alleen zonder zulke
    # rijen (downgrade stopt anders hard op de CHECK; mens beslist).
    op.drop_constraint("vraag_antwoord_consistent", "vraag", schema="boekhouding", type_="check")
    op.create_check_constraint("vraag_antwoord_consistent", "vraag", _OUDE_CONSISTENT, schema="boekhouding")
    op.drop_constraint("vraag_status_geldig", "vraag", schema="boekhouding", type_="check")
    op.create_check_constraint("vraag_status_geldig", "vraag", _OUDE_STATUS_CHECK, schema="boekhouding")
    op.drop_column("vraag", "afgehandeld_op", schema="boekhouding")
    op.drop_column("vraag", "afgehandeld_door", schema="boekhouding")
    op.drop_column("vraag", "aan_de_beurt", schema="boekhouding")
