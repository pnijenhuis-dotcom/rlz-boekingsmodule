"""E-mail-normalisatie (bugfix 2026-08-14, live door Peter gevonden op de cloud-omgeving):
de login deed een case-gevoelige e-mailmatch — "Peter@ak-nijenhuis.nl" werkte, hetzelfde adres
in kleine letters gaf "Ongeldige inloggegevens". Structurele regel: e-mailadressen worden op
ÉLKE ingang (aanmaak, uitnodiging, login, accordeur-login) door deze ene functie genormaliseerd
en de database dwingt de genormaliseerde vorm af met een CHECK (migratie 0049) — een pad dat
deze functie vergeet, faalt dan hard bij het schrijven i.p.v. stil een onbereikbaar account te
maken. De bestaande unique-index op e_mail is daarmee automatisch de index op de
genormaliseerde vorm."""

from __future__ import annotations


def normaliseer_e_mail(e_mail: str) -> str:
    """Lowercase + trim. RFC 5321 staat een case-gevoelige local-part formeel toe, maar geen
    enkele reële mailprovider onderscheidt daarop; verwisselbare casing als twee accounts is
    hier alleen maar een bron van lockouts en duplicaten."""
    return e_mail.strip().lower()
