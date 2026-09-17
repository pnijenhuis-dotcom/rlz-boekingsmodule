"""Klant-accordering — accorderingsroute per LEVERANCIER (vraag Peter 17-09: "kan 1 accordeur facturen van 1 specifieke
leverancier zien, de rest niet?"; verduidelijking: "1 losse accordeur die alleen de aangevinkte leveranciers ziet — dus NIET
langs de andere accordeurs" = de leveranciersroute VERVANGT de administratieroute voor die leveranciers, zelfde patroon als de
afdelingsroute van migratie 0084). Schema-only, pure DDL:
- `boekhouding.accordering_leverancier_route` — één route per administratie mét naam; append-only (deactiveren, nooit verwijderen).
- `boekhouding.accordering_leverancier_route_vendor` — de aangevinkte leveranciers (crediteurrecords; matching in de code loopt
  over de crediteur-IDENTITEIT via `crediteuren/voorkeur.py`); een leverancier zit in hooguit één actieve route (partiële
  unieke index) → 409 mét reden in de service.
- `boekhouding.accordering_laag.leverancier_route_id` — NULL = administratie-/afdelingsroute (bestaand), gevuld = laag van die
  leveranciersroute (meerdere lagen mét bedragdrempel per route mogelijk).
RLS per administratie + GRANT zonder DELETE (0084-patroon).

Revision ID: 0156
Revises: 0155
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0156"
down_revision: str | None = "0155"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def _rls(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        "accordering_leverancier_route",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gedeactiveerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gedeactiveerd_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_accordering_leverancier_route_administratie_id", "accordering_leverancier_route", ["administratie_id"], schema="boekhouding"
    )
    op.create_table(
        "accordering_leverancier_route_vendor",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("route_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.accordering_leverancier_route.id"), nullable=False),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("herkomst", sa.Text(), nullable=False, server_default="handmatig"),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gedeactiveerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gedeactiveerd_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_accordering_leverancier_route_vendor_route_id", "accordering_leverancier_route_vendor", ["route_id"], schema="boekhouding"
    )
    op.create_index(
        "ux_accordering_leverancier_route_vendor_actief",
        "accordering_leverancier_route_vendor",
        ["administratie_id", "vendor_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("actief"),
    )
    _rls("accordering_leverancier_route")
    _rls("accordering_leverancier_route_vendor")
    op.add_column(
        "accordering_laag",
        sa.Column(
            "leverancier_route_id",
            UUID(as_uuid=True),
            sa.ForeignKey("boekhouding.accordering_leverancier_route.id"),
            nullable=True,
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ix_accordering_laag_leverancier_route_id", "accordering_laag", ["leverancier_route_id"], schema="boekhouding"
    )


def downgrade() -> None:
    op.drop_index("ix_accordering_laag_leverancier_route_id", table_name="accordering_laag", schema="boekhouding")
    op.drop_column("accordering_laag", "leverancier_route_id", schema="boekhouding")
    op.drop_index("ux_accordering_leverancier_route_vendor_actief", table_name="accordering_leverancier_route_vendor", schema="boekhouding")
    op.drop_index("ix_accordering_leverancier_route_vendor_route_id", table_name="accordering_leverancier_route_vendor", schema="boekhouding")
    op.drop_table("accordering_leverancier_route_vendor", schema="boekhouding")
    op.drop_index("ix_accordering_leverancier_route_administratie_id", table_name="accordering_leverancier_route", schema="boekhouding")
    op.drop_table("accordering_leverancier_route", schema="boekhouding")
