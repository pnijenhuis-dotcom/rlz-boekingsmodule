"""Eigenaar per administratie (vragenworkflow, mockup Instellingen: "Eigenaar (krijgt vragen)").

De eigenaar is de default-toewijzing voor nieuwe vragen over documenten van deze administratie
(mockup #vraagmodal: "M. de Boer — eigenaar Kempen Vastgoed B.V. (standaard)"). Nullable: bestaande
administraties hebben nog geen eigenaar — vraag stellen vereist dan een expliciete toewijzing
(zichtbare fout i.p.v. een stille default, zie app/documenten/vragen.py). Geen aparte vlag of
koppeltabel: één eigenaar per administratie, precies wat de mockup toont.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column(
            "eigenaar_gebruiker_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.gebruiker.id"),
            nullable=True,
        ),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "eigenaar_gebruiker_id", schema="platform")
