"""Doorbelasting × projecten + verdeelsleutels (besluit Peter 25-08 "optie 2", RLZ-feedbackronde
deel 2 punt 2 — dicht het gat dat spiegel-inkoopfacturen aan `project_verplicht` van de
doel-administratie ontsnapten).

a. Per verdeelregel een PROJECT uit de doel-administratie (`doorbelasting_regel.project_id` =
   RLZ-project-GUID in de doel-administratie; verplicht + blokkerende check zodra de
   doel-administratie project_verplicht aan heeft). De spiegel-inkoopfactuurregels dragen het.
b. MULTI-PROJECT binnen één doelentiteit (casus: 1 factuur over 40 panden): één rij per
   project; `project_aandeel` = fractie van het doelentiteit-deel (som 1 per bron-regel ×
   doelentiteit), `verdeelbasis` = 'm2' (contract-m² uit project_specificatie, ontbrekend =
   geweigerd bij opslaan) óf 'gelijk'; `m2` = de m² waarop verdeeld is (herleidbaar). De unieke
   sleutel wordt (run, bron-regel, doelentiteit, project) mét NULLS NOT DISTINCT (PG15+): één
   rij zonder project per combinatie blijft even hard uniek als voorheen.
c. VERDEELSLEUTELS: `doorbelasting_verdeelsleutel` — herbruikbare verdeling per
   bron-administratie (naam + versie, append-only: opnieuw opslaan onder dezelfde naam = nieuwe
   versie, oude versie inactief maar bewaard; GRANT zonder DELETE). Welke sleutel(versie) op
   welke run is toegepast staat op de run (`verdeelsleutel_id` + `verdeelsleutel_toegepast_op`)
   én in het audit_event — QoE-eis herleidbaarheid.

Revision ID: 0067
Revises: 0066
Create Date: 2026-08-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    # --- c. verdeelsleutels ------------------------------------------------------------------
    op.create_table(
        "doorbelasting_verdeelsleutel",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("naam", sa.Text(), nullable=False),
        sa.Column("versie", sa.Integer(), nullable=False),
        sa.Column("actief", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("definitie", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("aangemaakt_door", sa.UUID(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["aangemaakt_door"], ["platform.gebruiker.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("administratie_id", "naam", "versie", name="doorbelasting_verdeelsleutel_naam_versie"),
        sa.CheckConstraint("versie >= 1", name="doorbelasting_verdeelsleutel_versie"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_doorbelasting_verdeelsleutel_administratie_id",
        "doorbelasting_verdeelsleutel",
        ["administratie_id"],
        unique=False,
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.doorbelasting_verdeelsleutel ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.doorbelasting_verdeelsleutel FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY doorbelasting_verdeelsleutel_scope ON boekhouding.doorbelasting_verdeelsleutel
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    # Append-only per versie: geen DELETE — een eerder toegepaste sleutelversie blijft herleidbaar.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.doorbelasting_verdeelsleutel TO {APP_ROLE}")

    # --- a/b. project per verdeelregel + multi-project ----------------------------------------
    op.add_column("doorbelasting_regel", sa.Column("project_id", sa.UUID(), nullable=True), schema="boekhouding")
    op.add_column(
        "doorbelasting_regel",
        sa.Column("project_aandeel", sa.Numeric(precision=9, scale=6), nullable=True),
        schema="boekhouding",
    )
    op.add_column("doorbelasting_regel", sa.Column("verdeelbasis", sa.Text(), nullable=True), schema="boekhouding")
    op.add_column(
        "doorbelasting_regel", sa.Column("m2", sa.Numeric(precision=10, scale=2), nullable=True), schema="boekhouding"
    )
    op.create_check_constraint(
        "doorbelasting_regel_verdeelbasis",
        "doorbelasting_regel",
        "verdeelbasis IS NULL OR verdeelbasis IN ('m2', 'gelijk')",
        schema="boekhouding",
    )
    op.create_check_constraint(
        "doorbelasting_regel_project_aandeel",
        "doorbelasting_regel",
        "project_aandeel IS NULL OR (project_aandeel > 0 AND project_aandeel <= 1)",
        schema="boekhouding",
    )
    op.drop_constraint("doorbelasting_regel_uniek", "doorbelasting_regel", schema="boekhouding", type_="unique")
    op.create_unique_constraint(
        "doorbelasting_regel_uniek",
        "doorbelasting_regel",
        ["run_id", "bron_regel_id", "mapping_id", "project_id"],
        schema="boekhouding",
        postgresql_nulls_not_distinct=True,
    )

    # --- c. herleidbaarheid op de run ---------------------------------------------------------
    op.add_column("doorbelasting_run", sa.Column("verdeelsleutel_id", sa.UUID(), nullable=True), schema="boekhouding")
    op.add_column(
        "doorbelasting_run",
        sa.Column("verdeelsleutel_toegepast_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.create_foreign_key(
        "fk_doorbelasting_run_verdeelsleutel",
        "doorbelasting_run",
        "doorbelasting_verdeelsleutel",
        ["verdeelsleutel_id"],
        ["id"],
        source_schema="boekhouding",
        referent_schema="boekhouding",
    )


def downgrade() -> None:
    op.drop_constraint("fk_doorbelasting_run_verdeelsleutel", "doorbelasting_run", schema="boekhouding", type_="foreignkey")
    op.drop_column("doorbelasting_run", "verdeelsleutel_toegepast_op", schema="boekhouding")
    op.drop_column("doorbelasting_run", "verdeelsleutel_id", schema="boekhouding")
    op.drop_constraint("doorbelasting_regel_uniek", "doorbelasting_regel", schema="boekhouding", type_="unique")
    # Terugdraaien vergt menselijk oordeel: multi-project-rijen (zelfde run/bron-regel/mapping)
    # botsen op de oude sleutel — eerst samenvoegen of verwijderen.
    op.create_unique_constraint(
        "doorbelasting_regel_uniek", "doorbelasting_regel", ["run_id", "bron_regel_id", "mapping_id"], schema="boekhouding"
    )
    op.drop_constraint("doorbelasting_regel_project_aandeel", "doorbelasting_regel", schema="boekhouding", type_="check")
    op.drop_constraint("doorbelasting_regel_verdeelbasis", "doorbelasting_regel", schema="boekhouding", type_="check")
    op.drop_column("doorbelasting_regel", "m2", schema="boekhouding")
    op.drop_column("doorbelasting_regel", "verdeelbasis", schema="boekhouding")
    op.drop_column("doorbelasting_regel", "project_aandeel", schema="boekhouding")
    op.drop_column("doorbelasting_regel", "project_id", schema="boekhouding")
    op.execute(f"REVOKE ALL ON boekhouding.doorbelasting_verdeelsleutel FROM {APP_ROLE}")
    op.drop_index(
        "ix_doorbelasting_verdeelsleutel_administratie_id", table_name="doorbelasting_verdeelsleutel", schema="boekhouding"
    )
    op.drop_table("doorbelasting_verdeelsleutel", schema="boekhouding")
