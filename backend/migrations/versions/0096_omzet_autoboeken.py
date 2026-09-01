"""Omzet-autoboeken opt-in per administratie (GO Peter 01-09 — het aparte akkoord waar BESLISSINGEN
"Autoboek-afweging overige deterministische paden" (16-08) op wachtte; automatisering-first-patroon):
`platform.administratie.omzet_autoboeken_ingeschakeld`, default UIT, Beheerder-only. Ná intake/extractie
van een kassarapport boekt de motor uitsluitend automatisch als álles groen is (harde checks incl.
memoriaal-saldo-0, mapping-loze-categorie en marge-plausibiliteit; categorie-mapping volledig mens-
bevestigd; geen duplicaatsignaal per periode; geen open vraag/afwijzing); elk ander geval → werkvoorraad.
Schema-only.

Revision ID: 0096
Revises: 0095
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0096"
down_revision: str | None = "0095"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("omzet_autoboeken_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "omzet_autoboeken_ingeschakeld", schema="platform")
