"""Steigerbouw-run blok D (besluiten Peter 24-08, mockup planning-steigerbouw Transport-tab +
bestelling-popup): materiaalcatalogus per leverancier, bestellingen mét revisies (PDF-bon per
mail), transportplanning (levering/retour per project per dag, status gepland → bevestigd →
geleverd als seam voor het verhuursysteem), materiaalstand en de materiaalmatch (D6:
inkoopfacturen van verhuur-crediteuren vs. aantal × huurperiode per item).

RLS per administratie (patroon 0056), GRANT zonder DELETE — bestellingen/transporten worden
geannuleerd mét reden, revisies zijn append-only; élke mutatie via de service mét audit_event.

Revision ID: 0074
Revises: 0073
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
SCHEMA = "boekhouding"


def _rls(tabel: str) -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON {SCHEMA}.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        "materiaal_leverancier",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("bestel_email", sa.Text(), nullable=True),
        sa.Column("telefoon", sa.Text(), nullable=True),
        sa.Column("adres", sa.Text(), nullable=True),
        sa.Column("vendor_id", sa.UUID(), nullable=True),
        sa.Column("actief", sa.Boolean(), nullable=False),
        sa.Column("bijgewerkt_door", sa.UUID(), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["bijgewerkt_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("administratie_id", "naam", name="uq_materiaal_leverancier_naam"),
        schema=SCHEMA,
    )
    op.create_index("ix_materiaal_leverancier_administratie_id", "materiaal_leverancier", ["administratie_id"], schema=SCHEMA)
    _rls("materiaal_leverancier")

    op.create_table(
        "materiaal_categorie",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("leverancier_id", sa.UUID(), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("bundel", sa.Text(), nullable=False),
        sa.Column("volgorde", sa.Integer(), nullable=False),
        sa.Column("actief", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["leverancier_id"], [f"{SCHEMA}.materiaal_leverancier.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("leverancier_id", "naam", name="uq_materiaal_categorie_naam"),
        schema=SCHEMA,
    )
    op.create_index("ix_materiaal_categorie_administratie_id", "materiaal_categorie", ["administratie_id"], schema=SCHEMA)
    _rls("materiaal_categorie")

    op.create_table(
        "materiaal_product",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("leverancier_id", sa.UUID(), nullable=False),
        sa.Column("categorie_id", sa.UUID(), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("verpakking", sa.Text(), nullable=True),
        sa.Column("eenheid", sa.Text(), nullable=False),
        sa.Column("m2_lengte", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("volgorde", sa.Integer(), nullable=False),
        sa.Column("actief", sa.Boolean(), nullable=False),
        sa.CheckConstraint("m2_lengte IS NULL OR m2_lengte >= 0", name="ck_materiaal_product_m2_lengte"),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["leverancier_id"], [f"{SCHEMA}.materiaal_leverancier.id"]),
        sa.ForeignKeyConstraint(["categorie_id"], [f"{SCHEMA}.materiaal_categorie.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("leverancier_id", "naam", name="uq_materiaal_product_naam"),
        schema=SCHEMA,
    )
    op.create_index("ix_materiaal_product_administratie_id", "materiaal_product", ["administratie_id"], schema=SCHEMA)
    op.create_index(
        "ix_materiaal_product_leverancier", "materiaal_product", ["leverancier_id", "categorie_id", "volgorde"], schema=SCHEMA
    )
    _rls("materiaal_product")

    op.create_table(
        "materiaal_bestelling",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("leverancier_id", sa.UUID(), nullable=False),
        sa.Column("volgnummer", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("revisie", sa.Integer(), nullable=False),
        sa.Column("regels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("gewenste_leverdatum", sa.Date(), nullable=True),
        sa.Column("gewenste_levertijd", sa.Time(), nullable=True),
        sa.Column("leveradres", sa.Text(), nullable=True),
        sa.Column("contactpersoon", sa.Text(), nullable=True),
        sa.Column("opmerking", sa.Text(), nullable=True),
        sa.Column("annulering_reden", sa.Text(), nullable=True),
        sa.Column("aangemaakt_door", sa.UUID(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("bijgewerkt_door", sa.UUID(), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('concept', 'verstuurd', 'geannuleerd')", name="ck_materiaal_bestelling_status"),
        sa.CheckConstraint("revisie >= 0", name="ck_materiaal_bestelling_revisie"),
        sa.CheckConstraint(
            "status <> 'geannuleerd' OR (annulering_reden IS NOT NULL AND length(btrim(annulering_reden)) > 0)",
            name="ck_materiaal_bestelling_annulering",
        ),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["leverancier_id"], [f"{SCHEMA}.materiaal_leverancier.id"]),
        sa.ForeignKeyConstraint(["aangemaakt_door"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(["bijgewerkt_door"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            [f"{SCHEMA}.project_cache.id", f"{SCHEMA}.project_cache.administratie_id"],
            name="fk_materiaal_bestelling_project_cache",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("administratie_id", "volgnummer", name="uq_materiaal_bestelling_volgnummer"),
        schema=SCHEMA,
    )
    op.create_index("ix_materiaal_bestelling_administratie_id", "materiaal_bestelling", ["administratie_id"], schema=SCHEMA)
    op.create_index("ix_materiaal_bestelling_project", "materiaal_bestelling", ["administratie_id", "project_id"], schema=SCHEMA)
    _rls("materiaal_bestelling")

    op.create_table(
        "materiaal_bestelling_revisie",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("bestelling_id", sa.UUID(), nullable=False),
        sa.Column("revisie", sa.Integer(), nullable=False),
        sa.Column("regels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("m2_totaal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("delta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("gewenste_leverdatum", sa.Date(), nullable=True),
        sa.Column("gewenste_levertijd", sa.Time(), nullable=True),
        sa.Column("leveradres", sa.Text(), nullable=True),
        sa.Column("pdf_opslag_pad", sa.Text(), nullable=False),
        sa.Column("verzonden_naar", sa.Text(), nullable=False),
        sa.Column("mail_status", sa.Text(), nullable=False),
        sa.Column("mail_fout", sa.Text(), nullable=True),
        sa.Column("verstuurd_door", sa.UUID(), nullable=False),
        sa.Column("verstuurd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("mail_status IN ('verzonden', 'mislukt')", name="ck_materiaal_bestelling_revisie_mail"),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["bestelling_id"], [f"{SCHEMA}.materiaal_bestelling.id"]),
        sa.ForeignKeyConstraint(["verstuurd_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bestelling_id", "revisie", name="uq_materiaal_bestelling_revisie"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_materiaal_bestelling_revisie_administratie_id", "materiaal_bestelling_revisie", ["administratie_id"], schema=SCHEMA
    )
    _rls("materiaal_bestelling_revisie")

    op.create_table(
        "materiaal_transport",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("leverancier_id", sa.UUID(), nullable=False),
        sa.Column("bestelling_id", sa.UUID(), nullable=True),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("tijdstip", sa.Time(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("status_bron", sa.Text(), nullable=False),
        sa.Column("status_reden", sa.Text(), nullable=True),
        sa.Column("status_gewijzigd_door", sa.UUID(), nullable=True),
        sa.Column("status_gewijzigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("regels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        sa.Column("aangemaakt_door", sa.UUID(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("soort IN ('levering', 'retour')", name="ck_materiaal_transport_soort"),
        sa.CheckConstraint(
            "status IN ('gepland', 'bevestigd', 'geleverd', 'geannuleerd')", name="ck_materiaal_transport_status"
        ),
        sa.CheckConstraint(
            "status <> 'geannuleerd' OR (status_reden IS NOT NULL AND length(btrim(status_reden)) > 0)",
            name="ck_materiaal_transport_annulering",
        ),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["leverancier_id"], [f"{SCHEMA}.materiaal_leverancier.id"]),
        sa.ForeignKeyConstraint(["bestelling_id"], [f"{SCHEMA}.materiaal_bestelling.id"]),
        sa.ForeignKeyConstraint(["status_gewijzigd_door"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(["aangemaakt_door"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            [f"{SCHEMA}.project_cache.id", f"{SCHEMA}.project_cache.administratie_id"],
            name="fk_materiaal_transport_project_cache",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index("ix_materiaal_transport_administratie_id", "materiaal_transport", ["administratie_id"], schema=SCHEMA)
    op.create_index("ix_materiaal_transport_datum", "materiaal_transport", ["administratie_id", "datum"], schema=SCHEMA)
    op.create_index(
        "ix_materiaal_transport_project", "materiaal_transport", ["administratie_id", "project_id", "datum"], schema=SCHEMA
    )
    _rls("materiaal_transport")

    op.create_table(
        "materiaalmatch",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("leverancier_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("uitkomst", sa.Text(), nullable=False),
        sa.Column("aantal_regels_getoetst", sa.Integer(), nullable=False),
        sa.Column("aantal_regels_afwijkend", sa.Integer(), nullable=False),
        sa.Column("aantal_regels_onbekend", sa.Integer(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("berekend_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("afwijking_bevestigd_door", sa.UUID(), nullable=True),
        sa.Column("afwijking_bevestigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("uitkomst IN ('match', 'afwijking', 'niet_toetsbaar')", name="ck_materiaalmatch_uitkomst"),
        sa.CheckConstraint(
            "(afwijking_bevestigd_door IS NULL) = (afwijking_bevestigd_op IS NULL)", name="ck_materiaalmatch_bevestigd_samen"
        ),
        sa.ForeignKeyConstraint(["document_id"], [f"{SCHEMA}.document.id"]),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["leverancier_id"], [f"{SCHEMA}.materiaal_leverancier.id"]),
        sa.ForeignKeyConstraint(["afwijking_bevestigd_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("document_id"),
        schema=SCHEMA,
    )
    op.create_index("ix_materiaalmatch_administratie_id", "materiaalmatch", ["administratie_id"], schema=SCHEMA)
    op.create_index("ix_materiaalmatch_administratie_uitkomst", "materiaalmatch", ["administratie_id", "uitkomst"], schema=SCHEMA)
    _rls("materiaalmatch")


def downgrade() -> None:
    for tabel in (
        "materiaalmatch",
        "materiaal_transport",
        "materiaal_bestelling_revisie",
        "materiaal_bestelling",
        "materiaal_product",
        "materiaal_categorie",
        "materiaal_leverancier",
    ):
        op.drop_table(tabel, schema=SCHEMA)
