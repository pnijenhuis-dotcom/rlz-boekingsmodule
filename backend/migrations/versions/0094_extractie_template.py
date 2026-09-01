"""Deterministische extractie-terugval — template per bekende leverancier (best-practice-besluit 2,
31-08; aanleiding: AI-extractie als single point of failure — schema-bug 30/31-08 en de AI-kostengrens
legden élke extractie plat — én AI-kosten op facturen die er elke maand identiek uitzien).

`boekhouding.extractie_template`: één rij per crediteur-sleutel (btw-nummer > KvK-nummer >
administratie+crediteur) met de geleerde ankerdefinitie (JSONB), de leerdocumenten (opake id's),
geldigheid mét reden, versie en gebruiksteller. Geleerd uit N ≥ 3 mens-bevestigde (geboekte)
PDF-facturen, pas geldig als hij ze álle exact reproduceert; ongeldig zodra hij op een nieuw document
faalt of door de controleur gecorrigeerd wordt — het document loopt dan het AI-pad, en ná nieuwe
bevestigingen leert het systeem vanzelf opnieuw. Geen handmatig templatebeheer.

BEWUST GEEN RLS (zie app/extractie/models.py): de rij bevat uitsluitend leverancier-layout-metadata
(ankerwoorden, vormpatroon factuurnummer, btw-percentages) — geen klantgegevens — en de kenmerk-
sleutel is juist bedoeld om over administraties heen te werken. Geen DELETE-grant: templates
worden ongeldig gemarkeerd of in versie verhoogd, nooit verwijderd. Schema-only.

Revision ID: 0094
Revises: 0093
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0094"
down_revision: str | None = "0093"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "extractie_template",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("sleutel", sa.Text(), nullable=False),
        sa.Column("sleutel_soort", sa.Text(), nullable=False),
        sa.Column("administratie_id", UUID(as_uuid=True), sa.ForeignKey("platform.administratie.id"), nullable=True),
        sa.Column("vendor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("definitie", JSONB(), nullable=False),
        sa.Column("geleerd_uit", JSONB(), nullable=False),
        sa.Column("geleerd_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("versie", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("geldig", sa.Boolean(), nullable=False),
        sa.Column("ongeldig_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ongeldig_reden", sa.Text(), nullable=True),
        sa.Column("gebruikt_aantal", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("laatst_gebruikt_op", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("sleutel", name="uq_extractie_template_sleutel"),
        sa.CheckConstraint(
            "sleutel_soort IN ('btw_nummer', 'kvk_nummer', 'administratie_vendor')",
            name="ck_extractie_template_sleutel_soort",
        ),
        schema="boekhouding",
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.extractie_template TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("extractie_template", schema="boekhouding")
