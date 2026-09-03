"""Odoo-adapter fase 1, blok 0 — boekhoud-backend-port per administratie (Platform-besluit 0016,
STAP-0 `verkenning/odoo-verkenning.md` 02-09, besluiten Peter 02-09):

- `platform.administratie.boekhoud_backend` ('rlz' | 'odoo', default 'rlz'): uitsluitend de
  routeringssleutel voor de adapter-registry (`app/backends/registry.py`) — het domein vertakt er
  nooit op. Bestaande administraties blijven 'rlz' (server_default, geen backfill).
- `platform.odoo_koppeling`: koppeling + credential per Odoo-administratie — URL, de COMPANY (heilig:
  élke write draagt 'm expliciet), API-key envelope-versleuteld (zelfde patroon als rlz_credential),
  de bij de probe vastgestelde dagboeken (inkoop/memoriaal/verkoop), het analytic-plan "Project",
  het probe-rapport en de sleutel-vervaldatum (Odoo: max 3 maanden → rotatie-klikpunt).
- `boekhouding.odoo_id_koppeling`: Odoo-int-id ↔ lokale UUID per (administratie, model) — de caches
  (grootboek/btw/crediteuren/projecten) blijven UUID-gesleuteld, de adapter vertaalt.
- `boekhouding.odoo_document_koppeling`: (document, boek_cyclus, soort) → account.move (id, naam,
  state, company) — idempotentie-anker (Odoo kent geen client-GUID-PUT) + kruisverwijzing reversal.
- `boekhouding.odoo_product_koppeling`: materiaalcatalogus-product ↔ product.product (brug voor
  regelniveau-data in Odoo, eis Peter/Jarvis).
- `boekhouding.boekvoorstel.betalingskenmerk`: nieuw kopveld (Odoo `payment_reference`; RLZ heeft
  het niet — blijft daar ongebruikt). Extractie via het sentinel-patroon, geen schema-union.
RLS per administratie op de boekhouding-tabellen (patroon 0095); géén DELETE-grant. Schema-only.

Revision ID: 0101
Revises: 0100
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID

revision: str = "0101"
down_revision: str | None = "0100"
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
    op.add_column(
        "administratie",
        sa.Column("boekhoud_backend", sa.String(length=16), nullable=False, server_default="rlz"),
        schema="platform",
    )
    op.create_check_constraint(
        "ck_administratie_boekhoud_backend",
        "administratie",
        "boekhoud_backend IN ('rlz', 'odoo')",
        schema="platform",
    )

    op.create_table(
        "odoo_koppeling",
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("odoo_url", sa.Text(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("company_naam", sa.Text(), nullable=True),
        sa.Column("api_gebruiker", sa.Text(), nullable=True),
        sa.Column("api_key_ciphertext", BYTEA(), nullable=False),
        sa.Column("wrapped_data_key", BYTEA(), nullable=False),
        sa.Column("api_key_verloopt_op", sa.Date(), nullable=True),
        sa.Column("journal_purchase_id", sa.Integer(), nullable=True),
        sa.Column("journal_general_id", sa.Integer(), nullable=True),
        sa.Column("journal_sale_id", sa.Integer(), nullable=True),
        sa.Column("analytic_plan_id", sa.Integer(), nullable=True),
        sa.Column("probe_rapport", JSONB(), nullable=True),
        sa.Column("probe_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("company_id > 0", name="ck_odoo_koppeling_company"),
        schema="platform",
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform.odoo_koppeling TO {APP_ROLE}")

    op.create_table(
        "odoo_id_koppeling",
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True),
        sa.Column("model", sa.String(length=64), primary_key=True),
        sa.Column("odoo_id", sa.Integer(), primary_key=True),
        sa.Column("lokaal_id", UUID(as_uuid=True), nullable=False),
        sa.Column("naam", sa.Text(), nullable=True),
        sa.Column("laatst_gezien_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("administratie_id", "lokaal_id", name="uq_odoo_id_koppeling_lokaal"),
        schema="boekhouding",
    )
    _rls("odoo_id_koppeling")

    op.create_table(
        "odoo_document_koppeling",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("boek_cyclus", sa.Integer(), nullable=False),
        sa.Column("soort", sa.String(length=16), nullable=False),
        sa.Column("odoo_move_id", sa.Integer(), nullable=False),
        sa.Column("odoo_naam", sa.Text(), nullable=True),
        sa.Column("odoo_move_type", sa.String(length=16), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reversal_van_move_id", sa.Integer(), nullable=True),
        sa.Column("detail", JSONB(), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "administratie_id", "document_id", "boek_cyclus", "soort", name="uq_odoo_document_koppeling_cyclus"
        ),
        sa.CheckConstraint("soort IN ('boeking', 'tegenboeking')", name="ck_odoo_document_koppeling_soort"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_odoo_document_koppeling_administratie_id",
        "odoo_document_koppeling",
        ["administratie_id"],
        schema="boekhouding",
    )
    op.create_index(
        "ix_odoo_document_koppeling_move", "odoo_document_koppeling", ["company_id", "odoo_move_id"], schema="boekhouding"
    )
    _rls("odoo_document_koppeling")

    op.create_table(
        "odoo_product_koppeling",
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True),
        sa.Column(
            "materiaal_product_id",
            UUID(as_uuid=True),
            sa.ForeignKey("boekhouding.materiaal_product.id"),
            primary_key=True,
        ),
        sa.Column("odoo_product_id", sa.Integer(), nullable=False),
        sa.Column("odoo_template_id", sa.Integer(), nullable=True),
        sa.Column("default_code", sa.Text(), nullable=True),
        sa.Column("naam", sa.Text(), nullable=True),
        sa.Column("bron", sa.String(length=16), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("bron IN ('gevonden', 'aangemaakt')", name="ck_odoo_product_koppeling_bron"),
        schema="boekhouding",
    )
    _rls("odoo_product_koppeling")

    op.add_column("boekvoorstel", sa.Column("betalingskenmerk", sa.Text(), nullable=True), schema="boekhouding")


def downgrade() -> None:
    op.drop_column("boekvoorstel", "betalingskenmerk", schema="boekhouding")
    for tabel in ("odoo_product_koppeling", "odoo_document_koppeling", "odoo_id_koppeling"):
        op.execute(f"DROP POLICY IF EXISTS {tabel}_scope ON boekhouding.{tabel}")
    op.drop_index("ix_odoo_document_koppeling_move", table_name="odoo_document_koppeling", schema="boekhouding")
    op.drop_index(
        "ix_odoo_document_koppeling_administratie_id", table_name="odoo_document_koppeling", schema="boekhouding"
    )
    op.drop_table("odoo_product_koppeling", schema="boekhouding")
    op.drop_table("odoo_document_koppeling", schema="boekhouding")
    op.drop_table("odoo_id_koppeling", schema="boekhouding")
    op.execute(f"REVOKE ALL ON platform.odoo_koppeling FROM {APP_ROLE}")
    op.drop_table("odoo_koppeling", schema="platform")
    op.drop_constraint("ck_administratie_boekhoud_backend", "administratie", schema="platform", type_="check")
    op.drop_column("administratie", "boekhoud_backend", schema="platform")
