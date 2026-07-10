"""Async extractie (2026-07-10): wachtrij-status + systeem-actor.

Aanleiding: de synchrone chunked extractie van een uitzonderlijk grote factuur hield de
upload-request (en daarmee het scherm) ruim 90 seconden vast. Grote documenten gaan voortaan
direct een achtergrondwachtrij in (status `extractie_wachtrij`); een worker verwerkt ze los van
de request. Kleine documenten houden de bestaande snelle synchrone route.

Twee onderdelen:

1. Nieuwe documentstatus `extractie_wachtrij` (ná `ontvangen` in de enum-volgorde). ALTER TYPE
   ... ADD VALUE mag sinds PG12 binnen een transactie zolang de nieuwe waarde niet in dezelfde
   transactie gebruikt wordt — de INSERT hieronder raakt een ander enum-type, dus dat is veilig.

2. Systeem-actor: één vaste, herkenbare platform-gebruiker (UUID ...0001) voor élke
   statusovergang/audit_event door achtergrondverwerking (patroon geldt straks ook voor
   sync-jobs, webhook-aflevering, e-mail-intake). Bewust een échte `platform.gebruiker`-rij:
   de FK's op `document_gebeurtenis.actor_id` en `audit_event.actor_id` blijven dan gewoon
   gelden — geen NULL-actor, geen sentinel buiten de tabel. Kan nooit inloggen: status
   `geblokkeerd` + geen wachtwoord-hash + geen uitnodiging. Rol is de bestaande waarde
   `boekhouding` (geen eigen enum-waarde: rollen sturen autorisatie van ménsen; herkenbaarheid
   komt van de vaste UUID + naam, niet van een rol). Seed in de migratie is hier wél passend
   (vgl. de boeken_instelling-singleton in 0008): omgevingsonafhankelijk en deterministisch —
   anders dan de bootstrap-Beheerder, die een echte naam/e-mail als invoer heeft en daarom
   CLI-only is.

Downgrade is een bewuste no-op: enum-waarden verwijderen kan PostgreSQL niet, en de
systeem-gebruiker kan al gerefereerd zijn vanuit tijdlijn/audit (append-only) — de rij laten
staan is onschadelijk voor oudere code (status geblokkeerd, nooit gezet als actor door oude
code). Een volledige downgrade naar base ruimt hem via de tabel-drop in 0002 alsnog op.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

SYSTEEM_ACTOR_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.execute(
        "ALTER TYPE boekhouding.document_status ADD VALUE IF NOT EXISTS 'extractie_wachtrij' AFTER 'ontvangen'"
    )
    op.execute(
        f"""
        INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status)
        VALUES ('{SYSTEEM_ACTOR_ID}', 'Systeem (achtergrondverwerking)', 'systeem@platform.intern',
                'boekhouding', 'geblokkeerd')
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    # Bewuste no-op — zie de module-docstring.
    pass
