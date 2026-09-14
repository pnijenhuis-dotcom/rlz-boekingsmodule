"""Odoo-koppelwizard nazorg 14-09 — failsafe dubbele Odoo-koppeling, laag 1 (database).

Besluit Peter 14-09: één Odoo-company (per host) hoort bij precies één administratie in de module — een tweede
administratie op dezelfde company zou de replay/reconciliatie breken (Vastgoedgroep Nederland company 6 is het
migratiedoel van run 2 en mocht in de wizard gewoon aangevinkt worden). Unieke index over álle koppeling-rijen
(leesbron, volledige backend, migratiedoel) op (host genormaliseerd, company_id); de host-uitdrukking is dezelfde als
`app/odoo/ids.py::odoo_host` (`ODOO_HOST_SQL`). Geen partial index: een koppeling-rij kent geen inactieve stand en
een gearchiveerde administratie houdt haar claim (sentinel-`rlz_admin_id` is al UNIQUE) — dearchiveren is de weg.
De 409 in de service is de normale weg; deze index is het vangnet.

Schema-only.

Revision ID: 0140
Revises: 0139
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0140"
down_revision: str | None = "0139"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

INDEX = "uq_odoo_koppeling_host_company"
# Identiek aan app/odoo/ids.py::ODOO_HOST_SQL (bewust uitgeschreven: een migratie importeert geen app-code).
HOST_SQL = "lower(split_part(split_part(odoo_url, '//', 2), '/', 1))"


def upgrade() -> None:
    op.create_index(INDEX, "odoo_koppeling", [sa.text(HOST_SQL), "company_id"], unique=True, schema="platform")


def downgrade() -> None:
    op.drop_index(INDEX, table_name="odoo_koppeling", schema="platform")
