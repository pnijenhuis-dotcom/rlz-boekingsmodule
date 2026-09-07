"""Factuurperiode op weekniveau (blok 11 vervolgrun 07-09; vraag Peter: kosten op weekniveau voor
projectadministraties — alleen de datalaag). Vijf nullable kolommen op `boekhouding.boekvoorstel`:

- `periode_jaar`, `periode_week_van`, `periode_week_tot`: de ISO-week(s) waarop de factuur betrekking heeft;
- `periode_herkomst`: 'factuur' (letterlijk voorgelezen en deterministisch genormaliseerd — app/documenten/periode.py),
  'factuur_maand' (maandvermelding → weekbereik van de maand), 'afgeleid_van_factuurdatum' (terugval: ISO-week van
  de factuurdatum) of 'mens' (correctie via de PUT, wint altijd);
- `periode_tekst`: de ruwe factuurtekst (blijft bewaard, ook als die onherkenbaar was).

Op `boekvoorstel` (niet `document`): de periode is een kopveld van het boekvoorstel — het A10-prefill-/autosave-pad
persisteert al de kopvelden (vervaldatum, betalingskenmerk) dáár, de mens corrigeert via dezelfde PUT en de
boekmotoren lezen het boekvoorstel. Geen backfill: bestaande voorstellen krijgen de afleiding live bij het openen
en persistent bij de eerstvolgende opslag. Schema-only.

Revision ID: 0120
Revises: 0119
Create Date: 2026-09-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0120"
down_revision: str | None = "0119"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("boekvoorstel", sa.Column("periode_jaar", sa.Integer(), nullable=True), schema="boekhouding")
    op.add_column("boekvoorstel", sa.Column("periode_week_van", sa.Integer(), nullable=True), schema="boekhouding")
    op.add_column("boekvoorstel", sa.Column("periode_week_tot", sa.Integer(), nullable=True), schema="boekhouding")
    op.add_column("boekvoorstel", sa.Column("periode_herkomst", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column("boekvoorstel", sa.Column("periode_tekst", sa.Text(), nullable=True), schema="boekhouding")
    op.create_check_constraint(
        "ck_boekvoorstel_periode_herkomst",
        "boekvoorstel",
        "periode_herkomst IS NULL OR periode_herkomst IN ('factuur', 'factuur_maand', 'afgeleid_van_factuurdatum', 'mens')",
        schema="boekhouding",
    )
    op.create_check_constraint(
        "ck_boekvoorstel_periode_weken",
        "boekvoorstel",
        "(periode_week_van IS NULL AND periode_week_tot IS NULL) OR "
        "(periode_week_van BETWEEN 1 AND 53 AND periode_week_tot BETWEEN periode_week_van AND 53)",
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_constraint("ck_boekvoorstel_periode_weken", "boekvoorstel", schema="boekhouding", type_="check")
    op.drop_constraint("ck_boekvoorstel_periode_herkomst", "boekvoorstel", schema="boekhouding", type_="check")
    for kolom in ("periode_tekst", "periode_herkomst", "periode_week_tot", "periode_week_van", "periode_jaar"):
        op.drop_column("boekvoorstel", kolom, schema="boekhouding")
