"""Odoo-slotstuk 04-09 (C1) — hervertaling van OPEN boekvoorstellen bij een overstap RLZ → Odoo.

`boekhouding.boekvoorstel_regel.overstap_vertaling` (JSONB, NULL): het spoor van `app/odoo/hervertaling.py` per
regel — per veld grootboek/btw/project {van_id, van_code, van_naam, naar_id, naar_code, naar_naam} (vertaald via de
mensbevestigde mapping van 0111) óf {…, naar_id: None, reden} (geen Odoo-tegenhanger → veld leeg gelaten), plus `op`.
NULL = niet hervertaald (RLZ-administraties, nieuwe Odoo-administraties, regels ná de overstap). De controleur ziet
per veld een chip; de eerstvolgende PUT schrijft de regels opnieuw zonder dit spoor (bestaand delete+insert-patroon).

Schema-only, geen backfill. RLS (policy `boekvoorstel_regel_scope` via document, 0008) en rechten ongewijzigd.

Revision ID: 0112
Revises: 0111
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0112"
down_revision: str | None = "0111"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "boekvoorstel_regel",
        sa.Column("overstap_vertaling", JSONB(none_as_null=True), nullable=True),
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_column("boekvoorstel_regel", "overstap_vertaling", schema="boekhouding")
