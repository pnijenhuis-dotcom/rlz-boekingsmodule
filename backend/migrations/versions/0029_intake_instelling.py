"""Intake-AI-toggle als platform-instelling (Beheerder-knop; env blijft fallback).

De AVG-gate voor AI op nog-niet-toegewezen intake-documenten (tenaamstelling-lezen +
multi-factuur-splitsingsdetectie) was tot nu toe alleen een env-setting
(`settings.intake_ai_ingeschakeld`). Deze migratie maakt er een platform-instelling van,
zelfde singleton-patroon als `webhook_instelling` (0025) en `boeken_instelling` (0008):
Beheerder-only aan/uit via de UI/CLI, elke wijziging in het audit_event. Default UIT —
zonder expliciete opt-in gaat er geen intake-byte naar de Claude API.

De env-setting blijft uitsluitend FALLBACK voor als deze rij ontbreekt (migratie nog niet
toegepast, bv. losse scripts tegen een oude database) — zodra de rij bestaat is de
DB-instelling leidend (zie app/beheer/service.py::intake_ai_effectief_ingeschakeld).

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    op.create_table(
        "intake_instelling",
        sa.Column("singleton", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("ai_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gewijzigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("singleton", name="intake_instelling_singleton"),
        schema="platform",
    )
    op.execute("INSERT INTO platform.intake_instelling (singleton, ai_ingeschakeld) VALUES (true, false)")
    op.execute(f"GRANT SELECT, UPDATE ON platform.intake_instelling TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.intake_instelling FROM {APP_ROLE}")
    op.drop_table("intake_instelling", schema="platform")
