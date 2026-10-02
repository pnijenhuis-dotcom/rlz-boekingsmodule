"""Entiteit → administratie voor Vastly-verkoopfacturen — uitsluitend via de UBL en het entiteitenregister (Peter 28-09:
"nooit op tenaamstelling"; Peter 01-10: "vastly facturen 100% auto zonder menselijke tussenstap … hou het simpel";
migraties 0172 + 0173).

De verhuurder staat in de UBL als `AccountingSupplierParty` (KvK uit PartyLegalEntity/CompanyID schemeID 0106 —
`UblVoorstel.kvk_nummer` — en naam) en sinds 01-10 (koppelcontract §2d-notitie 01-10 avond) draagt élke Vastly-UBL
daarnaast een tweede `cac:AdditionalDocumentReference` `RLZ-ADMINISTRATIE:<platform administratie-uuid>`. De resolutie
is
deterministisch en kent precies deze bronnen, in deze volgorde:

1. het administratie-id uit de UBL (`documenten/ubl.administratie_verwijzing`): bestaat de administratie, is ze actief
   en niet gearchiveerd → klaar (bron 'ubl'); de koppelingsrij op de primaire sleutel (KvK, anders naam) wordt mét bron
   'ubl'
   vastgelegd als die er nog niet is. Draagt de UBL een id dat de module NIET kent (onbekend, inactief, gearchiveerd,
   ongeldig of meerdere) dan is dat een zichtbare weigering — nooit stil terugvallen op een ándere administratie
   (koppelcontract §2d-notitie 01-10 punt 3);
2. ontbreekt het element: een bestaande koppelingsrij op de KvK-sleutel (`vastly_entiteit_koppeling`);
3. `administratie_identiteit.kvk` (de identiteit die de sync uit RLZ `AdministrationSettings`/Odoo `res.company`
   leest) —
   precies ÉÉN actieve, niet-gearchiveerde administratie → koppeling vastgelegd met bron 'identiteit';
4. een BESTAANDE koppelingsrij op de genormaliseerde naam (`intercompany.identiteit.naam_norm`) — alleen lezen: de
   mens-koppeling via de bevinding is per 01-10 vervallen, er komen geen nieuwe naam-koppelingen bij.

Niets anders: geen fuzzy match, geen afzender-hint, geen toewijzings-geheugen van de verzamelbak, geen mens-knop.
Onbekend
= `EntiteitBesluit.administratie_id is None` mét de sleutels + de weigerreden voor de bevinding ("melden bij Vastly").
Geen AI."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Administratie
from app.documenten.ubl import UblVeldvoorstel, administratie_verwijzing
from app.extractie.btw_nummer import normaliseer_kvk_nummer
from app.intercompany.identiteit import naam_norm
from app.intercompany.models import AdministratieIdentiteit
from app.verkoop.models import VastlyEntiteitKoppeling

SLEUTEL_KVK = "kvk"
SLEUTEL_NAAM = "naam"
BRON_IDENTITEIT = "identiteit"
#: Historische mens-koppelingen (bevinding "Koppel aan administratie…", 29-09 → vervallen 01-10) worden nog gelezen.
BRON_MENS = "mens"
BRON_UBL = "ubl"
#: Prefix van de intake-reden op een niet-gekoppeld Vastly-verkoopdocument (tijdlijn + intake-bericht); de rest van
#: de reden is `kvk=<kvk>|naam=<naam_norm>|weergave=<naam>|administratie_id=<ruwe UBL-waarde>`.
REDEN_NIET_GEKOPPELD = "vastly_entiteit_niet_gekoppeld"
#: De oude verzamelbak-reden van vóór 29-09 — dezelfde documenten, dezelfde behandeling (heraanbieding + bevinding).
REDEN_OUD = "vastly_verkoop_zonder_eenduidige_entiteit"
VASTLY_REDENEN = (REDEN_NIET_GEKOPPELD, REDEN_OUD)
#: Weigerredenen (bevindingstekst "melden bij Vastly").
WEIGERING_ID_ONBEKEND = "administratie_id_onbekend"
WEIGERING_GEEN_ID_GEEN_KVK = "geen_administratie_id_geen_bekende_kvk"


class EntiteitFout(Exception):
    """Domeinfout in het entiteitenregister (onbekende/inactieve administratie, ongeldige sleutel)."""


@dataclass(frozen=True)
class EntiteitSleutels:
    """De sleutels die een UBL voor de verhuurder kan dragen (genormaliseerd) + de weergavenaam + het administratie-id
    uit de UBL (`administratie_id_ruw` = de letterlijke waarde ná het prefix, ook als die geen geldige UUID is)."""

    kvk: str | None
    naam_norm: str | None
    weergave: str | None
    administratie_id: uuid.UUID | None = None
    administratie_id_ruw: str | None = None

    @property
    def heeft_administratie_id(self) -> bool:
        """Het `RLZ-ADMINISTRATIE:`-element staat in de UBL (geldig of niet)."""
        return self.administratie_id_ruw is not None

    @property
    def primair(self) -> tuple[str, str] | None:
        """(sleutel_soort, sleutel) waarop een koppelingsrij geschreven wordt: KvK als die er is, anders naam."""
        if self.kvk:
            return SLEUTEL_KVK, self.kvk
        if self.naam_norm:
            return SLEUTEL_NAAM, self.naam_norm
        return None

    def als_reden(self) -> str:
        delen = [REDEN_NIET_GEKOPPELD]
        if self.kvk:
            delen.append(f"kvk={self.kvk}")
        if self.naam_norm:
            delen.append(f"naam={self.naam_norm}")
        if self.weergave:
            delen.append(f"weergave={self.weergave}")
        if self.administratie_id_ruw:
            delen.append(f"administratie_id={self.administratie_id_ruw}")
        return ": ".join([delen[0], "|".join(delen[1:])]) if len(delen) > 1 else delen[0]


@dataclass(frozen=True)
class EntiteitBesluit:
    administratie_id: uuid.UUID | None
    #: 'ubl' | 'koppeling_kvk' | 'identiteit_kvk' | 'koppeling_naam' | None
    bron: str | None
    sleutels: EntiteitSleutels
    #: Bij `administratie_id is None`: WEIGERING_ID_ONBEKEND (de UBL noemt een id dat de module niet kent) of
    #: WEIGERING_GEEN_ID_GEEN_KVK (geen element, geen bekende KvK, geen bestaande naam-koppeling).
    weigering: str | None = None


def sleutels_uit_voorstel(voorstel: UblVeldvoorstel) -> EntiteitSleutels:
    kvk = normaliseer_kvk_nummer(voorstel.kvk_nummer) if voorstel.kvk_nummer else None
    naam = (voorstel.leverancier_naam or "").strip() or None
    verwijzing = administratie_verwijzing(voorstel)
    return EntiteitSleutels(
        kvk=kvk or None,
        naam_norm=naam_norm(naam) or None,
        weergave=naam,
        administratie_id=verwijzing.administratie_id,
        administratie_id_ruw=(verwijzing.ruw or "") if verwijzing.aanwezig else None,
    )


def sleutels_uit_reden(reden: str | None) -> EntiteitSleutels:
    """Omgekeerde van `EntiteitSleutels.als_reden` — voor documenten die al met een reden in de tijdlijn staan.
    De oude reden (`vastly_verkoop_zonder_eenduidige_entiteit`) draagt geen sleutels: dan leest de heraanbieding
    de UBL opnieuw."""
    if not reden or not reden.startswith(REDEN_NIET_GEKOPPELD + ":"):
        return EntiteitSleutels(kvk=None, naam_norm=None, weergave=None)
    velden: dict[str, str] = {}
    for deel in reden.split(":", 1)[1].strip().split("|"):
        if "=" in deel:
            k, v = deel.split("=", 1)
            velden[k.strip()] = v.strip()
    ruw = velden.get("administratie_id") or None
    try:
        administratie_id = uuid.UUID(ruw) if ruw else None
    except ValueError:
        administratie_id = None
    return EntiteitSleutels(
        kvk=velden.get("kvk") or None,
        naam_norm=velden.get("naam") or None,
        weergave=velden.get("weergave") or None,
        administratie_id=administratie_id,
        administratie_id_ruw=ruw,
    )


def _actieve_administratie(session: Session, administratie_id: uuid.UUID) -> Administratie | None:
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.actief or administratie.gearchiveerd_op is not None:
        return None
    return administratie


def _koppeling(session: Session, soort: str, sleutel: str) -> VastlyEntiteitKoppeling | None:
    return session.scalars(
        select(VastlyEntiteitKoppeling).where(
            VastlyEntiteitKoppeling.sleutel_soort == soort, VastlyEntiteitKoppeling.sleutel == sleutel
        )
    ).first()


def _leg_koppeling_vast(
    session: Session, *, sleutels: EntiteitSleutels, administratie_id: uuid.UUID, bron: str
) -> None:
    """Koppelingsrij op de primaire sleutel als die er nog niet is (een bestaande rij wordt nooit stil overschreven —
    de UBL wint voor dít document, de rij blijft zoals een mens of de identiteit 'm zette)."""
    primair = sleutels.primair
    if primair is None:
        return
    soort, sleutel = primair
    if _koppeling(session, soort, sleutel) is None:
        session.add(
            VastlyEntiteitKoppeling(
                sleutel_soort=soort,
                sleutel=sleutel,
                administratie_id=administratie_id,
                bron=bron,
                weergave=sleutels.weergave,
            )
        )


def resolve_administratie(session: Session, sleutels: EntiteitSleutels) -> EntiteitBesluit:
    """Deterministische resolutie (module-doc). Een koppeling naar een intussen gearchiveerde administratie telt
    niet (dan is het een weigering — de bevinding zegt het)."""
    if sleutels.heeft_administratie_id:
        administratie = (
            _actieve_administratie(session, sleutels.administratie_id)
            if sleutels.administratie_id is not None
            else None
        )
        if administratie is None:
            return EntiteitBesluit(administratie_id=None, bron=None, sleutels=sleutels, weigering=WEIGERING_ID_ONBEKEND)
        _leg_koppeling_vast(session, sleutels=sleutels, administratie_id=administratie.id, bron=BRON_UBL)
        return EntiteitBesluit(administratie_id=administratie.id, bron=BRON_UBL, sleutels=sleutels)
    if sleutels.kvk:
        rij = _koppeling(session, SLEUTEL_KVK, sleutels.kvk)
        if rij is not None and _actieve_administratie(session, rij.administratie_id) is not None:
            return EntiteitBesluit(administratie_id=rij.administratie_id, bron="koppeling_kvk", sleutels=sleutels)
        treffers = [
            r
            for r in session.scalars(
                select(AdministratieIdentiteit).where(AdministratieIdentiteit.kvk == sleutels.kvk)
            ).all()
            if _actieve_administratie(session, r.administratie_id) is not None
        ]
        if len(treffers) == 1:
            administratie_id = treffers[0].administratie_id
            if rij is None:
                _leg_koppeling_vast(session, sleutels=sleutels, administratie_id=administratie_id, bron=BRON_IDENTITEIT)
            return EntiteitBesluit(administratie_id=administratie_id, bron="identiteit_kvk", sleutels=sleutels)
    if sleutels.naam_norm:
        rij = _koppeling(session, SLEUTEL_NAAM, sleutels.naam_norm)
        if rij is not None and _actieve_administratie(session, rij.administratie_id) is not None:
            return EntiteitBesluit(administratie_id=rij.administratie_id, bron="koppeling_naam", sleutels=sleutels)
    return EntiteitBesluit(administratie_id=None, bron=None, sleutels=sleutels, weigering=WEIGERING_GEEN_ID_GEEN_KVK)


def weigering_tekst(sleutels: EntiteitSleutels, weigering: str | None) -> str:
    """Leesbare weigerreden voor tijdlijn/bevinding — altijd mét de handeling 'melden bij Vastly' (geen mens-knop)."""
    if weigering == WEIGERING_ID_ONBEKEND:
        return (
            f"UBL draagt administratie-id {sleutels.administratie_id_ruw or '?'} dat de module niet kent (onbekend, "
            "inactief of gearchiveerd) — melden bij Vastly"
        )
    return "UBL draagt geen administratie-id en geen bekende KvK — melden bij Vastly"
