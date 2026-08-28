"""Voorwaarden + privacyverklaring-akkoord in de accordeur-activeringsflow (migratie 0040).

Tekst = docs/avg/05-activatie-checklist.md bijlage A (concept, wacht op juridische toetsing
Peter — de versie-string hieronder markeert dat expliciet). Informatielaag bóvenop het
AVG-pakket, géén vervanging (zie de bijlage-A-preambule). Het akkoord (wie/wanneer/
tekstversie) landt in platform.accordeur_akkoord én het append-only audit_event; zonder
akkoord op de ACTUELE tekstversie geen toegang tot de accordeer-wachtrij (server-side
afgedwongen in app/accordering/router.py — een nieuwe tekstversie vraagt dus vanzelf een
nieuw akkoord)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import AccordeurAkkoord
from app.db.session import scoped_session

# Bij elke inhoudelijke tekstwijziging ophogen — bestaande accordeurs krijgen dan opnieuw het
# akkoord-scherm (fail-closed op de actuele versie).
AKKOORD_TEKST_VERSIE = "2026-08-28-v2"

# Placeholders [klantnaam]/[administratie] vult de PWA met de administratienamen uit de scope
# van de accordeur; [link] verwijst naar de privacyverklaring (concept — jurist-toets open).
AKKOORD_TEKST = """\
Welkom bij de goedkeuringsapp van Administratiekantoor Nijenhuis. Je bent door [klantnaam] \
aangewezen om inkoopfacturen van [administratie] goed te keuren. Lees dit even door voordat \
je begint.

1. Gebruiksvoorwaarden. Je gebruikt deze app uitsluitend om facturen van [klantnaam] te \
beoordelen: goedkeuren, of afwijzen met een verplichte reden. Je account is persoonlijk — \
deel je inloggegevens of apparaat-toegang niet met anderen. [Klantnaam] en het kantoor \
kunnen je toegang op elk moment intrekken.

2. Jouw gegevens. Voor je account verwerken wij: je naam, e-mailadres, inloggegevens \
(wachtwoord versleuteld, eventuele passkey), apparaat- en sessiegegevens en een logboek van \
je handelingen (welke factuur, akkoord of afwijzing met reden, datum en tijd). Doel: veilige \
toegang en een controleerbaar goedkeuringsspoor bij de administratie. Het logboek bewaren \
wij 7 jaar (wettelijke administratieplicht). Administratiekantoor Nijenhuis is voor deze \
accountgegevens de verwerkingsverantwoordelijke; in de privacyverklaring lees je hoe wij met \
je gegevens omgaan en welke rechten je hebt (inzage, correctie, bezwaar).

3. Staande goedkeuringen. Stel je een staande goedkeuring in ("akkoord voor deze en alle \
volgende facturen van deze leverancier met exact dit bedrag"), dan wordt zo'n volgende \
factuur automatisch namens jou goedgekeurd. Elke automatische toepassing is zichtbaar in het \
logboek en je kunt de regel in de app altijd intrekken.

4. Werkstempels (alleen veldwerkers: ZZP'ers en uitvoerders). Werk je op projectlocaties, dan \
kan de app op je telefoon je aankomst en vertrek op die locaties stempelen: uitsluitend het \
tijdstip en het project, alleen bij het binnenkomen en verlaten van de projectzone die het \
kantoor voor dat project heeft ingesteld — buiten die zones ontvangt de app niets en er wordt \
niets gevolgd. De stempels zijn een hulpmiddel bij de controle van je weekstaat (het kantoor \
ziet ze naast je opgegeven uren; een verschil is een gespreksonderwerp, nooit een automatische \
korting) en zijn zichtbaar voor jou en voor de keurder van het kantoor — verder voor niemand. \
Ze worden even lang bewaard als je weekstaten. Uitzetten kan altijd via de locatie-instelling \
van je telefoon; de controle zwijgt dan."""


def heeft_akkoord(*, gebruiker_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        rij = session.scalars(
            select(AccordeurAkkoord.id).where(
                AccordeurAkkoord.gebruiker_id == gebruiker_id,
                AccordeurAkkoord.tekst_versie == AKKOORD_TEKST_VERSIE,
            )
        ).first()
        return rij is not None


def leg_akkoord_vast(*, gebruiker_id: uuid.UUID) -> None:
    """Idempotent (uniek op gebruiker+versie): een dubbele POST is geen fout. Vastlegging in
    het append-only audit_event conform de activatie-checklist (wie/wanneer/tekstversie)."""
    if heeft_akkoord(gebruiker_id=gebruiker_id):
        return
    with scoped_session(None, actor_id=gebruiker_id) as session:
        rij = AccordeurAkkoord(id=uuid.uuid4(), gebruiker_id=gebruiker_id, tekst_versie=AKKOORD_TEKST_VERSIE)
        session.add(rij)
        record_audit_event(
            session,
            actor_id=gebruiker_id,
            module="platform",
            tabel="accordeur_akkoord",
            record_id=rij.id,
            actie="accordeur_voorwaarden_akkoord",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"tekst_versie": AKKOORD_TEKST_VERSIE},
        )
