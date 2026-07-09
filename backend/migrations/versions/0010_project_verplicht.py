"""Project-verplicht-instelling per administratie (design-pass controlescherm, taak 4): de
Project-kolom in het controlescherm is alleen zichtbaar/verplicht als de administratie dat zo
heeft ingesteld. Default UIT (bestaande administraties/tests blijven ongewijzigd werken zonder
project-koppeling); een Beheerder zet 'm aan per administratie (app/beheer).

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("project_verplicht", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "project_verplicht", schema="platform")
