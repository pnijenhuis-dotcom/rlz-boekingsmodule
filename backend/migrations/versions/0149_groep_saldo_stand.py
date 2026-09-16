"""Groepssaldi debiteuren/crediteuren per groep (Peter 16-09, "huidig saldo van de (cumulatieve) debiteuren en crediteuren
van de Kempengroep"): cache-tabel `boekhouding.groep_saldo_stand` — één rij per administratie per dag met het bruto-saldo
op de debiteuren-/crediteurenrekening(en), het intercompany-deel (open posten op groepsmaatschappijen) en de status van de
meting (ok / geen_rekening / ongeldig (webfilter) / fout / overgeslagen). Gevuld door de nachtelijke stap in `sync-alles`
(`app/groepen/saldi.py::meet_en_schrijf_alle`); gelezen door `GET /groepen/{id}/saldi` (kaart "Groepssaldi" op de
klantenlijst). RLS = scope-policy (zelfde vorm als werkvoorraad_teller_cache, 0136): een Boekhouding-rol ziet alleen de
administraties in eigen scope — de groepstotalen zeggen dan "N van M administraties in je scope". Schema-only.

Revision ID: 0149
Revises: 0148
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0149"
down_revision: str | None = "0148"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABEL = "groep_saldo_stand"


def upgrade() -> None:
    op.create_table(
        TABEL,
        sa.Column("administratie_id", sa.UUID(), sa.ForeignKey("platform.administratie.id"), primary_key=True),
        sa.Column("datum", sa.Date(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("debiteuren", sa.Numeric(14, 2), nullable=True),
        sa.Column("crediteuren", sa.Numeric(14, 2), nullable=True),
        sa.Column("ic_debiteuren", sa.Numeric(14, 2), nullable=True),
        sa.Column("ic_crediteuren", sa.Numeric(14, 2), nullable=True),
        sa.Column("debiteuren_rekening", sa.Text(), nullable=True),
        sa.Column("crediteuren_rekening", sa.Text(), nullable=True),
        sa.Column("gemeten_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('ok', 'geen_rekening', 'ongeldig', 'fout', 'overgeslagen')", name="ck_groep_saldo_stand_status"
        ),
        schema="boekhouding",
    )
    op.execute(f"ALTER TABLE boekhouding.{TABEL} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{TABEL} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {TABEL}_scope ON boekhouding.{TABEL}
        USING (
            administratie_id = platform.current_administratie_id()
            OR platform.current_actor_is_beheerder()
            OR EXISTS (
                SELECT 1 FROM platform.gebruiker_administratie ga
                WHERE ga.gebruiker_id = platform.current_actor_id()
                  AND ga.administratie_id = {TABEL}.administratie_id
            )
        )
        WITH CHECK (
            administratie_id = platform.current_administratie_id()
            OR platform.current_actor_is_beheerder()
        )
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{TABEL} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABEL}_scope ON boekhouding.{TABEL}")
    op.drop_table(TABEL, schema="boekhouding")
