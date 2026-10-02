"""Webhook-outbox: 409 `niet_koppelbaar` van Vastly = status `wacht_op_ontvanger` (run A 02-10 punt 17, Peter 02-10;
BESLISSINGEN "RUN A 02-10 — BOEKEN, PROJECTEN, MELDINGEN, KLEINE BUGS (Peter 02-10)").

Tot 02-10 viel een 409 "nog niet koppelbaar" (koppelcontract §3c, voorstel-3c-409: onbekende_administratie /
onbekend_document / referentie_conflict) onder de gewone retry (8 pogingen, backoff ≤ 3600 s) en stond het event
ná ≈ 2 uur definitief `mislukt` — terwijl de ontvanger alleen zei "nog niet". Sinds 02-10 is dat een eigen,
zichtbare status mét oplopende cadans (1 u → 6 u → 24 u → dagelijks, max 14 dagen vanaf de eerste 409), daarna pas
`mislukt` mét de reden uit de body.

- CHECK `webhook_uitgaand_status_geldig` krijgt de vierde waarde `wacht_op_ontvanger`;
- `wacht_op_ontvanger_sinds` (timestamptz, NULL) = moment van de eerste 409 — de 14-dagen-grens en de cadans rekenen
  hiervandaan; NULL = nooit gewacht;
- `wacht_pogingen` (int, 0) = aantal 409-pogingen — telt NIET mee voor de dead-letter-grens van 8;
- de partiële index op `volgende_poging_op` dekt beide actieve statussen.
Schema-only; geen datawijziging (de elf events van 01-10 zijn al `verwerkt`).

Revision ID: 0175
Revises: 0174
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0175"
down_revision: str | None = "0174"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABEL = "webhook_uitgaand"
_SCHEMA = "boekhouding"
_CHECK = "webhook_uitgaand_status_geldig"
_INDEX = "ix_webhook_uitgaand_openstaand"


def upgrade() -> None:
    op.drop_constraint(_CHECK, _TABEL, schema=_SCHEMA, type_="check")
    op.create_check_constraint(
        _CHECK,
        _TABEL,
        "status IN ('openstaand', 'afgeleverd', 'mislukt', 'wacht_op_ontvanger')",
        schema=_SCHEMA,
    )
    op.add_column(
        _TABEL, sa.Column("wacht_op_ontvanger_sinds", sa.DateTime(timezone=True), nullable=True), schema=_SCHEMA
    )
    op.add_column(
        _TABEL, sa.Column("wacht_pogingen", sa.Integer(), nullable=False, server_default="0"), schema=_SCHEMA
    )
    op.drop_index(_INDEX, table_name=_TABEL, schema=_SCHEMA)
    op.create_index(
        _INDEX,
        _TABEL,
        ["volgende_poging_op"],
        schema=_SCHEMA,
        postgresql_where=sa.text("status IN ('openstaand', 'wacht_op_ontvanger')"),
    )


def downgrade() -> None:
    # Een wachtende rij wordt weer een gewone openstaande rij (de afleveraar van vóór 0175 pakt 'm dan op).
    op.execute(f"UPDATE {_SCHEMA}.{_TABEL} SET status = 'openstaand' WHERE status = 'wacht_op_ontvanger'")
    op.drop_index(_INDEX, table_name=_TABEL, schema=_SCHEMA)
    op.create_index(
        _INDEX, _TABEL, ["volgende_poging_op"], schema=_SCHEMA, postgresql_where=sa.text("status = 'openstaand'")
    )
    op.drop_column(_TABEL, "wacht_pogingen", schema=_SCHEMA)
    op.drop_column(_TABEL, "wacht_op_ontvanger_sinds", schema=_SCHEMA)
    op.drop_constraint(_CHECK, _TABEL, schema=_SCHEMA, type_="check")
    op.create_check_constraint(_CHECK, _TABEL, "status IN ('openstaand', 'afgeleverd', 'mislukt')", schema=_SCHEMA)
