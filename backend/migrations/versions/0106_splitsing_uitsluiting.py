"""Splitsing "nooit splitsen" per afzender (medewerker-wens 04-09, blok B — cases Universal Nederland
en Delta: mails waarvan de PDF één factuur MÉT bijlagen is (werkbonnen, urenstaten, pakbonnen) en
waarop de splitsings-AI toch factuurgrenzen voorstelt).

`boekhouding.intake_splitsing_uitsluiting`: één regel per (administratie, genormaliseerd afzenderadres).
De ADMINISTRATIE is de beheerplek (tab Algemeen van de administratie-detailpagina); de AFZENDER is de
sleutel bij de intake — dáár is de administratie nog onbekend, dus de intake toetst kantoorbreed op
`afzender_adres` over alle actieve regels. Deactiveren = `actief=false` + `verwijderd_op/door`; nooit
hard verwijderen (historie blijft, audit op beide kanten). Unieke ACTIEVE regel per
(administratie_id, afzender_adres) via een partiële unique index — een gedeactiveerde regel mag
opnieuw worden aangemaakt.

RLS: patroon `toewijzing_regel` (migratie 0028, `_rls_platform_breed`): het intake-pad draait in
`scoped_session(None)` (er is nog geen administratie) en moet ALLE actieve regels zien, exact zoals
het toewijzings-geheugen; de administratie-scope wordt server-side in de endpoints afgedwongen (zelfde
lijn als de toewijzingsregels). Géén DELETE-grant — nooit verwijderen. Schema-only, geen backfill.

Revision ID: 0106
Revises: 0105
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0106"
down_revision: str | None = "0105"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABEL = "intake_splitsing_uitsluiting"


def _rls_platform_breed(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (true)
        WITH CHECK (true)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        TABEL,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("afzender_adres", sa.Text(), nullable=False),
        sa.Column("leverancier_naam", sa.Text(), nullable=True),
        sa.Column("reden", sa.Text(), nullable=True),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("verwijderd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verwijderd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        f"ux_{TABEL}_actief",
        TABEL,
        ["administratie_id", "afzender_adres"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("actief"),
    )
    # Intake-leesroute: "is er een actieve regel voor dit afzenderadres" (kantoorbreed).
    op.create_index(
        f"ix_{TABEL}_afzender_actief",
        TABEL,
        ["afzender_adres"],
        schema="boekhouding",
        postgresql_where=sa.text("actief"),
    )
    _rls_platform_breed(TABEL)


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.{TABEL} FROM {APP_ROLE}")
    op.execute(f"DROP POLICY IF EXISTS {TABEL}_scope ON boekhouding.{TABEL}")
    op.drop_index(f"ix_{TABEL}_afzender_actief", table_name=TABEL, schema="boekhouding")
    op.drop_index(f"ux_{TABEL}_actief", table_name=TABEL, schema="boekhouding")
    op.drop_table(TABEL, schema="boekhouding")
