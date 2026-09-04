"""Documenttype "verplichting" (offerte / prijsopgave / opdrachtbevestiging) + factuur↔verplichting-match
(wens Peter 04-09, mockup `offerte-matching.html` ①–⑧).

Inkomende offertes/prijsopgaven/opdrachtbevestigingen worden één documenttype `verplichting` mét
soort-label; ze doorlopen de BESTAANDE klant-accorderingsflow (lagen, drempels, app) en eindigen —
zonder enige boeking in RLZ/Odoo — op de nieuwe terminale documentstatus `geaccordeerd`. Elke latere
inkoopfactuur van dezelfde crediteur wordt er CUMULATIEF tegen gematcht (③: verbruik = som van de
gematchte, verrekende facturen; binnen = verbruik ≤ goedgekeurd bedrag, geen tolerantiemarge).

Schema-only (geen backfill):
- `document_status` krijgt de waarde `geaccordeerd` (ALTER TYPE ... ADD VALUE — PG12+: mag binnen een
  transactie zolang de waarde niet in dezelfde transactie gebruikt wordt; zelfde patroon als 0015/0024/0028).
- CHECK `document_soort_geldig` uitgebreid met 'verplichting' (DROP+CREATE, patroon 0039).
- `boekhouding.verplichting`: één rij per verplichting-document (1:1 op document_id) — de gecontroleerde
  kopvelden, het bij het laatste akkoord vastgelegde `goedgekeurd_bedrag_excl` (+ wie/wanneer), de
  cumulatieve verbruiksstand en het vervallen-spoor (⑥: vervallen stopt nieuwe matches, gematchte
  facturen blijven ongemoeid).
- `boekhouding.verplichting_match`: één rij per INKOOPdocument (herberekening ververst 'm) met de
  uitkomst, de cumulatieve stand vóór/ná en het handmatige-koppeling-spoor.

Beide tabellen: RLS ENABLE+FORCE + policy op administratie_id + GRANT zonder DELETE (patroon 0107) —
een verplichting vervalt (kolom), verdwijnt nooit.

Revision ID: 0110
Revises: 0109
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0110"
down_revision: str | None = "0109"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"

_SOORTEN_NA = "('inkoopfactuur', 'kassarapport', 'verkoopfactuur', 'waarborg', 'verplichting')"
_SOORTEN_VOOR = "('inkoopfactuur', 'kassarapport', 'verkoopfactuur', 'waarborg')"


def upgrade() -> None:
    # PG12+: ADD VALUE mag in een transactie zolang de nieuwe waarde niet in DEZELFDE transactie
    # gebruikt wordt (deze migratie schrijft geen documentrijen) — zie 0015/0024/0028.
    op.execute("ALTER TYPE boekhouding.document_status ADD VALUE IF NOT EXISTS 'geaccordeerd'")

    op.execute("ALTER TABLE boekhouding.document DROP CONSTRAINT document_soort_geldig")
    op.create_check_constraint(
        "document_soort_geldig", "document", f"soort IN {_SOORTEN_NA}", schema="boekhouding"
    )

    op.create_table(
        "verplichting",
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("soort_label", sa.Text(), nullable=True),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("offertenummer", sa.Text(), nullable=True),
        # `datum` = documentdatum van de offerte. Contract-aanvulling (zie contract_afwijkingen_B.md):
        # de DTO en de Input dragen dit veld en de check "Geldigheid" toetst geldig_tot ertegen.
        sa.Column("datum", sa.Date(), nullable=True),
        sa.Column("totaalbedrag_excl", sa.Numeric(14, 2), nullable=True),
        sa.Column("geldig_tot", sa.Date(), nullable=True),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        sa.Column("opgeslagen_door", UUID(as_uuid=True), nullable=True),
        sa.Column("opgeslagen_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("goedgekeurd_bedrag_excl", sa.Numeric(14, 2), nullable=True),
        sa.Column("goedgekeurd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("goedgekeurd_door", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "verbruikt_bedrag_excl", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column("vervallen_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vervallen_reden", sa.Text(), nullable=True),
        sa.Column("vervallen_door", UUID(as_uuid=True), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "soort_label IS NULL OR soort_label IN ('offerte', 'prijsopgave', 'opdrachtbevestiging')",
            name="ck_verplichting_soort_label",
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ix_verplichting_administratie_vendor", "verplichting", ["administratie_id", "vendor_id"], schema="boekhouding"
    )

    op.create_table(
        "verplichting_match",
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column(
            "verplichting_document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=True
        ),
        sa.Column("uitkomst", sa.Text(), nullable=False),
        sa.Column("bedrag_excl", sa.Numeric(14, 2), nullable=True),
        sa.Column("verbruik_voor", sa.Numeric(14, 2), nullable=True),
        sa.Column("verbruik_na", sa.Numeric(14, 2), nullable=True),
        sa.Column("overschrijding_excl", sa.Numeric(14, 2), nullable=True),
        sa.Column("handmatig_gekoppeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verrekend_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("berekend_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("details", JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "uitkomst IN ('binnen', 'buiten', 'geen_match', 'meerdere_kandidaten', 'niet_toetsbaar', "
            "'geen_verplichting')",
            name="ck_verplichting_match_uitkomst",
        ),
        sa.CheckConstraint(
            "overschrijding_excl IS NULL OR overschrijding_excl >= 0", name="ck_verplichting_match_overschrijding"
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ix_verplichting_match_administratie_uitkomst",
        "verplichting_match",
        ["administratie_id", "uitkomst"],
        schema="boekhouding",
    )

    for tabel in ("verplichting", "verplichting_match"):
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


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS verplichting_match_scope ON boekhouding.verplichting_match")
    op.drop_index(
        "ix_verplichting_match_administratie_uitkomst", table_name="verplichting_match", schema="boekhouding"
    )
    op.drop_table("verplichting_match", schema="boekhouding")
    op.execute("DROP POLICY IF EXISTS verplichting_scope ON boekhouding.verplichting")
    op.drop_index("ix_verplichting_administratie_vendor", table_name="verplichting", schema="boekhouding")
    op.drop_table("verplichting", schema="boekhouding")
    # Documenten van soort 'verplichting' bestaan alleen mét deze tabellen; de CHECK gaat terug.
    op.execute("ALTER TABLE boekhouding.document DROP CONSTRAINT document_soort_geldig")
    op.create_check_constraint(
        "document_soort_geldig", "document", f"soort IN {_SOORTEN_VOOR}", schema="boekhouding"
    )
    # PostgreSQL kent geen DROP VALUE op een enum — de waarde 'geaccordeerd' blijft bestaan
    # (ongebruikt en onschadelijk); zelfde afweging als 0015/0024/0028.
