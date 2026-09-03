"""Opruimpunt alembic-drift uit migraties 0099/0100 (03-09): negen kolommen zijn dáár als `sa.String()`
(VARCHAR) aangemaakt terwijl de modellen `Mapped[str]` dragen — sinds de 16-08-lijn (type_annotation_map)
is dat `Text`. `alembic check` meldde daardoor negen `modify_type`-operaties. Deze migratie trekt de
database gelijk aan de modellen: VARCHAR → TEXT (in PostgreSQL een metadata-wijziging, geen herschrijving,
geen dataverlies — beide typen zijn onbegrensd). Schema-only.

Kolommen:
- boekhouding.terugkerend_herbereken_run: status, foutreden  (0099)
- boekhouding.crediteur_dubbel_afmelding: sleutel_soort, sleutel, combinatie, reden  (0100)
- boekhouding.crediteur_archiveer_werklijst: voorkeur_naam, status, gedaan_bron  (0100)

Revision ID: 0103
Revises: 0102
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0103"
down_revision: str | None = "0102"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_KOLOMMEN: tuple[tuple[str, str], ...] = (
    ("terugkerend_herbereken_run", "status"),
    ("terugkerend_herbereken_run", "foutreden"),
    ("crediteur_dubbel_afmelding", "sleutel_soort"),
    ("crediteur_dubbel_afmelding", "sleutel"),
    ("crediteur_dubbel_afmelding", "combinatie"),
    ("crediteur_dubbel_afmelding", "reden"),
    ("crediteur_archiveer_werklijst", "voorkeur_naam"),
    ("crediteur_archiveer_werklijst", "status"),
    ("crediteur_archiveer_werklijst", "gedaan_bron"),
)


def upgrade() -> None:
    for tabel, kolom in _KOLOMMEN:
        op.alter_column(tabel, kolom, type_=sa.Text(), existing_type=sa.String(), schema="boekhouding")


def downgrade() -> None:
    for tabel, kolom in reversed(_KOLOMMEN):
        op.alter_column(tabel, kolom, type_=sa.String(), existing_type=sa.Text(), schema="boekhouding")
