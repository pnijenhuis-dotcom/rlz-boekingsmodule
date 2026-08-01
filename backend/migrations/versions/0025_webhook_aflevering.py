"""Webhook-afleveraar + HMAC-per-verzendpoging (Platform OPEN_ITEMS webhook-item, actiepunt 2).

De kern-fix: de outbox bewaarde tot nu toe de GETEKENDE payload (timestamp/nonce/handtekening
berekend bij het bóéken). Met een replay-venster van ~5 min (koppelcontract §3) wijst de
ontvanger elke aflevering die later dan ~5 min na het boeken plaatsvindt — precies het normale
outbox-/retry-scenario — per definitie af. Vanaf deze migratie ligt de payload ONGETEKEND vast
({schema_version, event, data}); timestamp + nonce + handtekening worden pas bij elke
verzendpoging berekend (app/documenten/webhook_afleveraar.py). Het wire-formaat verandert niet:
de afleveraar verstuurt dezelfde envelope als die hier vroeger opgeslagen stond.

Drie onderdelen:
1. Bestaande outbox-rijen: de handtekeningvelden uit de opgeslagen payload strippen — ze zijn
   waardeloos (verlopen zodra de afleveraar draait) en de afleveraar tekent toch per poging.
2. Afleverstatus op de outbox-rij: `status` (openstaand/afgeleverd/mislukt — mislukt =
   dead-letter na max pogingen, zichtbaar en nooit stil), `pogingen`, `laatste_poging_op`,
   `laatste_fout`, `volgende_poging_op` (retry/backoff). De oude partiële index op
   `afgeleverd_op IS NULL` wordt vervangen door één op de rijen die de afleveraar echt zoekt.
3. `platform.webhook_instelling`: singleton-toggle voor de aflevering, parallel aan de
   boeken-kill-switch (migratie 0008) maar met default UIT — vastgoed's ontvanger bestaat nog
   niet, dus rijen blijven openstaand totdat een Beheerder de aflevering expliciet aanzet.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "boekhouding_app"


def upgrade() -> None:
    # --- 1. bestaande payloads ongetekend maken ----------------------------------------------
    op.execute(
        "UPDATE boekhouding.webhook_uitgaand "
        "SET payload = (payload - 'timestamp' - 'nonce' - 'handtekening')"
    )

    # --- 2. afleverstatus + retry/backoff-velden ---------------------------------------------
    op.add_column(
        "webhook_uitgaand",
        sa.Column("status", sa.Text(), nullable=False, server_default="openstaand"),
        schema="boekhouding",
    )
    op.create_check_constraint(
        "webhook_uitgaand_status_geldig",
        "webhook_uitgaand",
        "status IN ('openstaand', 'afgeleverd', 'mislukt')",
        schema="boekhouding",
    )
    op.add_column(
        "webhook_uitgaand",
        sa.Column("pogingen", sa.Integer(), nullable=False, server_default="0"),
        schema="boekhouding",
    )
    op.add_column(
        "webhook_uitgaand",
        sa.Column("laatste_poging_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    op.add_column(
        "webhook_uitgaand",
        sa.Column("laatste_fout", sa.Text(), nullable=True),
        schema="boekhouding",
    )
    op.add_column(
        "webhook_uitgaand",
        sa.Column("volgende_poging_op", sa.DateTime(timezone=True), nullable=True),
        schema="boekhouding",
    )
    # Consistentie met de bestaande kolom: een rij die ooit als afgeleverd gemarkeerd is
    # (afgeleverd_op gevuld — bestaat in de praktijk nog niet, maar de kolom wel) krijgt de
    # bijbehorende status.
    op.execute("UPDATE boekhouding.webhook_uitgaand SET status = 'afgeleverd' WHERE afgeleverd_op IS NOT NULL")

    op.drop_index("ix_webhook_uitgaand_onafgeleverd", table_name="webhook_uitgaand", schema="boekhouding")
    op.create_index(
        "ix_webhook_uitgaand_openstaand",
        "webhook_uitgaand",
        ["volgende_poging_op"],
        schema="boekhouding",
        postgresql_where=sa.text("status = 'openstaand'"),
    )

    # --- 3. aflevering-toggle (singleton, default UIT) ---------------------------------------
    op.create_table(
        "webhook_instelling",
        sa.Column("singleton", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("aflevering_ingeschakeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gewijzigd_door", UUID(as_uuid=True), sa.ForeignKey("platform.gebruiker.id"), nullable=True),
        sa.Column("gewijzigd_op", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("singleton", name="webhook_instelling_singleton"),
        schema="platform",
    )
    op.execute("INSERT INTO platform.webhook_instelling (singleton, aflevering_ingeschakeld) VALUES (true, false)")
    op.execute(f"GRANT SELECT, UPDATE ON platform.webhook_instelling TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform.webhook_instelling FROM {APP_ROLE}")
    op.drop_table("webhook_instelling", schema="platform")

    op.drop_index("ix_webhook_uitgaand_openstaand", table_name="webhook_uitgaand", schema="boekhouding")
    op.create_index(
        "ix_webhook_uitgaand_onafgeleverd",
        "webhook_uitgaand",
        ["afgeleverd_op"],
        schema="boekhouding",
        postgresql_where=sa.text("afgeleverd_op IS NULL"),
    )
    op.drop_column("webhook_uitgaand", "volgende_poging_op", schema="boekhouding")
    op.drop_column("webhook_uitgaand", "laatste_fout", schema="boekhouding")
    op.drop_column("webhook_uitgaand", "laatste_poging_op", schema="boekhouding")
    op.drop_column("webhook_uitgaand", "pogingen", schema="boekhouding")
    op.drop_constraint("webhook_uitgaand_status_geldig", "webhook_uitgaand", schema="boekhouding")
    op.drop_column("webhook_uitgaand", "status", schema="boekhouding")
    # De gestripte handtekeningvelden komen bewust niet terug: ze waren bij aflevering toch
    # ongeldig (replay-venster) en de secret om ze te herberekenen hoort niet in een migratie.
