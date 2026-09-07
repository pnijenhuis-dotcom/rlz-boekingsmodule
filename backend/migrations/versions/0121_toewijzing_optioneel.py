"""Toewijzing optioneel op afwijzing en vraag (herstelrun "geen stille no-op" 07-09, blok 2; besluit Peter,
kernprincipe 7 "minimale mens, maximale autonomie": automatisering wacht NOOIT op een menselijke instelling).

`boekhouding.afwijzing.toegewezen_aan` ("Ter controle naar") en `boekhouding.vraag.toegewezen_aan` waren NOT NULL
(migraties 0023/0022): zonder administratie-eigenaar én zonder expliciete toewijzing weigerde de servicelaag
(`GeenToewijzingMogelijk`) — waardoor élke automatische afvoer/vraag op een eigenaarloze administratie strandde
(in productie heeft geen enkele administratie een eigenaar). Sinds deze migratie mag de toewijzing leeg zijn: de
handeling wordt uitgevoerd en de controle-rij landt ZONDER toewijzing in de kantoorbrede lijsten (werkvoorraad
"Afgewezen — ter controle", Inzicht › Open vragen, Mogelijk-duplicaat-tab). Een expliciet opgegeven toegewezene
buiten de scope blijft een zichtbare fout (`ToegewezeneBuitenScope`).

`document.toegewezen_aan` (0004) en `vraag.aan_de_beurt` (0064) waren al nullable. Schema-only, geen backfill:
bestaande rijen houden hun toewijzing.

Revision ID: 0121
Revises: 0120
Create Date: 2026-09-07

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0121"
down_revision: str | None = "0120"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("afwijzing", "toegewezen_aan", nullable=True, schema="boekhouding")
    op.alter_column("vraag", "toegewezen_aan", nullable=True, schema="boekhouding")


def downgrade() -> None:
    # Rijen zonder toewijzing zouden de NOT NULL blokkeren — een downgrade vereist dan eerst een bewuste
    # (menselijke) toewijzing van die rijen; nooit stil verwijderen of een verzonnen persoon invullen.
    op.alter_column("vraag", "toegewezen_aan", nullable=False, schema="boekhouding")
    op.alter_column("afwijzing", "toegewezen_aan", nullable=False, schema="boekhouding")
