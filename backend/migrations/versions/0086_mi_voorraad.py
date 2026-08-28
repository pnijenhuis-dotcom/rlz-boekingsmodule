"""Voorraad-aansluiting fase 1 — Universal Verkoop (bouwrun 28-08 blok D, mockup
voorraad-aansluiting.html = bouwnorm; besluiten Peter 28-08: parallel bouwen, dagniveau-mutaties,
normalisatie VOLAUTOMATISCH zonder verplicht klikwerk). Eerste bewoner van het `mi`-schema (de
Jarvis-fundering: feitenlaag op regelniveau).

1. platform.administratie.voorraad_ingeschakeld — opt-in "Voorraad bijhouden" (Beheerder-only,
   default UIT; aan voor Universal Verkoop pas op Peters klik).
2. mi.artikelgroep — genormaliseerde artikelgroepen per administratie (eenheid, tolerantie-% default 1).
3. mi.normalisatie_regel — deterministische regel per (administratie, leverancier, genormaliseerde
   artikeltekst) → artikelgroep óf uitgesloten (dienst/transport); bron 'ai' (eerste match, direct
   toegepast) of 'handmatig' (correctie — herrekent historie). Vendor-sentinel UUID(0) = onbekend.
4. mi.voorraad_regel — de feiten: regel-niveau in-/uitstroom (artikeltekst, aantal, eenheid, prijs,
   bedrag, datum) uit het inkoop-veldvoorstel (extern document) resp. verkoopfactuurregels; mét de
   normalisatie-uitkomst + zekerheid. Afgeleide feitenlaag (herrekenbaar) — daarom óók DELETE-grant.
5. mi.voorraad_telling — systeemstand fase 1 = handmatige telling per artikelgroep per datum.
NOOIT RLZ-writes, niets geboekt — puur signaal. RLS per administratie; `GRANT USAGE ON SCHEMA mi`.

Revision ID: 0086
Revises: 0085
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0086"
down_revision: str | None = "0085"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"
SCHEMA = "mi"


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
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}")

    op.add_column(
        "administratie",
        sa.Column("voorraad_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="platform",
    )

    op.create_table(
        "artikelgroep",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("eenheid", sa.Text(), nullable=False, server_default="st"),
        sa.Column("tolerantie_pct", sa.Numeric(5, 2), nullable=False, server_default="1.00"),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("aangemaakt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("tolerantie_pct >= 0 AND tolerantie_pct <= 100", name="ck_artikelgroep_tolerantie"),
        schema=SCHEMA,
    )
    op.create_index("ix_artikelgroep_administratie_id", "artikelgroep", ["administratie_id"], schema=SCHEMA)
    op.execute(
        f"CREATE UNIQUE INDEX uq_artikelgroep_naam ON {SCHEMA}.artikelgroep (administratie_id, lower(naam)) WHERE actief"
    )
    _rls("artikelgroep")

    op.create_table(
        "normalisatie_regel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("artikeltekst_norm", sa.Text(), nullable=False),
        sa.Column("artikelgroep_id", UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.artikelgroep.id"), nullable=True),
        sa.Column("uitgesloten", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("zekerheid", sa.Numeric(4, 3), nullable=True),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("bijgewerkt_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("bron IN ('ai', 'handmatig', 'regel')", name="ck_normalisatie_regel_bron"),
        sa.UniqueConstraint("administratie_id", "vendor_id", "artikeltekst_norm", name="uq_normalisatie_regel_tekst"),
        schema=SCHEMA,
    )
    _rls("normalisatie_regel")

    op.create_table(
        "voorraad_regel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("boekhouding.document.id"), nullable=False),
        sa.Column("richting", sa.Text(), nullable=False),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("relatie_naam", sa.Text(), nullable=True),
        sa.Column("regel_volgnummer", sa.Integer(), nullable=False),
        sa.Column("artikeltekst", sa.Text(), nullable=False),
        sa.Column("aantal", sa.Numeric(12, 3), nullable=True),
        sa.Column("eenheid", sa.Text(), nullable=True),
        sa.Column("prijs", sa.Numeric(14, 4), nullable=True),
        sa.Column("netto_bedrag", sa.Numeric(14, 2), nullable=True),
        sa.Column("artikelgroep_id", UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.artikelgroep.id"), nullable=True),
        sa.Column("normalisatie_status", sa.Text(), nullable=False),
        sa.Column("normalisatie_zekerheid", sa.Numeric(4, 3), nullable=True),
        sa.Column("bijgewerkt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("richting IN ('in', 'uit')", name="ck_voorraad_regel_richting"),
        sa.CheckConstraint(
            "normalisatie_status IN ('genormaliseerd', 'onzeker', 'uitgesloten', 'niet_genormaliseerd')",
            name="ck_voorraad_regel_status",
        ),
        sa.UniqueConstraint("document_id", "richting", "regel_volgnummer", name="uq_voorraad_regel_document_regel"),
        schema=SCHEMA,
    )
    op.create_index("ix_voorraad_regel_administratie_datum", "voorraad_regel", ["administratie_id", "datum"], schema=SCHEMA)
    op.create_index("ix_voorraad_regel_artikelgroep_id", "voorraad_regel", ["artikelgroep_id"], schema=SCHEMA)
    _rls("voorraad_regel", met_delete=True)

    op.create_table(
        "voorraad_telling",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=False),
        sa.Column("artikelgroep_id", UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.artikelgroep.id"), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("aantal", sa.Numeric(12, 3), nullable=False),
        sa.Column("opmerking", sa.Text(), nullable=True),
        sa.Column("ingevoerd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=False),
        sa.Column("ingevoerd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("artikelgroep_id", "datum", name="uq_voorraad_telling_groep_datum"),
        schema=SCHEMA,
    )
    op.create_index("ix_voorraad_telling_administratie_id", "voorraad_telling", ["administratie_id"], schema=SCHEMA)
    _rls("voorraad_telling")


def downgrade() -> None:
    for tabel in ("voorraad_telling", "voorraad_regel", "normalisatie_regel", "artikelgroep"):
        op.execute(f"DROP POLICY IF EXISTS {tabel}_scope ON {SCHEMA}.{tabel}")
    op.drop_table("voorraad_telling", schema=SCHEMA)
    op.drop_table("voorraad_regel", schema=SCHEMA)
    op.drop_table("normalisatie_regel", schema=SCHEMA)
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.uq_artikelgroep_naam")
    op.drop_table("artikelgroep", schema=SCHEMA)
    op.drop_column("administratie", "voorraad_ingeschakeld", schema="platform")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
