"""Odoo-rekening-mapping: derde soort 'project' (RLZ-project → Odoo-analytic-account) — Odoo-slotstuk 04-09,
besluit Peter 04-09 (beslispunt 2 van "ODOO-AFRONDINGSRUN 04-09 — BLOK A + C1").

Een RLZ-administratie die op Odoo overstapt draagt in het boekingsgeheugen en de open boekvoorstellen óók
RLZ-project-UUID's. Die vertaalden tot nu toe naar None ("RLZ-project ≠ Odoo-analytic-account"); met de
projectmapping verliest projectdata zijn koppeling niet meer: `app/odoo/mapping.py::vertaal_observaties`
zet `project_id` via de geldende 'project'-rij. Nieuwe bronnen: `projectnummer` (groen — leidende cijfers
van de RLZ-naam == Odoo-code), `projectnaam` (oranje — genormaliseerde naamgelijkheid), `aangemaakt` (bij de
overstap in Odoo opgezocht/aangemaakt op code + plan).

Pure DDL: twee CHECK-constraints verruimd (drop + create). Geen backfill — bestaande rijen blijven geldig.

Revision ID: 0113
Revises: 0112
Create Date: 2026-09-04

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0113"
down_revision: str | None = "0112"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

TABEL = "odoo_rekening_mapping"
SCHEMA = "boekhouding"

SOORT_OUD = "soort IN ('grootboek', 'btw')"
SOORT_NIEUW = "soort IN ('grootboek', 'btw', 'project')"
BRON_OUD = "bron IN ('zelfde_code', 'code_verlengd', 'tarief', 'handmatig')"
BRON_NIEUW = (
    "bron IN ('zelfde_code', 'code_verlengd', 'tarief', 'handmatig', 'projectnummer', 'projectnaam', 'aangemaakt')"
)


def upgrade() -> None:
    op.drop_constraint("ck_odoo_rekening_mapping_soort", TABEL, schema=SCHEMA, type_="check")
    op.create_check_constraint("ck_odoo_rekening_mapping_soort", TABEL, SOORT_NIEUW, schema=SCHEMA)
    op.drop_constraint("ck_odoo_rekening_mapping_bron", TABEL, schema=SCHEMA, type_="check")
    op.create_check_constraint("ck_odoo_rekening_mapping_bron", TABEL, BRON_NIEUW, schema=SCHEMA)


def downgrade() -> None:
    # Rijen mét soort 'project' of een project-bron passen niet in de oude constraint — de downgrade laat ze
    # bewust staan als dat zo is (append-only tabel: nooit stil verwijderen); PostgreSQL weigert dan de
    # constraint en de downgrade stopt zichtbaar.
    op.drop_constraint("ck_odoo_rekening_mapping_bron", TABEL, schema=SCHEMA, type_="check")
    op.create_check_constraint("ck_odoo_rekening_mapping_bron", TABEL, BRON_OUD, schema=SCHEMA)
    op.drop_constraint("ck_odoo_rekening_mapping_soort", TABEL, schema=SCHEMA, type_="check")
    op.create_check_constraint("ck_odoo_rekening_mapping_soort", TABEL, SOORT_OUD, schema=SCHEMA)
