"""Staande goedkeuring: voorstel-stilte per accordeur+leverancier + nooit voorstellen (blok 7 run 11-09 middag).

Aanleiding (feedback accordeur-app, casus Lusso): 12 gelijke facturen voor 12 chalets in één week gaven 12× de vraag
"voortaan automatisch akkoord?". Het voorstel komt sinds dit blok alleen bij een PERIODIEK patroon (gedeelde motor
`app/terugkerend/service.py::classificeer_reeks`) en de vraag wordt één keer gesteld: "nee"/"niet nu" = 90 dagen stil,
"nooit voor deze leverancier" = uitzondering (accordeur zelf in de app, Beheerder administratiebreed in de kantoor-web).

`boekhouding.staande_goedkeuring_voorstel_stil`: accordeur (NULL = alle accordeurs van de administratie), administratie,
leverancier-sleutel (vendor_id + naam op zet-moment), soort `stil_tot`/`nooit`, stil_tot, reden, actief + opgeheven
door/op (opheffen = actief=False, nooit een DELETE). RLS op administratie zoals de andere accordering-tabellen, FORCE.
Schema-only (pure DDL); geen backfill — bestaande staande goedkeuringen blijven ongewijzigd.

Revision ID: 0134
Revises: 0133
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0134"
down_revision: str | None = "0133"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
TABEL = "staande_goedkeuring_voorstel_stil"


def _rls_op_administratie(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    # Geen DELETE-grant: opheffen = actief=False (niets verdwijnt stil).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        TABEL,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("accordeur_gebruiker_id", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("leverancier_naam", sa.Text(), nullable=True),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("stil_tot", sa.Date(), nullable=True),
        sa.Column("reden", sa.Text(), nullable=True),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("opgeheven_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("opgeheven_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("soort IN ('stil_tot', 'nooit')", name="ck_staande_goedkeuring_voorstel_stil_soort"),
        schema="boekhouding",
    )
    op.create_index(f"ix_{TABEL}_administratie_id", TABEL, ["administratie_id"], schema="boekhouding")
    op.create_index(f"ix_{TABEL}_vendor", TABEL, ["administratie_id", "vendor_id"], schema="boekhouding")
    _rls_op_administratie(TABEL)


def downgrade() -> None:
    op.drop_table(TABEL, schema="boekhouding")
