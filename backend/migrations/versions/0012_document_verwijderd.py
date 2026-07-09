"""Soft-delete voor documenten (design-pass controlescherm, taak 4): nieuwe statuswaarde
'verwijderd' op het bestaande document_status-enum. Bewust géén harde delete ("niets verdwijnt
stil", CLAUDE.md kernprincipe 4) — bestand en record blijven bestaan, alleen de status verandert
(zelfde statusmachine/audit-pad als elke andere overgang, zie app/documenten/statusmachine.py en
service.py::verwijder_document/herstel_document). Geboekte documenten kunnen hier nooit naartoe
(bewaarplicht) — dat blijft afgedwongen doordat GEBOEKT geen uitgaande overgangen heeft.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_OUDE_WAARDEN = (
    "ontvangen",
    "extractie_bezig",
    "te_controleren",
    "klaar_om_te_boeken",
    "geboekt",
    "vraag_open",
    "afgewezen",
    "boeken_mislukt",
    "niet_toegewezen",
)


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE mag sinds PG12 binnen een transactie (Makefile's check-versions
    # eist PG16) — mits de nieuwe waarde niet in dezelfde transactie gebruikt wordt, wat hier niet
    # gebeurt.
    op.execute("ALTER TYPE boekhouding.document_status ADD VALUE 'verwijderd'")


def downgrade() -> None:
    # Postgres kent geen ALTER TYPE ... DROP VALUE — enige weg terug is het hele enum-type
    # vervangen: hernoemen, opnieuw aanmaken zonder 'verwijderd', elke kolom die het type gebruikt
    # hercasten, oude type droppen. Bestaande 'verwijderd'-rijen (bv. van een eerdere testrun)
    # kunnen niet zinvol naar hun "vorige status" terug (die staat alleen in de JSONB-tijdlijn,
    # niet op de kolom) — val terug op 'te_controleren'. Dit pad is voor het terugdraaien van de
    # migratie zelf (test-database-reset in tests/conftest.py); de reguliere app-flow
    # (service.py::herstel_document) blijft de precieze vorige status gebruiken en verwijdert
    # nooit stil.
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE boekhouding.document SET status = 'te_controleren' WHERE status = 'verwijderd'"))
    # De tijdlijn (append-only) kan historische 'verwijderd'-rijen bevatten (elke eerdere
    # verwijdering/herstel schreef er een) — zelfde lossy fallback als hierboven, alleen relevant
    # voor dit downgrade-pad (test-database-reset), niet voor de reguliere append-only werking.
    conn.execute(
        sa.text(
            "UPDATE boekhouding.document_gebeurtenis SET van_status = 'te_controleren' WHERE van_status = 'verwijderd'"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE boekhouding.document_gebeurtenis SET naar_status = 'te_controleren' WHERE naar_status = 'verwijderd'"
        )
    )
    # De server_default op document.status (migratie 0004) blokkeert de type-cast hieronder —
    # even weghalen en na de cast in dezelfde vorm terugzetten.
    conn.execute(sa.text("ALTER TABLE boekhouding.document ALTER COLUMN status DROP DEFAULT"))
    conn.execute(sa.text("ALTER TYPE boekhouding.document_status RENAME TO document_status_met_verwijderd"))
    waarden = ", ".join(f"'{w}'" for w in _OUDE_WAARDEN)
    conn.execute(sa.text(f"CREATE TYPE boekhouding.document_status AS ENUM ({waarden})"))
    for tabel, kolom in (
        ("document", "status"),
        ("document_gebeurtenis", "van_status"),
        ("document_gebeurtenis", "naar_status"),
    ):
        conn.execute(
            sa.text(
                f"ALTER TABLE boekhouding.{tabel} ALTER COLUMN {kolom} "
                f"TYPE boekhouding.document_status USING {kolom}::text::boekhouding.document_status"
            )
        )
    conn.execute(sa.text("ALTER TABLE boekhouding.document ALTER COLUMN status SET DEFAULT 'ontvangen'"))
    conn.execute(sa.text("DROP TYPE boekhouding.document_status_met_verwijderd"))
