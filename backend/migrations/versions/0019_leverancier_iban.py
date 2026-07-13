"""Vertrouwde IBAN's per crediteur — fundament van de IBAN-wissel-fraudecontrole (CLAUDE.md
harde checks; open item 2026-07-13, hardening-audit na de e2e-boektest).

Meerwaardige set per (administratie, crediteur): meerdere bevestigde IBAN's is de NORM, geen
wissel-signaal — de G-rekening (WKA, gesplitste betaling) is in de bouwketen de standaard-case.
Een IBAN wordt nooit automatisch als G-rekening geclassificeerd (in NL niet betrouwbaar uit het
IBAN af te leiden): een mens bevestigt de tweede rekening, en daarmee ís hij vertrouwd.

`bron` legt vast hoe het IBAN in de set kwam: 'rlz_seed' (uit RLZ's Vendors/{id}/BankRelations —
IBAN-veld live geverifieerd 2026-07-13, zodat "eerste keer" niet blind is), 'baseline' (eerste
factuur-IBAN van een crediteur zonder seed — vastgelegd, zichtbaar ter bevestiging, niet
blokkerend want er is niets om mee te vergelijken) of 'bevestigd' (mens bevestigde een afwijkend
IBAN na een wissel-blokkade; `bevestigd_door` verplicht gevuld). Elke toevoeging krijgt een
audit_event — de IBAN-mutatie is juist het controlewaardige feit.

Bewust géén FK naar vendor_cache (zelfde overweging als leverancier_voorkeur, migratie 0017):
de vertrouwde set moet een sync-verdwijning van de crediteur overleven. RLS conform het
bestaande patroon.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "leverancier_iban",
        sa.Column(
            "administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), primary_key=True
        ),
        sa.Column("vendor_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("iban", sa.Text(), primary_key=True),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.Column("bevestigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("bron IN ('rlz_seed', 'baseline', 'bevestigd')", name="leverancier_iban_bron_geldig"),
        sa.CheckConstraint(
            "bron != 'bevestigd' OR bevestigd_door IS NOT NULL", name="leverancier_iban_bevestigd_door_verplicht"
        ),
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.leverancier_iban ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.leverancier_iban FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY leverancier_iban_scope ON boekhouding.leverancier_iban
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.leverancier_iban TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON boekhouding.leverancier_iban FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS leverancier_iban_scope ON boekhouding.leverancier_iban")
    op.drop_table("leverancier_iban", schema="boekhouding")
