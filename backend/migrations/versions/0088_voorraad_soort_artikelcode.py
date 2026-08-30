"""Voorraad-normalisatie v2 (opdracht 30-08, besluiten Peter 29-08 avond — BESLISSINGEN "OPDRACHT 30-08"):

A. Dienst-regels BLIJVEN in de MI-laag. "Uitgesloten" wordt een SOORT-label (artikel / dienst /
   transport): dienst-/transportregels tellen niet mee in de voorraad-aansluiting maar blijven bewaard
   en queryable als omzet-/dienstregel (kilometers, keuringen, werktijd = omzet-informatie voor MI).
   - `mi.normalisatie_regel.soort` en `mi.voorraad_regel.soort` (default 'artikel').
   - `normalisatie_status` beschrijft sindsdien uitsluitend de normalisatie-ZEKERHEID
     (genormaliseerd / onzeker / niet_genormaliseerd); de oude waarde 'uitgesloten' blijft in de CHECK
     toegestaan als LEGACY-representatie (vóór 0088) en wordt door de app-hernormalisatie
     (`voorraad-hernormaliseer`) per administratie omgezet naar soort dienst/transport + status
     genormaliseerd. Bewust géén data-UPDATE in deze migratie: migraties zijn schema-only (afsluit-
     routine) én Alembic draait op Cloud SQL als `postgres` zónder BYPASSRLS — een UPDATE op een
     FORCE-RLS-tabel zou dáár stil 0 rijen raken (TRANCHE2-les). Om dezelfde reden blijft de kolom
     `normalisatie_regel.uitgesloten` staan (blijft in sync met soort; opruimen = latere migratie ná
     de hernormalisatie op álle omgevingen).
C. Artikelcode als deterministische normalisatiesleutel MÉT inkoop↔verkoop-onderscheid:
   - `mi.voorraad_regel.artikelcode` (uit de verkoop-Description "(560140.4)" of het inkoop-
     veldvoorstel — de codes van leverancier en eigen verkoop zijn NIET gelijk, nooit aannemen);
   - nieuwe koppeltabel `mi.artikelcode_koppeling` per (administratie, richting, leverancier, code) →
     artikelgroep óf soort dienst/transport; bron 'ai' (eerste keer = voorstel, zekerheid erbij) of
     'handmatig' (correctie); daarna deterministisch vóór de tekstregel en vóór de AI.
Nooit RLZ-writes. RLS per administratie zoals 0086.

Revision ID: 0088
Revises: 0087
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
SCHEMA = "mi"
SOORTEN = "('artikel', 'dienst', 'transport')"


def _rls(tabel: str, *, met_delete: bool = False) -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON {SCHEMA}.{tabel}
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    rechten = "SELECT, INSERT, UPDATE" + (", DELETE" if met_delete else "")
    op.execute(f"GRANT {rechten} ON {SCHEMA}.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    # A — soort-label op de normalisatieregel en de feitenregel.
    op.add_column(
        "normalisatie_regel",
        sa.Column("soort", sa.Text(), nullable=False, server_default="artikel"),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_normalisatie_regel_soort", "normalisatie_regel", f"soort IN {SOORTEN}", schema=SCHEMA
    )
    op.add_column(
        "voorraad_regel",
        sa.Column("soort", sa.Text(), nullable=False, server_default="artikel"),
        schema=SCHEMA,
    )
    op.create_check_constraint("ck_voorraad_regel_soort", "voorraad_regel", f"soort IN {SOORTEN}", schema=SCHEMA)

    # C — artikelcode op de feitenregel + koppeltabel code → groep per richting/leverancier.
    op.add_column("voorraad_regel", sa.Column("artikelcode", sa.Text(), nullable=True), schema=SCHEMA)
    op.create_index(
        "ix_voorraad_regel_artikelcode", "voorraad_regel", ["administratie_id", "artikelcode"], schema=SCHEMA
    )
    op.create_table(
        "artikelcode_koppeling",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("richting", sa.Text(), nullable=False),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("artikelgroep_id", UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.artikelgroep.id"), nullable=True),
        sa.Column("soort", sa.Text(), nullable=False, server_default="artikel"),
        sa.Column("zekerheid", sa.Numeric(4, 3), nullable=True),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("voorbeeld_tekst", sa.Text(), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("bijgewerkt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("administratie_id", "richting", "vendor_id", "code", name="uq_artikelcode_koppeling"),
        sa.CheckConstraint("richting IN ('in', 'uit')", name="ck_artikelcode_koppeling_richting"),
        sa.CheckConstraint(f"soort IN {SOORTEN}", name="ck_artikelcode_koppeling_soort"),
        sa.CheckConstraint("bron IN ('ai', 'handmatig')", name="ck_artikelcode_koppeling_bron"),
        sa.CheckConstraint(
            "(soort = 'artikel') OR artikelgroep_id IS NULL", name="ck_artikelcode_koppeling_groep_bij_artikel"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_artikelcode_koppeling_administratie_id", "artikelcode_koppeling", ["administratie_id"], schema=SCHEMA
    )
    _rls("artikelcode_koppeling")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS artikelcode_koppeling_scope ON {SCHEMA}.artikelcode_koppeling")
    op.drop_index("ix_artikelcode_koppeling_administratie_id", table_name="artikelcode_koppeling", schema=SCHEMA)
    op.drop_table("artikelcode_koppeling", schema=SCHEMA)
    op.drop_index("ix_voorraad_regel_artikelcode", table_name="voorraad_regel", schema=SCHEMA)
    op.drop_column("voorraad_regel", "artikelcode", schema=SCHEMA)
    op.drop_constraint("ck_voorraad_regel_soort", "voorraad_regel", schema=SCHEMA, type_="check")
    op.drop_column("voorraad_regel", "soort", schema=SCHEMA)
    op.drop_constraint("ck_normalisatie_regel_soort", "normalisatie_regel", schema=SCHEMA, type_="check")
    op.drop_column("normalisatie_regel", "soort", schema=SCHEMA)
