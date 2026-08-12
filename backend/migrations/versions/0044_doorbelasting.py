"""Kempen-doorbelasting (besluit Peter 2026-08-13, hoort bij de livegang).

Vijf bouwstenen (canoniek: verkenning/16_DOORBELASTING_KEMPEN.md §4 + mockup #verdeelmodal):
- `platform.administratie.doorbelasting_ingeschakeld` — de per-administratie-toggle (default
  UIT; alleen bron-administraties zoals Kempen Facilities gaan aan);
- `doorbelasting_mapping` — de server-side afgedwongen whitelist doelentiteit ↔
  Customer-GUID-in-bron, mét intercompany-vlag per rij (Rubicon-verificatie §2c bewees dat
  RC-afhandeling per doelentiteit verschilt) en de vaste provisie-GB in de doel-administratie;
- `doorbelasting_instelling` — config per bron-administratie: provisie-% (default 5,00),
  vlak btw-tarief en omzet-GB('s) — huidige praktijk als config, nooit hardcoded (§2);
- `doorbelasting_run` + `doorbelasting_regel` — het bevestigde verdeelvoorstel per geboekte
  bron-inkoopfactuur (percentages exact 100% per regel, grootste-rest-centverdeling);
- `doorbelasting_boeking` — de tweezijdige uitvoering per doelentiteit (verkoop in bron +
  spiegel-inkoop in doel), met half-geboekt-patroon en `spiegel_open` als open taak.

Duplicaatbewaking DB-uniek (opdracht blok 1d): hooguit één niet-gestorneerde run per
document, en hooguit één niet-gestorneerde boeking per (document, doelentiteit) — partial
unique indexes, gestorneerd uitgezonderd zodat een storno+opnieuw-doorbelasten kan.

Alle tabellen RLS op administratie_id (bron-administratie = de scope; de doel-kant leeft in
RLZ, niet in extra lokale rijen), GRANT zonder DELETE — behalve `doorbelasting_regel`
(werkstaat: een verdeling mag herzien worden zolang er niet geboekt is, patroon
verkoop_voorstel_regel uit 0035).

Seed van de Kempen-mapping (verkenning §1) is bewust GEEN onderdeel van deze migratie
(migraties zijn schema-only): losse expliciete stap `make doorbelasting-seed-kempen` zodra
de Facilities-administratie onboarded is.

Revision ID: 0044
Revises: 0043
Create Date: 2026-08-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


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
        "administratie",
        sa.Column("doorbelasting_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )

    op.create_table(
        "doorbelasting_mapping",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("doelentiteit_naam", sa.Text(), nullable=False),
        sa.Column("doel_customer_guid", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "doel_administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=True
        ),
        sa.Column("intercompany", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provisie_kosten_ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("laatste_kosten_ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("administratie_id", "doel_customer_guid", name="doorbelasting_mapping_doel_uniek"),
        schema="boekhouding",
    )
    _rls_op_administratie("doorbelasting_mapping")

    op.create_table(
        "doorbelasting_instelling",
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("provisie_percentage", sa.Numeric(5, 2), nullable=False, server_default=sa.text("5.00")),
        sa.Column("btw_taxrate_id", UUID(as_uuid=True), nullable=True),
        sa.Column("omzet_ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("provisie_omzet_ledger_id", UUID(as_uuid=True), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "provisie_percentage >= 0 AND provisie_percentage <= 100",
            name="doorbelasting_instelling_provisie_bereik",
        ),
        schema="boekhouding",
    )
    _rls_op_administratie("doorbelasting_instelling")

    op.create_table(
        "doorbelasting_run",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'concept'")),
        sa.Column("laatste_fout", JSONB(), nullable=True),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("geboekt_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('concept', 'geboekt', 'gestorneerd')", name="doorbelasting_run_status"
        ),
        schema="boekhouding",
    )
    _rls_op_administratie("doorbelasting_run")
    op.create_index(
        "doorbelasting_run_document_actief_uniek",
        "doorbelasting_run",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status != 'gestorneerd'"),
        schema="boekhouding",
    )

    op.create_table(
        "doorbelasting_regel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.doorbelasting_run.id"), nullable=False),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column(
            "bron_regel_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.boekvoorstel_regel.id"), nullable=False
        ),
        sa.Column(
            "mapping_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.doorbelasting_mapping.id"), nullable=False
        ),
        sa.Column("percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("netto_deel", sa.Numeric(14, 2), nullable=False),
        sa.Column("doel_kosten_ledger_id", UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("percentage > 0 AND percentage <= 100", name="doorbelasting_regel_pct_bereik"),
        sa.UniqueConstraint("run_id", "bron_regel_id", "mapping_id", name="doorbelasting_regel_uniek"),
        schema="boekhouding",
    )
    _rls_op_administratie("doorbelasting_regel")
    # Werkstaat: een verdeling mag herzien worden zolang de run concept is (patroon
    # verkoop_voorstel_regel, 0035) — de service weigert DELETE zodra er geboekt is.
    op.execute(f"GRANT DELETE ON boekhouding.doorbelasting_regel TO {APP_ROLE}")

    op.create_table(
        "doorbelasting_boeking",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.doorbelasting_run.id"), nullable=False),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column(
            "mapping_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.doorbelasting_mapping.id"), nullable=False
        ),
        sa.Column(
            "doel_administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=True
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'geboekt'")),
        sa.Column("netto_totaal", sa.Numeric(14, 2), nullable=False),
        sa.Column("provisie_bedrag", sa.Numeric(14, 2), nullable=False),
        sa.Column("btw_bedrag", sa.Numeric(14, 2), nullable=False),
        sa.Column("verkoop_rlz_id", UUID(as_uuid=True), nullable=False),
        sa.Column("verkoop_referentie", sa.Text(), nullable=True),
        sa.Column("verkoop_invoice_number", sa.Integer(), nullable=True),
        sa.Column("spiegel_rlz_id", UUID(as_uuid=True), nullable=False),
        sa.Column("spiegel_geboekt_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("half_geboekt_detail", JSONB(), nullable=True),
        sa.Column("storno_reden", sa.Text(), nullable=True),
        sa.Column("geboekt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('geboekt', 'spiegel_open', 'half_geboekt', 'gestorneerd')",
            name="doorbelasting_boeking_status",
        ),
        # Storneren zonder reden bestaat niet (zelfde discipline als afwijzen/uitsluiten).
        sa.CheckConstraint(
            "status != 'gestorneerd' OR (storno_reden IS NOT NULL AND length(btrim(storno_reden)) >= 5)",
            name="doorbelasting_boeking_storno_reden",
        ),
        schema="boekhouding",
    )
    _rls_op_administratie("doorbelasting_boeking")
    op.create_index(
        "doorbelasting_boeking_doc_doel_uniek",
        "doorbelasting_boeking",
        ["document_id", "mapping_id"],
        unique=True,
        postgresql_where=sa.text("status != 'gestorneerd'"),
        schema="boekhouding",
    )


    # Vierde reconciliatiebron: de acceptatielaag (0042) moet 'doorbelasting' als bron kennen,
    # anders kan een beoordeelde doorbelasting-afwijking nooit geaccepteerd worden.
    op.drop_constraint(
        "reconciliatie_acceptatie_bron_geldig", "reconciliatie_acceptatie", schema="boekhouding", type_="check"
    )
    op.create_check_constraint(
        "reconciliatie_acceptatie_bron_geldig",
        "reconciliatie_acceptatie",
        "bron IN ('documenten', 'bank', 'omzet', 'doorbelasting')",
        schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_constraint(
        "reconciliatie_acceptatie_bron_geldig", "reconciliatie_acceptatie", schema="boekhouding", type_="check"
    )
    op.create_check_constraint(
        "reconciliatie_acceptatie_bron_geldig",
        "reconciliatie_acceptatie",
        "bron IN ('documenten', 'bank', 'omzet')",
        schema="boekhouding",
    )
    for tabel in (
        "doorbelasting_boeking",
        "doorbelasting_regel",
        "doorbelasting_run",
        "doorbelasting_instelling",
        "doorbelasting_mapping",
    ):
        op.execute(f"REVOKE ALL ON boekhouding.{tabel} FROM {APP_ROLE}")
        op.drop_table(tabel, schema="boekhouding")
    op.drop_column("administratie", "doorbelasting_ingeschakeld", schema="platform")
