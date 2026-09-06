"""Mini-voorraad speciale producten (blok F mini-run 06-09, mockup mini-voorraad.html ①–⑧ — BESLISSINGEN
"MINI-VOORRAAD SPECIALE PRODUCTEN"). Universal Steigerbouw koopt speciale producten buiten de standaardcatalogus;
bij het BOEKEN van een inkoopfactuur worden de productregels (omschrijving × aantal) automatisch bijgeteld, ín
de boek-transactie (tegenboeken/storno spiegelt), mét herkomst per regel. Kernbesluit ⑧ (Peter 05-09):
MENS-MANIPULATIE ONMOGELIJK — de stand is uitsluitend Σ van append-only mutaties die elk aan een brondocument
of -gebeurtenis hangen; er bestaat geen corrigeer-, samenvoeg- of standmutatie-endpoint.

- `platform.administratie.mini_voorraad_ingeschakeld` — opt-in (Beheerder-only, default UIT; F1).
- `mi.mini_product` — één product per (administratie, leverancier, genormaliseerde factuuromschrijving);
  `omschrijving` = LETTERLIJK de factuurtekst (⑦, = sleutel), `weergavenaam` alleen via "Naam bevestigen",
  vlag `nieuw_controleren` (④), archiveren = kolom (nooit delete, ⑥). GRANT zonder DELETE.
- `mi.mini_voorraad_mutatie` — APPEND-ONLY (GRANT SELECT + INSERT, 0091-patroon `werkopdracht`): getekend
  `aantal` per soort (instroom +, storno −, uitstroom −, beschadiging −), `datum`, herkomst (document +
  regel + boek_cyclus) óf gebeurtenis (beschadiging: project VERPLICHT via CHECK, gemeld_door, toelichting).
  Stand per product = SUM(aantal) — query, geen kolom, geen view.
RLS per administratie (0086-patroon). Schema-only DDL, geen backfill (boekingen van vóór de opt-in tellen
bewust niet mee — beslispunt Peter).

Revision ID: 0116
Revises: 0115
Create Date: 2026-09-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0116"
down_revision: str | None = "0115"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
SCHEMA = "mi"


def _rls(tabel: str, *, rechten: str) -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON {SCHEMA}.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT {rechten} ON {SCHEMA}.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    op.add_column(
        "administratie",
        sa.Column("mini_voorraad_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )

    op.create_table(
        "mini_product",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("leverancier_naam", sa.Text(), nullable=True),
        sa.Column("artikelcode", sa.Text(), nullable=True),
        sa.Column("omschrijving", sa.Text(), nullable=False),
        sa.Column("omschrijving_norm", sa.Text(), nullable=False),
        sa.Column("weergavenaam", sa.Text(), nullable=True),
        sa.Column("eenheid", sa.Text(), nullable=True),
        sa.Column("nieuw_controleren", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("naam_bevestigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("naam_bevestigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gearchiveerd", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gearchiveerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gearchiveerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("bron_document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=True),
        sa.CheckConstraint("length(btrim(omschrijving)) > 0", name="ck_mini_product_omschrijving"),
        sa.CheckConstraint("length(btrim(omschrijving_norm)) > 0", name="ck_mini_product_omschrijving_norm"),
        sa.UniqueConstraint("administratie_id", "vendor_id", "omschrijving_norm", name="uq_mini_product_sleutel"),
        schema=SCHEMA,
    )
    op.create_index("ix_mini_product_administratie_id", "mini_product", ["administratie_id"], schema=SCHEMA)
    op.create_index(
        "ix_mini_product_artikelcode", "mini_product", ["administratie_id", "vendor_id", "artikelcode"], schema=SCHEMA
    )
    _rls("mini_product", rechten="SELECT, INSERT, UPDATE")

    op.create_table(
        "mini_voorraad_mutatie",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.mini_product.id"), nullable=False),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("aantal", sa.Numeric(12, 3), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=True),
        sa.Column("regel_volgnummer", sa.Integer(), nullable=True),
        sa.Column("boek_cyclus", sa.Integer(), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("gemeld_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("toelichting", sa.Text(), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.CheckConstraint(
            "soort IN ('instroom', 'storno', 'uitstroom', 'beschadiging')", name="ck_mini_voorraad_mutatie_soort"
        ),
        sa.CheckConstraint(
            "soort <> 'beschadiging' OR project_id IS NOT NULL", name="ck_mini_voorraad_mutatie_beschadiging_project"
        ),
        sa.CheckConstraint("aantal <> 0", name="ck_mini_voorraad_mutatie_aantal"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mini_voorraad_mutatie_product", "mini_voorraad_mutatie", ["product_id", "aangemaakt_op"], schema=SCHEMA
    )
    op.create_index(
        "ix_mini_voorraad_mutatie_document",
        "mini_voorraad_mutatie",
        ["administratie_id", "document_id"],
        schema=SCHEMA,
    )
    # Append-only: geen UPDATE/DELETE-grant — een stand kan alleen veranderen door een nieuwe brongebonden rij.
    _rls("mini_voorraad_mutatie", rechten="SELECT, INSERT")


def downgrade() -> None:
    for tabel in ("mini_voorraad_mutatie", "mini_product"):
        op.execute(f"REVOKE ALL ON {SCHEMA}.{tabel} FROM {APP_ROLE}")
        op.execute(f"DROP POLICY IF EXISTS {tabel}_scope ON {SCHEMA}.{tabel}")
    op.drop_index("ix_mini_voorraad_mutatie_document", table_name="mini_voorraad_mutatie", schema=SCHEMA)
    op.drop_index("ix_mini_voorraad_mutatie_product", table_name="mini_voorraad_mutatie", schema=SCHEMA)
    op.drop_table("mini_voorraad_mutatie", schema=SCHEMA)
    op.drop_index("ix_mini_product_artikelcode", table_name="mini_product", schema=SCHEMA)
    op.drop_index("ix_mini_product_administratie_id", table_name="mini_product", schema=SCHEMA)
    op.drop_table("mini_product", schema=SCHEMA)
    op.drop_column("administratie", "mini_voorraad_ingeschakeld", schema="platform")
