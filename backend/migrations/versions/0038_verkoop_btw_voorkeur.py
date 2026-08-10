"""Onthouden btw-codekeuze bij echte ambiguïteit (blok A grote opdracht 2026-08-10).

Btw komt altijd uit de factuur (categorie + percentage, wettelijk leidend) en wordt in het
verkoopvoorstel vergrendeld. Alleen wanneer ≥ 2 actieve RLZ-tarieven dezelfde factuur-btw
dekken (bv. "NL, Hoog Tarief" naast "NL, Hoog Tarief (vooruit)") kiest een mens één keer per
administratie; die keuze landt hier per (categorie, canonieke fractie) — boekingsgeheugen-
patroon, nooit per factuur opnieuw. RLS op administratie (patroon 0035), GRANT zonder DELETE.

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "verkoop_btw_voorkeur",
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("btw_categorie", sa.Text(), nullable=False),
        sa.Column("percentage_fractie", sa.Numeric(6, 4), nullable=False),
        sa.Column("taxrate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("administratie_id", "btw_categorie", "percentage_fractie"),
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.verkoop_btw_voorkeur ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.verkoop_btw_voorkeur FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY verkoop_btw_voorkeur_scope ON boekhouding.verkoop_btw_voorkeur
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.verkoop_btw_voorkeur TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS verkoop_btw_voorkeur_scope ON boekhouding.verkoop_btw_voorkeur")
    op.drop_table("verkoop_btw_voorkeur", schema="boekhouding")
