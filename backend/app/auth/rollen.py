"""Rol-indeling kantoor vs externe app-rollen — één plek (migratie 0056, uren & meerwerk).

Vóór de veldrollen was "kantoor" overal gedefinieerd als "alles behalve klant_accordeur";
met drie nieuwe externe rollen (ZZP'er / uitvoerder / detacheerder, BOUW GO 2026-08-21) zou
elke zo geschreven gate ze stil als kantoor behandelen. Daarom staat de indeling hier
éénmalig, en toetsen alle gates tegen deze sets:

- EXTERNE_APP_ROLLEN: rollen die de mobiele app gebruiken en de accordeur-authcadans volgen
  (0040-lijn: wachtwoord → passkey-activatie, 7-dagen sliding refresh-TTL, ontgrendel-assertie
  per app-opening, apparaat-kill-switch). Zij mogen nooit de éénstaps-kantoor-passkey-login of
  kantoor-endpoints (intake, accordering-kantooracties, beheer) gebruiken.
- VELD_ROLLEN: de uren-&-meerwerk-deelverzameling (geen accordeur) — de doelgroep van
  app/uren/router-endpoints.
"""

from __future__ import annotations

from app.db.models import GebruikerRol

VELD_ROLLEN: frozenset[GebruikerRol] = frozenset(
    {GebruikerRol.ZZPER, GebruikerRol.UITVOERDER, GebruikerRol.DETACHEERDER}
)

EXTERNE_APP_ROLLEN: frozenset[GebruikerRol] = VELD_ROLLEN | {GebruikerRol.KLANT_ACCORDEUR}


def is_externe_app_rol(rol: GebruikerRol) -> bool:
    return rol in EXTERNE_APP_ROLLEN


def is_kantoorrol(rol: GebruikerRol) -> bool:
    """Kantoor = elke rol die géén externe app-rol is (beheerder / boekhouding_projecten /
    boekhouding). Bewust als complement gedefinieerd: een nieuwe externe rol hoeft dan alleen
    aan EXTERNE_APP_ROLLEN toegevoegd te worden en valt nooit stil in de kantoor-groep."""
    return rol not in EXTERNE_APP_ROLLEN


def is_veldrol(rol: GebruikerRol) -> bool:
    return rol in VELD_ROLLEN
