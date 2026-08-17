"""Native push voor de store-apps (fase 3, GO Peter 2026-08-16): tweede subscriptie-soort.

`platform.push_subscriptie` krijgt een `soort`-kolom (webpush | apns | fcm — rapport
verkenning/17 (b): APNs direct voor iOS + FCM voor Android, achter één adapterlaag).
Voor native subscripties draagt `endpoint` het device-token (uniek per app+apparaat, zelfde
idempotentie als de Web-Push-endpoint-URL); `p256dh`/`auth` zijn Web-Push-encryptiesleutels
(RFC 8291) en bestaan native niet → nullable, met een check die de combinatie afdwingt
(webpush mét sleutels, native zónder — geen halve rijen). De apparaat-binding en daarmee de
kill-switch-semantiek (migratie 0050) zijn identiek voor alle soorten.

Revision ID: 0055
Revises: 0054
Create Date: 2026-08-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "push_subscriptie",
        sa.Column("soort", sa.Text(), nullable=False, server_default="webpush"),
        schema="platform",
    )
    op.alter_column("push_subscriptie", "p256dh", nullable=True, schema="platform")
    op.alter_column("push_subscriptie", "auth", nullable=True, schema="platform")
    op.create_check_constraint(
        "ck_push_subscriptie_soort",
        "push_subscriptie",
        "soort IN ('webpush', 'apns', 'fcm')",
        schema="platform",
    )
    op.create_check_constraint(
        "ck_push_subscriptie_sleutels_bij_soort",
        "push_subscriptie",
        "(soort = 'webpush' AND p256dh IS NOT NULL AND auth IS NOT NULL) "
        "OR (soort IN ('apns', 'fcm') AND p256dh IS NULL AND auth IS NULL)",
        schema="platform",
    )


def downgrade() -> None:
    op.drop_constraint("ck_push_subscriptie_sleutels_bij_soort", "push_subscriptie", schema="platform")
    op.drop_constraint("ck_push_subscriptie_soort", "push_subscriptie", schema="platform")
    op.execute("DELETE FROM platform.push_subscriptie WHERE soort <> 'webpush'")
    op.alter_column("push_subscriptie", "auth", nullable=False, schema="platform")
    op.alter_column("push_subscriptie", "p256dh", nullable=False, schema="platform")
    op.drop_column("push_subscriptie", "soort", schema="platform")
