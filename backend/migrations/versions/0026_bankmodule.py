"""Bankmodule (fase 2): leeskant + werkstaat.

Leeskant (caches van RLZ, bron van waarheid blijft RLZ — STAP 0 + schrijf-PoC 2026-08-02):
- boekhouding.payment_account_cache — rekeningen incl. kas (Type 3), saldo, versheid-probe
  (LastBankImport) en PSD2-gateway-velden; de onboarding-check "heeft deze klant aanlevering?".
- boekhouding.bank_mutatie — ruwe PaymentTransactions; `open_bedrag` (OpenAmount) is de
  leidende afgeletterd-indicator (IsComplete is stale na storno en wordt bewust niet gemodelleerd).
- boekhouding.payment_item_cache — open posten om tegen af te letteren.
- boekhouding.bank_sync_stand — CreateDate-watermark (incrementele sync) + laatste sync-moment.

Werkstaat (eigen tabellen, nooit kolommen op de caches — sync mag caches vrij overschrijven):
- boekhouding.bank_afletter_opdracht — assist-model: "af te letteren in Reeleezee" klaargezet,
  mens legt de koppeling in de RLZ-UI, sync verifieert op OpenAmount 0 (afletteren-tegen-open-
  post kan via de publieke API in géén enkele vorm — fallback-PoC). Hooguit één klaargezette
  opdracht per mutatie (partiële unique index).
- boekhouding.bank_boeking + bank_boeking_regel — directe grootboekboekingen
  (PUT BankMutationDirectBookings, schrijf-PoC §3); id = deterministisch RLZ-client-GUID.
  Eén GEBOEKTE boeking per mutatie (partiële unique index — na storno mag opnieuw).
- boekhouding.bank_regel — vaste regels (voorstel-volgorde stap 3), uniek per actieve
  tegenpartij-sleutel per administratie.

Platform:
- platform.administratie.bank_autoboeken_ingeschakeld — opt-in per administratie voor de
  volautomatische stappen (vaste regels automatisch boeken), default UIT; werkt bovenop de
  bestaande boeken-failsafes (toggle + globale kill switch).

Alle boekhouding-tabellen: RLS + FORCE (registers/conventies.md, geen uitzonderingen), GRANT
SELECT/INSERT/UPDATE aan boekhouding_app — géén DELETE (niets verdwijnt, kernprincipe 3/4);
bank_boeking_regel scoped via de bovenliggende bank_boeking (zelfde subquery-patroon als
boekvoorstel_regel, migratie 0008).

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"

def _sync_kolommen() -> list[sa.Column]:
    """Verse kolomobjecten per tabel (een sa.Column-instantie kan maar aan één tabel hangen)."""
    return [
        sa.Column(
            "laatst_gesynchroniseerd", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("verdwenen_uit_bron_op", sa.DateTime(timezone=True), nullable=True),
    ]


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
    # --- leeskant: caches ---------------------------------------------------------------------
    op.create_table(
        "payment_account_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("naam", sa.Text(), nullable=True),
        sa.Column("iban", sa.Text(), nullable=True),
        sa.Column("rekening_type", sa.SmallInteger(), nullable=True),
        sa.Column("saldo", sa.Numeric(14, 2), nullable=True),
        sa.Column("saldo_datum", sa.Date(), nullable=True),
        sa.Column("is_gearchiveerd", sa.Boolean(), nullable=True),
        sa.Column("gateway_state", sa.SmallInteger(), nullable=True),
        sa.Column("gateway_type", sa.SmallInteger(), nullable=True),
        sa.Column("laatste_import", JSONB, nullable=True),
        sa.Column("brondata", JSONB, nullable=False),
        *_sync_kolommen(),
        schema="boekhouding",
    )
    op.create_index(
        "ix_payment_account_cache_administratie_id",
        "payment_account_cache",
        ["administratie_id"],
        schema="boekhouding",
    )
    _rls_op_administratie("payment_account_cache")

    op.create_table(
        "bank_mutatie",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("payment_account_id", UUID(as_uuid=True), nullable=True),
        sa.Column("boekdatum", sa.Date(), nullable=True),
        sa.Column("bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("open_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("tegenrekening_iban", sa.Text(), nullable=True),
        sa.Column("tegenpartij_naam", sa.Text(), nullable=True),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        sa.Column("mutatie_type", sa.SmallInteger(), nullable=True),
        sa.Column("rlz_voorstel_item_id", UUID(as_uuid=True), nullable=True),
        sa.Column("rlz_create_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("brondata", JSONB, nullable=False),
        *_sync_kolommen(),
        schema="boekhouding",
    )
    # De werkvoorraad-query ("alle open mutaties van deze rekening/administratie") is de
    # hoofdroute — partiële index op open rijen houdt 'm snel, ook bij jaren historie.
    op.create_index(
        "ix_bank_mutatie_open",
        "bank_mutatie",
        ["administratie_id", "payment_account_id"],
        schema="boekhouding",
        postgresql_where=sa.text("open_bedrag IS NOT NULL AND open_bedrag <> 0"),
    )
    op.create_index("ix_bank_mutatie_administratie_id", "bank_mutatie", ["administratie_id"], schema="boekhouding")
    _rls_op_administratie("bank_mutatie")

    op.create_table(
        "payment_item_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("boekdatum", sa.Date(), nullable=True),
        sa.Column("vervaldatum", sa.Date(), nullable=True),
        sa.Column("referentie", sa.Text(), nullable=True),
        sa.Column("referentie2", sa.Text(), nullable=True),
        sa.Column("rlz_document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("payment_status", sa.SmallInteger(), nullable=True),
        sa.Column("brondata", JSONB, nullable=False),
        *_sync_kolommen(),
        schema="boekhouding",
    )
    op.create_index(
        "ix_payment_item_cache_administratie_id", "payment_item_cache", ["administratie_id"], schema="boekhouding"
    )
    _rls_op_administratie("payment_item_cache")

    op.create_table(
        "bank_sync_stand",
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("mutaties_watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("laatste_sync_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    _rls_op_administratie("bank_sync_stand")

    # --- werkstaat: afletter-opdrachten (assist-model) ----------------------------------------
    op.create_table(
        "bank_afletter_opdracht",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("payment_transaction_id", UUID(as_uuid=True), nullable=False),
        sa.Column("payment_item_id", UUID(as_uuid=True), nullable=True),
        sa.Column("rlz_document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("voorstel_detail", JSONB, nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="klaargezet"),
        sa.Column("klaargezet_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("klaargezet_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("geverifieerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verificatie_detail", JSONB, nullable=True),
        sa.Column("ingetrokken_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("ingetrokken_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('klaargezet', 'geverifieerd', 'ingetrokken')", name="bank_afletter_opdracht_status_geldig"
        ),
        sa.CheckConstraint(
            "(status = 'geverifieerd') = (geverifieerd_op IS NOT NULL)",
            name="bank_afletter_opdracht_verificatie_consistent",
        ),
        sa.CheckConstraint(
            "(status = 'ingetrokken') = (ingetrokken_op IS NOT NULL)",
            name="bank_afletter_opdracht_intrekking_consistent",
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ux_bank_afletter_opdracht_open",
        "bank_afletter_opdracht",
        ["administratie_id", "payment_transaction_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status = 'klaargezet'"),
    )
    _rls_op_administratie("bank_afletter_opdracht")

    # --- werkstaat: directe grootboekboekingen ------------------------------------------------
    op.create_table(
        "bank_boeking",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("payment_transaction_id", UUID(as_uuid=True), nullable=False),
        sa.Column("rlz_document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        sa.Column("rlz_boekstuknummer", sa.Text(), nullable=True),
        sa.Column("bron", sa.Text(), nullable=False, server_default="handmatig"),
        sa.Column("status", sa.Text(), nullable=False, server_default="geboekt"),
        sa.Column("geboekt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("geboekt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gestorneerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gestorneerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("storno_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("bron IN ('handmatig', 'vaste_regel', 'automatisch')", name="bank_boeking_bron_geldig"),
        sa.CheckConstraint("status IN ('geboekt', 'gestorneerd')", name="bank_boeking_status_geldig"),
        sa.CheckConstraint(
            "(status = 'gestorneerd') = (gestorneerd_op IS NOT NULL)", name="bank_boeking_storno_consistent"
        ),
        schema="boekhouding",
    )
    op.create_index(
        "ux_bank_boeking_actief_per_mutatie",
        "bank_boeking",
        ["administratie_id", "payment_transaction_id"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("status = 'geboekt'"),
    )
    _rls_op_administratie("bank_boeking")

    op.create_table(
        "bank_boeking_regel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bank_boeking_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.bank_boeking.id"), nullable=False
        ),
        sa.Column("volgnummer", sa.Integer(), nullable=False),
        sa.Column("ledger_id", UUID(as_uuid=True), nullable=False),
        sa.Column("taxrate_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("netto_bedrag", sa.Numeric(14, 2), nullable=False),
        sa.Column("btw_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        schema="boekhouding",
    )
    op.create_index(
        "ix_bank_boeking_regel_boeking_id", "bank_boeking_regel", ["bank_boeking_id"], schema="boekhouding"
    )
    op.execute("ALTER TABLE boekhouding.bank_boeking_regel ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.bank_boeking_regel FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY bank_boeking_regel_scope ON boekhouding.bank_boeking_regel
        USING (EXISTS (
            SELECT 1 FROM boekhouding.bank_boeking b
            WHERE b.id = bank_boeking_id AND b.administratie_id = platform.current_administratie_id()
        ))
        WITH CHECK (EXISTS (
            SELECT 1 FROM boekhouding.bank_boeking b
            WHERE b.id = bank_boeking_id AND b.administratie_id = platform.current_administratie_id()
        ))
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.bank_boeking_regel TO {APP_ROLE}")

    # --- werkstaat: vaste regels ---------------------------------------------------------------
    op.create_table(
        "bank_regel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False
        ),
        sa.Column("tegenpartij_sleutel", sa.Text(), nullable=False),
        sa.Column("tegenrekening_iban", sa.Text(), nullable=True),
        sa.Column("ledger_id", UUID(as_uuid=True), nullable=False),
        sa.Column("taxrate_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("gedeactiveerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gedeactiveerd_op", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("tegenpartij_sleutel <> ''", name="bank_regel_sleutel_niet_leeg"),
        schema="boekhouding",
    )
    op.create_index(
        "ux_bank_regel_actief_per_tegenpartij",
        "bank_regel",
        ["administratie_id", "tegenpartij_sleutel"],
        unique=True,
        schema="boekhouding",
        postgresql_where=sa.text("actief"),
    )
    _rls_op_administratie("bank_regel")

    # --- platform: opt-in autoboek-toggle -------------------------------------------------------
    op.add_column(
        "administratie",
        sa.Column("bank_autoboeken_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("administratie", "bank_autoboeken_ingeschakeld", schema="platform")
    for tabel in (
        "bank_regel",
        "bank_boeking_regel",
        "bank_boeking",
        "bank_afletter_opdracht",
        "bank_sync_stand",
        "payment_item_cache",
        "bank_mutatie",
        "payment_account_cache",
    ):
        op.execute(f"REVOKE ALL ON boekhouding.{tabel} FROM {APP_ROLE}")
        op.execute(f"DROP POLICY IF EXISTS {tabel}_scope ON boekhouding.{tabel}")
        op.drop_table(tabel, schema="boekhouding")
