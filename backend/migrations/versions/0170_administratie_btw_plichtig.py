"""Btw-plichtig per administratie (BUG Peter 22-09, casus Vastgoedgroep Nederland / Studio Lacy Lion 2026-042 →
RLZ-04-00000925: de module splitste bruto/btw, RLZ boekte in de niet-btw-plichtige administratie alleen het netto →
€ 322,38 te weinig betaald; BESLISSINGEN "BTW-PLICHTIG PER ADMINISTRATIE — NIET-PLICHTIG = BTW IN DE KOSTEN, HARDE CHECK
(Peter 22-09)").

`platform.administratie.btw_plichtig` (default TRUE — bestaande administraties gedragen zich ongewijzigd),
`btw_plichtig_bron` ('rlz' | 'mens' | NULL = nog nooit bevestigd), `btw_plichtig_gewijzigd_op`, en het RLZ-signaal
`btw_plichtig_rlz_signaal` (= `AdministrationSettings.EnableTaxReporting`, gelezen in de nachtelijke identiteit-sync;
NULL = nog niet gelezen/Odoo) + `btw_plichtig_rlz_gezien_op`. Het signaal `false` zet het kenmerk NOOIT zelf op false
(een administratie kan de aangifte buiten RLZ doen) — het voedt de detector "bevestig btw-status"; `true` bevestigt
btw-plichtig mét bron 'rlz'. Schema-only (pure DDL); VGG op false is een data-stap (CLI `btw-plichtig-zetten` / UI).

Revision ID: 0170
Revises: 0169
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0170"
down_revision: str | None = "0169"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("btw_plichtig", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="platform",
    )
    op.add_column("administratie", sa.Column("btw_plichtig_bron", sa.Text(), nullable=True), schema="platform")
    op.add_column(
        "administratie",
        sa.Column("btw_plichtig_gewijzigd_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.add_column(
        "administratie", sa.Column("btw_plichtig_rlz_signaal", sa.Boolean(), nullable=True), schema="platform"
    )
    op.add_column(
        "administratie",
        sa.Column("btw_plichtig_rlz_gezien_op", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.create_check_constraint(
        "ck_administratie_btw_plichtig_bron",
        "administratie",
        "btw_plichtig_bron IS NULL OR btw_plichtig_bron IN ('rlz', 'mens')",
        schema="platform",
    )


def downgrade() -> None:
    op.drop_constraint("ck_administratie_btw_plichtig_bron", "administratie", schema="platform", type_="check")
    for kolom in (
        "btw_plichtig_rlz_gezien_op",
        "btw_plichtig_rlz_signaal",
        "btw_plichtig_gewijzigd_op",
        "btw_plichtig_bron",
        "btw_plichtig",
    ):
        op.drop_column("administratie", kolom, schema="platform")
