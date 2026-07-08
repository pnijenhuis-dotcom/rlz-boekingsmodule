"""Frontend-fundament: een gebruiker moet zijn EIGEN gebruiker_administratie-rijen kunnen lezen
(voor "welke administraties mag ik zien" bij het inloggen), ongeacht welke administratie de
sessie op dat moment gescoped heeft. De bestaande RLS-policy (migratie 0002) laat alleen rijen
zien voor de huidige `current_administratie_id()` of een Beheerder — een gewone gebruiker met
scope op meerdere administraties zag daarmee via één gescopede sessie nooit zijn volledige lijst.

Uitbreiding UITSLUITEND in de USING-clause (leesrichting): `gebruiker_id = current_actor_id()`
is een zelf-referentie, geen cross-tenant-lek. Bewust NIET toegevoegd aan WITH CHECK (schrijf-
richting) — dat zou een gebruiker zichzelf scope laten toekennen/verwijderen, een privilege-
escalatie. Scope-mutaties blijven zoals altijd Beheerder-only (app/auth/service.py).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS gebruiker_administratie_scope ON platform.gebruiker_administratie")
    op.execute(
        """
        CREATE POLICY gebruiker_administratie_scope ON platform.gebruiker_administratie
        USING (
            administratie_id = platform.current_administratie_id()
            OR platform.current_actor_is_beheerder()
            OR gebruiker_id = platform.current_actor_id()
        )
        WITH CHECK (
            administratie_id = platform.current_administratie_id()
            OR platform.current_actor_is_beheerder()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS gebruiker_administratie_scope ON platform.gebruiker_administratie")
    op.execute(
        """
        CREATE POLICY gebruiker_administratie_scope ON platform.gebruiker_administratie
        USING (administratie_id = platform.current_administratie_id() OR platform.current_actor_is_beheerder())
        WITH CHECK (administratie_id = platform.current_administratie_id() OR platform.current_actor_is_beheerder())
        """
    )
