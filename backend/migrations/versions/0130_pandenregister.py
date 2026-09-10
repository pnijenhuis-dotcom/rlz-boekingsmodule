"""Blok D2 bundel 10-09 — pandenregister datalaag (pand + pand_boeking, Vastgoedgroep Nederland).

`boekhouding.pand`: één pand = één dossier-adres per administratie (code = genormaliseerde adres-sleutel, uniek per
administratie). Afgeleid uit RLZ (aankoop = memoriaal RLZ-06 met pand-referentie + notaris-PDF, verkoop = verkoop-
factuur RLZ-01 op een notaris) óf door een mens ingevoerd (`herkomst`). Status: voorstel → bevestigd → in_handel →
verkocht; vervallen = nooit een pand geweest (blijft staan, nooit verwijderd).
`boekhouding.pand_boeking`: koppeling boeking ↔ pand (RLZ-boekstuk óf module-document), herkomst voorstel|mens,
zekerheid hoog|midden|laag mét reden; bevestiging door een mens is een aparte stap (run 2). `bron_sleutel` =
"rlz:<rlz_document_id>" of "doc:<document_id>" — de uitvoerbare vorm van "uniek op (administratie, coalesce(rlz_document_id,
document_id), pand)" zonder expressie-index (alembic check blijft leesbaar).

Schema-only (pure DDL) — de afleiding zelf is een losse, expliciete CLI-stap (`pandenregister-afleiden`).
RLS per administratie (0071-patroon), GRANT zonder DELETE: een pand of koppeling verdwijnt nooit stil.

Revision ID: 0130
Revises: 0129
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0130"
down_revision: str | None = "0129"
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
        "pand",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("adres", sa.Text(), nullable=False),
        sa.Column("plaats", sa.Text(), nullable=True),
        sa.Column("postcode", sa.Text(), nullable=True),
        sa.Column("aankoopdatum", sa.Date(), nullable=True),
        sa.Column("verkoopdatum", sa.Date(), nullable=True),
        sa.Column("notaris_dossiernummers", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("herkomst", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("herkomst IN ('afgeleid', 'mens')", name="ck_pand_herkomst"),
        sa.CheckConstraint(
            "status IN ('voorstel', 'bevestigd', 'in_handel', 'verkocht', 'vervallen')", name="ck_pand_status"
        ),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index("ix_pand_administratie_id", "pand", ["administratie_id"], schema="boekhouding")
    op.create_index("ux_pand_code", "pand", ["administratie_id", "code"], unique=True, schema="boekhouding")
    _rls("pand")

    op.create_table(
        "pand_boeking",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("pand_id", sa.UUID(), nullable=False),
        sa.Column("rlz_document_id", sa.UUID(), nullable=True),
        sa.Column("rlz_boekstuknummer", sa.Text(), nullable=True),
        sa.Column("rlz_collectie", sa.Text(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("bron_sleutel", sa.Text(), nullable=False),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("herkomst", sa.Text(), nullable=False),
        sa.Column("zekerheid", sa.Text(), nullable=False),
        sa.Column("reden", sa.Text(), nullable=True),
        sa.Column("datum", sa.Date(), nullable=True),
        sa.Column("bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("bevestigd_door", sa.UUID(), nullable=True),
        sa.Column("bevestigd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("soort IN ('aankoop', 'verkoop', 'kosten', 'overhead')", name="ck_pand_boeking_soort"),
        sa.CheckConstraint("herkomst IN ('voorstel', 'mens')", name="ck_pand_boeking_herkomst"),
        sa.CheckConstraint("zekerheid IN ('hoog', 'midden', 'laag')", name="ck_pand_boeking_zekerheid"),
        sa.CheckConstraint(
            "rlz_document_id IS NOT NULL OR document_id IS NOT NULL", name="ck_pand_boeking_bron_aanwezig"
        ),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["pand_id"], ["boekhouding.pand.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["boekhouding.document.id"]),
        sa.ForeignKeyConstraint(["bevestigd_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index("ix_pand_boeking_administratie_id", "pand_boeking", ["administratie_id"], schema="boekhouding")
    op.create_index("ix_pand_boeking_pand_id", "pand_boeking", ["pand_id"], schema="boekhouding")
    op.create_index(
        "ux_pand_boeking_bron_pand",
        "pand_boeking",
        ["administratie_id", "bron_sleutel", "pand_id"],
        unique=True,
        schema="boekhouding",
    )
    _rls("pand_boeking")


def downgrade() -> None:
    op.drop_index("ux_pand_boeking_bron_pand", table_name="pand_boeking", schema="boekhouding")
    op.drop_index("ix_pand_boeking_pand_id", table_name="pand_boeking", schema="boekhouding")
    op.drop_index("ix_pand_boeking_administratie_id", table_name="pand_boeking", schema="boekhouding")
    op.drop_table("pand_boeking", schema="boekhouding")
    op.drop_index("ux_pand_code", table_name="pand", schema="boekhouding")
    op.drop_index("ix_pand_administratie_id", table_name="pand", schema="boekhouding")
    op.drop_table("pand", schema="boekhouding")
