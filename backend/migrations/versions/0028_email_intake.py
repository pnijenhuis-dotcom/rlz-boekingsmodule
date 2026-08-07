"""E-mail-intake + verzamelbak "Niet toegewezen" (fase 3).

Fundament (mockup verzamelbak-paneel + #tenaamstellingmodal/#verdeelmodal; CLAUDE.md "E-mail
intake" + "Verzamelbak"; koppelcontract §2d VASTLY-VERKOOP):

- boekhouding.intake_bericht — één binnengekomen e-mail uit het centrale postvak (of een
  geüploade .eml): message-id (uniek → idempotente verwerking), afzender, onderwerp,
  verwerkingsresultaat per bijlage in `detail` (óók genegeerde VGB-documenten — "niets
  verdwijnt stil": wat geen werkvoorraad-document wordt, blijft hier zichtbaar).
- boekhouding.toewijzing_regel — het toewijzings-geheugen: genormaliseerde
  tenaamstelling-/afzender-sleutel → administratie. Gevoed door handmatige toewijzingen in de
  verzamelbak (mockup: "elke handmatige toewijzing wordt onthouden"). Append-only-achtig:
  deactiveren i.p.v. verwijderen; uniek per actieve (soort, sleutel).
- boekhouding.intake_splitsing — het multi-factuur-splitsingsvoorstel per bron-document
  (AI-detectie van factuurgrenzen): ALTIJD eerst ter controle (mockup), een mens bevestigt
  (evt. met aangepaste paginabereiken) of wijst af — nooit stil auto-splitsen.
- boekhouding.document: soort-CHECK uitgebreid met 'verkoopfactuur' (§2d: VASTLY-VERKOOP →
  omzetkant), intake-herkomstvelden (intake_bericht_id, afzender_hint, tenaamstelling) en de
  toewijzing-suggestie (administratie + bron — suggestie, nooit stille toewijzing).
- document_status: nieuwe terminale status 'gesplitst' voor een bron-PDF waarvan de
  bevestigde splitsing kind-documenten heeft opgeleverd (het origineel blijft bestaan en
  terugvindbaar — nooit weg).

RLS: intake_bericht/toewijzing_regel/intake_splitsing zijn platform-brede intake-tabellen
(de verzamelbak is per definitie administratie-loos; de match-regels moeten administratie-
overstijgend te raadplegen zijn tijdens de intake, vóór er een scope bestaat) — zelfde
overweging als document-rijen met administratie_id NULL (migratie 0004): policy USING (true)
met RLS+FORCE als vangnet-structuur, toegang begrensd door de applicatielaag (alleen
kantoorrollen, geen klant-accordeurs — app/intake/router.py). Geen DELETE-grants.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def _rls_platform_breed(tabel: str) -> None:
    op.execute(f"ALTER TABLE boekhouding.{tabel} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE boekhouding.{tabel} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {tabel}_scope ON boekhouding.{tabel}
        USING (true)
        WITH CHECK (true)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.{tabel} TO {APP_ROLE}")


def upgrade() -> None:
    # --- nieuwe documentsoort + terminale splitsings-status -------------------------------------
    op.execute("ALTER TABLE boekhouding.document DROP CONSTRAINT document_soort_geldig")
    op.create_check_constraint(
        "document_soort_geldig",
        "document",
        "soort IN ('inkoopfactuur', 'kassarapport', 'verkoopfactuur')",
        schema="boekhouding",
    )
    # ADD VALUE mag sinds PG12 binnen een transactie zolang de waarde niet in dezelfde
    # transactie gebruikt wordt (zelfde patroon als migratie 0016).
    op.execute("ALTER TYPE boekhouding.document_status ADD VALUE IF NOT EXISTS 'gesplitst' AFTER 'verwijderd'")

    # --- intake-bericht --------------------------------------------------------------------------
    op.create_table(
        "intake_bericht",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("afzender", sa.Text(), nullable=True),
        sa.Column("onderwerp", sa.Text(), nullable=True),
        sa.Column("bron", sa.Text(), nullable=False, server_default="eml_upload"),
        sa.Column("ontvangen_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verwerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verwerkt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("detail", JSONB, nullable=False),
        sa.CheckConstraint("bron IN ('eml_upload', 'imap')", name="intake_bericht_bron_geldig"),
        schema="boekhouding",
    )
    # Idempotente verwerking: hetzelfde bericht (Message-ID) wordt nooit twee keer verwerkt.
    op.create_index(
        "ux_intake_bericht_message_id",
        "intake_bericht",
        ["message_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )
    _rls_platform_breed("intake_bericht")

    # --- toewijzings-geheugen --------------------------------------------------------------------
    op.create_table(
        "toewijzing_regel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("soort", sa.Text(), nullable=False),
        sa.Column("sleutel", sa.Text(), nullable=False),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gedeactiveerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gedeactiveerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("soort IN ('tenaamstelling', 'afzender')", name="toewijzing_regel_soort_geldig"),
        sa.CheckConstraint("sleutel <> ''", name="toewijzing_regel_sleutel_niet_leeg"),
        schema="boekhouding",
    )
    op.create_index(
        "ux_toewijzing_regel_actief",
        "toewijzing_regel",
        ["soort", "sleutel"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("actief"),
    )
    _rls_platform_breed("toewijzing_regel")

    # --- splitsingsvoorstel ------------------------------------------------------------------------
    op.create_table(
        "intake_splitsing",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bron_document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False
        ),
        sa.Column("voorstel", JSONB, nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="voorgesteld"),
        sa.Column("voorgesteld_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("besloten_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("besloten_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("besluit_detail", JSONB, nullable=True),
        sa.CheckConstraint(
            "status IN ('voorgesteld', 'bevestigd', 'afgewezen')", name="intake_splitsing_status_geldig"
        ),
        sa.CheckConstraint(
            "(status = 'voorgesteld') = (besloten_op IS NULL)", name="intake_splitsing_besluit_consistent"
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ux_intake_splitsing_open_per_document",
        "intake_splitsing",
        ["bron_document_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status = 'voorgesteld'"),
    )
    _rls_platform_breed("intake_splitsing")

    # --- intake-herkomst + toewijzing-suggestie op document --------------------------------------
    op.add_column(
        "document",
        sa.Column("intake_bericht_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.intake_bericht.id")),
        schema="boekhouding",
    )
    op.add_column("document", sa.Column("afzender_hint", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column("document", sa.Column("tenaamstelling", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column(
        "document",
        sa.Column(
            "toewijzing_suggestie_administratie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.administratie.id"),
            nullable=True,
        ),
        schema="boekhouding",
    )
    op.add_column(
        "document", sa.Column("toewijzing_suggestie_bron", sa.Text(), nullable=True), schema="boekhouding"
    )
    # Splitsing-kinderen dragen hun herkomst: het bron-document + het paginabereik.
    op.add_column(
        "document",
        sa.Column("gesplitst_uit_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id")),
        schema="boekhouding",
    )


def downgrade() -> None:
    for kolom in (
        "gesplitst_uit_id",
        "toewijzing_suggestie_bron",
        "toewijzing_suggestie_administratie_id",
        "tenaamstelling",
        "afzender_hint",
        "intake_bericht_id",
    ):
        op.drop_column("document", kolom, schema="boekhouding")
    for tabel in ("intake_splitsing", "toewijzing_regel", "intake_bericht"):
        op.execute(f"REVOKE ALL ON boekhouding.{tabel} FROM {APP_ROLE}")
        op.execute(f"DROP POLICY IF EXISTS {tabel}_scope ON boekhouding.{tabel}")
        op.drop_table(tabel, schema="boekhouding")
    op.execute("ALTER TABLE boekhouding.document DROP CONSTRAINT document_soort_geldig")
    op.create_check_constraint(
        "document_soort_geldig",
        "document",
        "soort IN ('inkoopfactuur', 'kassarapport')",
        schema="boekhouding",
    )
    # 'gesplitst' uit de PG-enum verwijderen kan niet zonder type-rebuild — bewust laten staan
    # (zelfde afweging als migratie 0016 voor extractie_wachtrij).
