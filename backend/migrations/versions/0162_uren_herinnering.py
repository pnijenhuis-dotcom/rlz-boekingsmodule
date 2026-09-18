"""Veld-app UX run B (akkoord Peter 18-09 "alle punten"), punt 4 — dag-einde herinnering "Nog geen uren voor vandaag".

- `platform.administratie.uren_herinnering_tijd` TIME NULL — tijdstip (Europe/Amsterdam) waarná de herinnering mag; NULL =
  de code-default 16:30 (`app/uren/herinnering.py::STANDAARD_HERINNERING_TIJD`). Beheerder-only via
  `PUT /uren/beheer/herinnering-tijd/{aid}` (Instellingen › administratie › Uren & materiaal), audit oud→nieuw.
- `platform.gebruiker.uren_herinnering_uit` BOOLEAN NOT NULL DEFAULT false — opt-out PER GEBRUIKER (beslispunt: niet per
  toestel) via `PUT /uren/zzp/herinnering` (⚙ Toegang in de veld-app).
- `boekhouding.uren_herinnering` — de dagrij-claim: hooguit één herinnering per veldwerker per NL-kalenderdag over álle
  administraties (UNIQUE gebruiker_id + datum), `kanaal` push | e-mail | geen_kanaal, `administratie_id` = de administratie
  waarvan de tijd gold (NULL toegestaan). Patroon `planning_signaal`/`dossier_herinnering`: claim vóór verzenden, idempotent.
  RLS: FORCE + platformbrede systeem-/Beheerder-policy (de job draait als systeem-actor over alle administraties heen;
  de rij is per gebruiker, niet per administratie) — zelfde lijn als `accordeur_herinnering`. Geen DELETE-grant.
Schema-only, pure DDL.

Revision ID: 0162
Revises: 0161
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0162"
down_revision: str | None = "0161"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABEL = "uren_herinnering"


def upgrade() -> None:
    op.add_column("administratie", sa.Column("uren_herinnering_tijd", sa.Time(), nullable=True), schema="platform")
    op.add_column(
        "gebruiker",
        sa.Column("uren_herinnering_uit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="platform",
    )
    op.create_table(
        TABEL,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=True),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("verzonden_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("kanaal", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.UniqueConstraint("gebruiker_id", "datum", name=f"uq_{TABEL}_gebruiker_datum"),
        schema="boekhouding",
    )
    op.execute(f"ALTER TABLE boekhouding.{TABEL} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{TABEL} FORCE ROW LEVEL SECURITY")
    # Per-gebruiker-tabel zonder administratie-scope: alleen de systeem-actor (job) en een Beheerder lezen/schrijven;
    # een veldwerker leest uitsluitend zijn eigen rijen (opt-out-scherm toont "laatst herinnerd").
    op.execute(
        f"""
        CREATE POLICY {TABEL}_toegang ON boekhouding.{TABEL}
        USING (
            platform.current_actor_is_beheerder()
            OR platform.current_actor_id() = '00000000-0000-0000-0000-000000000001'::uuid
            OR gebruiker_id = platform.current_actor_id()
        )
        WITH CHECK (
            platform.current_actor_is_beheerder()
            OR platform.current_actor_id() = '00000000-0000-0000-0000-000000000001'::uuid
        )
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{TABEL} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table(TABEL, schema="boekhouding")
    op.drop_column("gebruiker", "uren_herinnering_uit", schema="platform")
    op.drop_column("administratie", "uren_herinnering_tijd", schema="platform")
