"""Verlegd-tarief deterministisch kiezen (blok 6 herstelrun "Basis eerst" 08-09-2026; bevinding 4c bundel 08-09:
Universal Steigerbouw heeft 12 `IsRelayed`-tarieven zonder favoriet, `verlegd_taxrate_voor` gaf None en de
Spot-Services-regel viel terug op een administratie-default "die toevallig klopt").

`platform.administratie.voorkeurs_verlegd_taxrate_id` (uuid, NULL): de door de Beheerder gekozen verlegd-code
(Instellingen › Administraties › tab Boeken & AI, alleen `IsRelayed`-tarieven uit `taxrate_cache`). Stap 1 van de
keuzevolgorde in `app/documenten/regel_prefill.py::bepaal_verlegd_taxrate` (voorkeur → meest gebruikt in de
RLZ-historie → één/NL/favoriet → administratie-default als die verlegd is → leeg). NULL = geen voorkeur — de
historie beslist. Bewust geen FK naar `taxrate_cache` (overleeft een sync-verdwijning; de service valideert tegen de
cache, zelfde patroon als `standaard_taxrate_id` in 0108). Schema-only, geen backfill.

Revision ID: 0123
Revises: 0122
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0123"
down_revision: str | None = "0122"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("voorkeurs_verlegd_taxrate_id", UUID(as_uuid=True), nullable=True),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "voorkeurs_verlegd_taxrate_id", schema="platform")
