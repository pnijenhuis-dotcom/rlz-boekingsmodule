"""Steigerbouw-run blok A (feedbackrondes Peter 23/24-08): ZZP-dossier per veldwerker +
handhaving + KvK/btw + signaal >12 uur per dag.

- `dossier_documenttype`: documenttypen als Beheerder-instelling per administratie (default-set
  kopie ID / steigerpas / VCA vol / AVB / KvK-uittreksel — code-constanten in app/uren/dossier.py,
  virtueel zolang er geen rijen zijn; de eerste PUT persisteert de volledige set).
- `dossier_document`: append-only uploads (kantoor én veldwerker/app), status ter_controle →
  goedgekeurd / afgewezen (reden verplicht, DB-CHECK). Nooit DELETE: een vervanging is een
  nieuwe rij, het "huidige" document per type = de jongste upload.
- `veldwerker_dossier`: stand per (administratie, veldwerker): herinnering-teller ("N van 3"),
  blokkade-vlag (ná de 3e herinnering; deblokkade zodra alle verplichte documenten geüpload zijn,
  ter controle telt; afwijzing heractiveert) + KvK-/btw-bedrijfsgegevens (mens bevestigt).
- `dossier_herinnering`: één rij per (veldwerker, dag) = de dagrem (max 1/dag), claim-vóór-
  verzenden zoals accordering.herinnering.
- `platform.administratie.uren_dagmax_uren`: drempel voor het >12-uur-per-dag-signaal (A6),
  default 12, per administratie instelbaar.

RLS per administratie (patroon 0056/0060), GRANT zonder DELETE — niets verdwijnt stil; élke
mutatie loopt via de service mét audit_event (actor + oud→nieuw, due-diligence-eis 24-08).

Revision ID: 0072
Revises: 0071
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0072"
down_revision: str | None = "0071"
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
        sa.Column("uren_dagmax_uren", sa.Numeric(precision=4, scale=2), server_default=sa.text("12"), nullable=False),
        schema="platform",
    )
    op.create_check_constraint(
        "ck_administratie_uren_dagmax", "administratie", "uren_dagmax_uren > 0 AND uren_dagmax_uren <= 24", schema="platform"
    )

    op.create_table(
        "dossier_documenttype",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("verplicht", sa.Boolean(), nullable=False),
        sa.Column("geldig_tot_vereist", sa.Boolean(), nullable=False),
        sa.Column("bsn_gevoelig", sa.Boolean(), nullable=False),
        sa.Column("volgorde", sa.Integer(), nullable=False),
        sa.Column("actief", sa.Boolean(), nullable=False),
        sa.Column("bijgewerkt_door", sa.UUID(), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("code ~ '^[a-z0-9_]{2,40}$'", name="ck_dossier_documenttype_code"),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["bijgewerkt_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("administratie_id", "code", name="uq_dossier_documenttype_code"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_dossier_documenttype_administratie_id", "dossier_documenttype", ["administratie_id"], schema="boekhouding"
    )
    _rls("dossier_documenttype")

    op.create_table(
        "veldwerker_dossier",
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("gebruiker_id", sa.UUID(), nullable=False),
        sa.Column("herinneringen_teller", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("laatste_herinnering_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("geblokkeerd", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("geblokkeerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gedeblokkeerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kvk_nummer", sa.Text(), nullable=True),
        sa.Column("btw_nummer", sa.Text(), nullable=True),
        sa.Column("kvk_naam", sa.Text(), nullable=True),
        sa.Column("kvk_plaats", sa.Text(), nullable=True),
        sa.Column("kvk_rechtsvorm", sa.Text(), nullable=True),
        sa.Column("kvk_bevestigd_door", sa.UUID(), nullable=True),
        sa.Column("kvk_bevestigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("herinneringen_teller >= 0", name="ck_veldwerker_dossier_teller"),
        sa.CheckConstraint("kvk_nummer IS NULL OR kvk_nummer ~ '^[0-9]{8}$'", name="ck_veldwerker_dossier_kvk"),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["gebruiker_id"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(["kvk_bevestigd_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("administratie_id", "gebruiker_id"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_veldwerker_dossier_administratie_id", "veldwerker_dossier", ["administratie_id"], schema="boekhouding"
    )
    _rls("veldwerker_dossier")

    op.create_table(
        "dossier_document",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("gebruiker_id", sa.UUID(), nullable=False),
        sa.Column("type_code", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("geldig_tot", sa.Date(), nullable=True),
        sa.Column("opslag_pad", sa.Text(), nullable=False),
        sa.Column("bestandsnaam", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("geupload_door", sa.UUID(), nullable=False),
        sa.Column("geupload_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("beoordeeld_door", sa.UUID(), nullable=True),
        sa.Column("beoordeeld_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("afwijs_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('ter_controle', 'goedgekeurd', 'afgewezen')", name="ck_dossier_document_status"),
        sa.CheckConstraint("bron IN ('kantoor', 'app')", name="ck_dossier_document_bron"),
        sa.CheckConstraint(
            "status <> 'afgewezen' OR (afwijs_reden IS NOT NULL AND length(btrim(afwijs_reden)) > 0)",
            name="ck_dossier_document_afwijs_reden",
        ),
        sa.CheckConstraint(
            "(status = 'ter_controle') = (beoordeeld_op IS NULL)", name="ck_dossier_document_beoordeeld"
        ),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["gebruiker_id"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(["geupload_door"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(["beoordeeld_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index("ix_dossier_document_administratie_id", "dossier_document", ["administratie_id"], schema="boekhouding")
    op.create_index(
        "ix_dossier_document_veldwerker",
        "dossier_document",
        ["administratie_id", "gebruiker_id", "type_code"],
        schema="boekhouding",
    )
    _rls("dossier_document")

    op.create_table(
        "dossier_herinnering",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("gebruiker_id", sa.UUID(), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("volgnummer", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("kanaal", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("verzonden_door", sa.UUID(), nullable=False),
        sa.Column("verzonden_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('bezig', 'verzonden', 'mislukt', 'overgeslagen')", name="ck_dossier_herinnering_status"
        ),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["gebruiker_id"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(["verzonden_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("administratie_id", "gebruiker_id", "datum", name="uq_dossier_herinnering_dag"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_dossier_herinnering_administratie_id", "dossier_herinnering", ["administratie_id"], schema="boekhouding"
    )
    _rls("dossier_herinnering")


def downgrade() -> None:
    for tabel in ("dossier_herinnering", "dossier_document", "veldwerker_dossier", "dossier_documenttype"):
        op.drop_table(tabel, schema="boekhouding")
    op.drop_constraint("ck_administratie_uren_dagmax", "administratie", schema="platform", type_="check")
    op.drop_column("administratie", "uren_dagmax_uren", schema="platform")
