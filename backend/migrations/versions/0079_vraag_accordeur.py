"""Vragen-dialoog naar de klant-accordeur (blok B5 gecombineerde run 26-08, besluit Peter 25/26-08 —
uitbreiding op de thread van migratie 0064).

Twee schema-wijzigingen op `boekhouding.vraag`:
1. De herkomst-CHECK `vraag_herkomst_herstelbaar` laat óók `ter_accordering` en `geboekt` toe: een vraag aan de accordeur op een document dat bij de klant ligt (of al geboekt
   is) verandert de documentstatus NIET — het akkoord in de app blijft mogelijk; alleen het BOEKEN
   is geblokkeerd (poort in `_rond_af_en_boek` zet het document dan zichtbaar op `vraag_open`).
2. `aan_de_beurt_sinds` + `accordeur_gemeld_op`: de beurt-wissel naar een accordeur stuurt de
   bestaande push-anders-mail-kanalen mét stille uren (20:00–08:00) — idempotent per beurt via
   deze twee tijdstippen (job `rlz-nieuwe-facturen` vangt de uitgestelde meldingen op).

Revision ID: 0079
Revises: 0078
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_OUD = "status_voor_vraag IN ('te_controleren', 'handmatig_afmaken', 'klaar_om_te_boeken')"
_NIEUW = (
    "status_voor_vraag IN ('te_controleren', 'handmatig_afmaken', 'klaar_om_te_boeken', "
    "'ter_accordering', 'geboekt')"
)


def upgrade() -> None:
    op.drop_constraint("vraag_herkomst_herstelbaar", "vraag", schema="boekhouding", type_="check")
    op.create_check_constraint("vraag_herkomst_herstelbaar", "vraag", _NIEUW, schema="boekhouding")
    op.add_column("vraag", sa.Column("aan_de_beurt_sinds", sa.DateTime(timezone=True), nullable=True), schema="boekhouding")
    op.add_column("vraag", sa.Column("accordeur_gemeld_op", sa.DateTime(timezone=True), nullable=True), schema="boekhouding")


def downgrade() -> None:
    op.drop_column("vraag", "accordeur_gemeld_op", schema="boekhouding")
    op.drop_column("vraag", "aan_de_beurt_sinds", schema="boekhouding")
    op.drop_constraint("vraag_herkomst_herstelbaar", "vraag", schema="boekhouding", type_="check")
    op.create_check_constraint("vraag_herkomst_herstelbaar", "vraag", _OUD, schema="boekhouding")
