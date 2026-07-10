"""Waarborg projectadministratie (groottevrij-besluit AI-extractie, 2026-07-10): nieuwe
documentstatus `handmatig_afmaken`. Krijgt een document als de AI-extractie de regelset niet
aantoonbaar compleet kreeg (afgekapt én chunking onvolledig) bij een administratie met
projectplicht — er wordt dan bewust GEEN (totalen-only) veldvoorstel opgeslagen, zodat
regeldetail/projecttoerekening nooit stilletjes wegvalt. De controleur vult alles handmatig in
(harde checks blijven de poort: project verplicht per regel, regelsom vs. totaal) of probeert
de extractie opnieuw.

PostgreSQL-noot: ALTER TYPE ... ADD VALUE mag sinds PG12 binnen een transactie, zolang de nieuwe
waarde niet in dezelfde transactie gebruikt wordt — deze migratie doet niets anders. Enum-waarden
verwijderen kan PostgreSQL niet; downgrade is daarom een bewuste no-op (de waarde blijft bestaan
maar wordt door oudere code simpelweg nooit gezet).

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE boekhouding.document_status ADD VALUE IF NOT EXISTS 'handmatig_afmaken'")


def downgrade() -> None:
    # PostgreSQL kent geen DROP VALUE voor enums; de waarde laten staan is onschadelijk.
    pass
