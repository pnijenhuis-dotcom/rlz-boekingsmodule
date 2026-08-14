"""E-mail-normalisatie (bugfix 2026-08-14): lowercase afgedwongen op platform.gebruiker.e_mail.

Live door Peter gevonden op de cloud: login deed een case-gevoelige e-mailmatch, dus
"Peter@ak-nijenhuis.nl" werkte maar hetzelfde adres in kleine letters niet. De structurele fix
normaliseert op élke ingang in de app (app/auth/normalisatie.py); deze migratie brengt de
bestaande rijen naar de genormaliseerde vorm en zet er een CHECK op zodat een toekomstig
schrijfpad zonder normalisatie hard faalt. De bestaande unique-index op e_mail is daarmee de
unieke index op de genormaliseerde vorm.

NB bewuste, expliciet opgedragen afwijking van de schema-only-regel: de UPDATE naar lowercase
zit ín deze migratie ("bestaande rijen meenemen — alleen migratie-technisch, geen dubbele
accounts"), omdat de CHECK anders op bestaande rijen faalt. Failsafe: bestaan er adressen die
alleen in casing verschillen (zouden ná lower() botsen op de unique-index), dan stopt de
migratie hard met de botsende adressen in de melding — een mens kiest dan welk account blijft
(nooit stil samenvoegen of verwijderen). Dev-database gecontroleerd 2026-08-14: geen botsingen.

Revision ID: 0049
Revises: 0048
Create Date: 2026-08-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    botsingen = conn.execute(
        sa.text(
            "SELECT lower(btrim(e_mail)) AS genormaliseerd, array_agg(e_mail) AS varianten "
            "FROM platform.gebruiker GROUP BY 1 HAVING count(*) > 1"
        )
    ).fetchall()
    if botsingen:
        detail = "; ".join(f"{rij.genormaliseerd}: {rij.varianten}" for rij in botsingen)
        raise RuntimeError(
            "Migratie 0049 gestopt: e-mailadressen die alleen in casing/spaties verschillen — "
            f"een mens moet eerst kiezen welk account blijft. Botsingen: {detail}"
        )

    op.execute("UPDATE platform.gebruiker SET e_mail = lower(btrim(e_mail)) WHERE e_mail <> lower(btrim(e_mail))")
    op.create_check_constraint(
        "ck_gebruiker_e_mail_lowercase", "gebruiker", "e_mail = lower(e_mail)", schema="platform"
    )


def downgrade() -> None:
    # De lowercase-UPDATE is bewust niet omkeerbaar (de oorspronkelijke casing is geen
    # informatie die iets mag betekenen); alleen de CHECK gaat weg.
    op.drop_constraint("ck_gebruiker_e_mail_lowercase", "gebruiker", schema="platform", type_="check")
