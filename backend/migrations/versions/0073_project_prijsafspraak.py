"""Steigerbouw-run blok B1 (feedbackronde Peter 23-08 punt 8, mockup projecten-invoer.html
"Prijsafspraken veldwerkers — dit project"): projectspecifieke prijsafspraken per veldwerker.

`project_prijsafspraak`: per (project × veldwerker) een tarief mét eenheid (uur | m2) en een
geldigheidsvenster in ISO-weken (vanaf/t/m, beide optioneel = hele project). De factuurmatch
rekent per weekstaat: projectafspraak wint → anders koppeling-tarief → anders onbepaalbaar
(nooit gokken); eenheid m² rekent met de goedgekeurde m² uit de weekstaten i.p.v. uren.
Append-only: intrekken = `ingetrokken_op` (reden verplicht, DB-CHECK), nooit DELETE; RLS per
administratie (patroon 0056). Schrijven = Beheerder + Boekhouding+Projecten (service), geaudit.

Revision ID: 0073
Revises: 0072
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "project_prijsafspraak",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("administratie_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("gebruiker_id", sa.UUID(), nullable=False),
        sa.Column("eenheid", sa.Text(), nullable=False),
        sa.Column("tarief", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("geldig_vanaf_jaar", sa.Integer(), nullable=True),
        sa.Column("geldig_vanaf_week", sa.Integer(), nullable=True),
        sa.Column("geldig_tm_jaar", sa.Integer(), nullable=True),
        sa.Column("geldig_tm_week", sa.Integer(), nullable=True),
        sa.Column("toelichting", sa.Text(), nullable=True),
        sa.Column("aangemaakt_door", sa.UUID(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ingetrokken_door", sa.UUID(), nullable=True),
        sa.Column("ingetrokken_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingetrokken_reden", sa.Text(), nullable=True),
        sa.CheckConstraint("eenheid IN ('uur', 'm2')", name="ck_project_prijsafspraak_eenheid"),
        sa.CheckConstraint("tarief >= 0", name="ck_project_prijsafspraak_tarief"),
        sa.CheckConstraint(
            "(geldig_vanaf_jaar IS NULL) = (geldig_vanaf_week IS NULL)", name="ck_project_prijsafspraak_vanaf_samen"
        ),
        sa.CheckConstraint("(geldig_tm_jaar IS NULL) = (geldig_tm_week IS NULL)", name="ck_project_prijsafspraak_tm_samen"),
        sa.CheckConstraint(
            "geldig_vanaf_week IS NULL OR (geldig_vanaf_week BETWEEN 1 AND 53)", name="ck_project_prijsafspraak_vanaf_week"
        ),
        sa.CheckConstraint("geldig_tm_week IS NULL OR (geldig_tm_week BETWEEN 1 AND 53)", name="ck_project_prijsafspraak_tm_week"),
        sa.CheckConstraint(
            "ingetrokken_op IS NULL OR (ingetrokken_reden IS NOT NULL AND length(btrim(ingetrokken_reden)) > 0)",
            name="ck_project_prijsafspraak_ingetrokken_reden",
        ),
        sa.ForeignKeyConstraint(["administratie_id"], ["platform.administratie.id"]),
        sa.ForeignKeyConstraint(["gebruiker_id"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(["aangemaakt_door"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(["ingetrokken_door"], ["platform.gebruiker.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_project_prijsafspraak_project_cache",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="boekhouding",
    )
    op.create_index(
        "ix_project_prijsafspraak_administratie_id", "project_prijsafspraak", ["administratie_id"], schema="boekhouding"
    )
    op.create_index(
        "ix_project_prijsafspraak_project",
        "project_prijsafspraak",
        ["administratie_id", "project_id", "gebruiker_id"],
        schema="boekhouding",
    )
    op.execute("ALTER TABLE boekhouding.project_prijsafspraak ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE boekhouding.project_prijsafspraak FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY project_prijsafspraak_scope ON boekhouding.project_prijsafspraak
        USING (administratie_id = platform.current_administratie_id())
        WITH CHECK (administratie_id = platform.current_administratie_id())
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON boekhouding.project_prijsafspraak TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_project_prijsafspraak_project", table_name="project_prijsafspraak", schema="boekhouding")
    op.drop_index("ix_project_prijsafspraak_administratie_id", table_name="project_prijsafspraak", schema="boekhouding")
    op.drop_table("project_prijsafspraak", schema="boekhouding")
