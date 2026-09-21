"""Activa / MVA fase 1 (AKKOORD Peter 21-09 "activa, JA" op docs/ONTWERP_ACTIVA_MVA.md mét alle defaults §8; ontwerp §7 fase 1;
BESLISSINGEN "ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)").

1. `platform.grootboekrekening.is_activa` boolean NOT NULL default false — de MVA-uitkomst uit de bron: RLZ `Account.IsFixedAssetAccount`
   ÉN `AccountType` 3 ÉN code in de 0xxx-reeks (STAP-0 a9: de vlag alleen is te breed). De Ledgers-sync schrijft 'm bij élke sync
   (`sync/service._grootboek_waarden`); Odoo: `account_type == asset_fixed`.
2. `boekhouding.activa_instelling` — één rij per administratie (PK administratie_id): opt-in `automatisch_aanmaken_ingeschakeld`
   (default UIT, autoboek-patroon), `activeringsgrens` (default 450,00 excl. btw), de uit RLZ gelezen `grens_rlz`
   (`AdministrationSettings.FixedAssetAlertAmount`, bron wint als gevuld) + `grens_rlz_gelezen_op`, `termijnen` JSONB (maanden per
   rekeningcategorie; leeg = ontwerp-defaults §3), `afschrijving_ledgers` JSONB (afschrijvingsrekening per categorie, ledger-id als
   tekst; leeg = de mens kiest op de kaart), register-probe `register_leesbaar`/`register_geprobeerd_op`/`register_fout`
   (Universal 403 = "recht ontbreekt", nooit stil).
3. `boekhouding.activum_koppeling` — het eigen koppelrecord document/regel ↔ RLZ-activum (RLZ kent geen regel-koppeling; STAP-0 a2):
   status `gepland` (mens zei "aanmaken" vóór het boeken) | `aangemaakt` (RLZ `FixedAssets` PUT + terug-lezen gelukt) |
   `overgeslagen` (mens: niet activeren, mét reden) | `mislukt` (RLZ-write faalde, zichtbaar, retry) | `beoordelen` (factuur
   gestorneerd — activum NIET verwijderen, mens beoordeelt in RLZ). Uniek per (document, regel, boek_cyclus). RLS op administratie
   (0167-patroon), app-rol SELECT/INSERT/UPDATE — geen DELETE (niets verdwijnt stil).
Schema-only, pure DDL; geen data-wijziging.

Revision ID: 0168
Revises: 0167
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0168"
down_revision: str | None = "0167"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
INSTELLING = "activa_instelling"
KOPPELING = "activum_koppeling"
STATUSSEN = ("gepland", "aangemaakt", "overgeslagen", "mislukt", "beoordelen")
HERKOMSTEN = ("mens", "automatisch")


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
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    op.add_column(
        "grootboekrekening",
        sa.Column("is_activa", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )
    op.create_table(
        INSTELLING,
        sa.Column("administratie_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "automatisch_aanmaken_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("activeringsgrens", sa.Numeric(12, 2), nullable=False, server_default="450.00"),
        sa.Column("grens_rlz", sa.Numeric(12, 2), nullable=True),
        sa.Column("grens_rlz_gelezen_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("termijnen", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column(
            "afschrijving_ledgers", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("register_leesbaar", sa.Boolean(), nullable=True),
        sa.Column("register_geprobeerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("register_fout", sa.Text(), nullable=True),
        sa.Column("gewijzigd_door", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("administratie_id", name="pk_activa_instelling"),
        sa.ForeignKeyConstraint(
            ["administratie_id"], ["platform.administratie.id"], name="fk_activa_instelling_administratie"
        ),
        sa.ForeignKeyConstraint(["gewijzigd_door"], ["platform.gebruiker.id"], name="fk_activa_instelling_gewijzigd_door"),
        schema="boekhouding",
    )
    _rls_op_administratie(INSTELLING)

    op.create_table(
        KOPPELING,
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("administratie_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("regel_volgnummer", sa.Integer(), nullable=False),
        sa.Column("boek_cyclus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("herkomst", sa.Text(), nullable=False, server_default="mens"),
        sa.Column("rlz_fixed_asset_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("rlz_receipt_number", sa.Text(), nullable=True),
        sa.Column("categorie", sa.Text(), nullable=False),
        sa.Column("termijn_maanden", sa.Integer(), nullable=False),
        sa.Column("methode_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("methode_naam", sa.Text(), nullable=True),
        sa.Column("aanschafwaarde", sa.Numeric(14, 2), nullable=False),
        sa.Column("restwaarde", sa.Numeric(14, 2), nullable=False, server_default="0.00"),
        sa.Column("aanschafdatum", sa.Date(), nullable=False),
        sa.Column("omschrijving", sa.Text(), nullable=False),
        sa.Column("balans_ledger_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("afschrijving_ledger_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("reden", sa.Text(), nullable=True),
        sa.Column("door", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_activum_koppeling"),
        sa.ForeignKeyConstraint(
            ["administratie_id"], ["platform.administratie.id"], name="fk_activum_koppeling_administratie"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["boekhouding.document.id"], name="fk_activum_koppeling_document"),
        sa.ForeignKeyConstraint(["door"], ["platform.gebruiker.id"], name="fk_activum_koppeling_door"),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in STATUSSEN) + ")", name="ck_activum_koppeling_status"
        ),
        sa.CheckConstraint(
            "herkomst IN (" + ", ".join(f"'{h}'" for h in HERKOMSTEN) + ")", name="ck_activum_koppeling_herkomst"
        ),
        sa.CheckConstraint("aanschafwaarde >= 0", name="ck_activum_koppeling_aanschafwaarde"),
        sa.CheckConstraint("termijn_maanden > 0", name="ck_activum_koppeling_termijn"),
        sa.UniqueConstraint(
            "document_id", "regel_volgnummer", "boek_cyclus", name="ux_activum_koppeling_document_regel_cyclus"
        ),
        schema="boekhouding",
    )
    op.create_index("ix_activum_koppeling_administratie_id", KOPPELING, ["administratie_id"], schema="boekhouding")
    op.create_index("ix_activum_koppeling_status", KOPPELING, ["administratie_id", "status"], schema="boekhouding")
    _rls_op_administratie(KOPPELING)


def downgrade() -> None:
    op.drop_index("ix_activum_koppeling_status", table_name=KOPPELING, schema="boekhouding")
    op.drop_index("ix_activum_koppeling_administratie_id", table_name=KOPPELING, schema="boekhouding")
    op.drop_table(KOPPELING, schema="boekhouding")
    op.drop_table(INSTELLING, schema="boekhouding")
    op.drop_column("grootboekrekening", "is_activa", schema="platform")
