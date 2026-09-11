"""Werkvoorraad-tellers als cache (blok 6 run 11-09 middag).

Aanleiding (Cloud Logging 08-09 t/m 11-09): `GET /werkvoorraad/overzicht` p50 2,8 s / p95 6,1 s bij 71 administraties —
een lus per administratie met een `scoped_session`-wissel en ±10 queries (status-GROUP BY + zeven signaaltellers, waarvan
drie Python-motoren). Schaalregel 2 → 2000: het aantal statements per request moet CONSTANT zijn.

Deze tabel is de cache: één rij per (administratie, teller). Gevuld/bijgewerkt door `app/werkvoorraad/tellers.py`:
(a) incrementeel bij élke statusovergang van een document (de statusmachine-schrijver), (b) nachtelijk volledig herrekend
in `sync-alles` (`werkvoorraad-tellers-herrekenen`), (c) fail-safe: ontbreekt een rij, dan telt de leesroute direct en
maakt de rij aan — er wordt nooit een lege teller getoond.

RLS: de leesroute leest ÁLLE administraties in de scope van de actor in één statement (`scoped_session(None,
actor_id=…)`). De USING-clause laat daarom naast de gescoopte administratie en de Beheerder-bypass ook rijen zien van
administraties waarop de actor een `gebruiker_administratie`-rij heeft (zelf-leesbaar sinds 0007 — een zelf-referentie,
geen cross-tenant-lek). WITH CHECK blijft strikt: schrijven alleen in de gescoopte administratie (of als Beheerder).

Revision ID: 0136
Revises: 0135
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0136"
down_revision: str | None = "0135"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "werkvoorraad_teller_cache",
        sa.Column(
            "administratie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.administratie.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("teller", sa.Text(), primary_key=True, nullable=False),
        sa.Column("waarde", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("waarde >= 0", name="ck_werkvoorraad_teller_cache_waarde"),
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.werkvoorraad_teller_cache ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.werkvoorraad_teller_cache FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY werkvoorraad_teller_cache_scope ON boekhouding.werkvoorraad_teller_cache
        USING (
            administratie_id = platform.current_administratie_id()
            OR platform.current_actor_is_beheerder()
            OR EXISTS (
                SELECT 1 FROM platform.gebruiker_administratie ga
                WHERE ga.gebruiker_id = platform.current_actor_id()
                  AND ga.administratie_id = werkvoorraad_teller_cache.administratie_id
            )
        )
        WITH CHECK (
            administratie_id = platform.current_administratie_id()
            OR platform.current_actor_is_beheerder()
        )
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON boekhouding.werkvoorraad_teller_cache TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS werkvoorraad_teller_cache_scope ON boekhouding.werkvoorraad_teller_cache")
    op.drop_table("werkvoorraad_teller_cache", schema="boekhouding")
