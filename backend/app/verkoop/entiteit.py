"""Entiteit → administratie voor Vastly-verkoopfacturen — uitsluitend via het entiteitenregister (Peter 28-09:
"nooit op tenaamstelling"; opdracht 29-09 punt 1; migratie 0172).

De verhuurder staat in de UBL als `AccountingSupplierParty`: KvK (PartyLegalEntity/CompanyID schemeID 0106 —
`UblVoorstel.kvk_nummer`) en naam. De resolutie is deterministisch en kent precies drie bronnen, in deze volgorde:

1. een bestaande koppelingsrij op de KvK-sleutel (`vastly_entiteit_koppeling`, bron identiteit óf mens);
2. `administratie_identiteit.kvk` (de identiteit die de sync uit RLZ `AdministrationSettings`/Odoo `res.company`
   leest) — precies ÉÉN actieve, niet-gearchiveerde administratie → koppeling wordt vastgelegd met bron 'identiteit'
   zodat de volgende factuur 'm zonder identiteitstabel vindt;
3. een bestaande koppelingsrij op de genormaliseerde NAAM (`intercompany.identiteit.naam_norm`) — die ontstaat
   uitsluitend door een mens-koppeling via de bevinding `vastly_entiteit_niet_gekoppeld`.

Niets anders: geen fuzzy match, geen afzender-hint, geen toewijzings-geheugen van de verzamelbak. Onbekend =
`EntiteitBesluit.administratie_id is None` mét de sleutels die de mens straks in de bevinding koppelt. Geen AI."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.documenten.ubl import UblVeldvoorstel
from app.extractie.btw_nummer import normaliseer_kvk_nummer
from app.intercompany.identiteit import naam_norm
from app.intercompany.models import AdministratieIdentiteit
from app.verkoop.models import VastlyEntiteitKoppeling

SLEUTEL_KVK = "kvk"
SLEUTEL_NAAM = "naam"
BRON_IDENTITEIT = "identiteit"
BRON_MENS = "mens"
#: Prefix van de intake-reden op een niet-gekoppeld Vastly-verkoopdocument (tijdlijn + intake-bericht); de rest van
#: de reden is `kvk=<kvk>|naam=<naam_norm>|weergave=<naam>`.
REDEN_NIET_GEKOPPELD = "vastly_entiteit_niet_gekoppeld"
#: De oude verzamelbak-reden van vóór 29-09 — dezelfde documenten, dezelfde behandeling (heraanbieding + bevinding).
REDEN_OUD = "vastly_verkoop_zonder_eenduidige_entiteit"
VASTLY_REDENEN = (REDEN_NIET_GEKOPPELD, REDEN_OUD)


class EntiteitFout(Exception):
    """Domeinfout in het entiteitenregister (onbekende/inactieve administratie, ongeldige sleutel)."""


@dataclass(frozen=True)
class EntiteitSleutels:
    """De twee sleutels die een UBL voor de verhuurder kan dragen (genormaliseerd) + de weergavenaam."""

    kvk: str | None
    naam_norm: str | None
    weergave: str | None

    @property
    def primair(self) -> tuple[str, str] | None:
        """(sleutel_soort, sleutel) waarop een mens-koppeling geschreven wordt: KvK als die er is, anders naam."""
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
        return ": ".join([delen[0], "|".join(delen[1:])]) if len(delen) > 1 else delen[0]


@dataclass(frozen=True)
class EntiteitBesluit:
    administratie_id: uuid.UUID | None
    #: 'koppeling_kvk' | 'identiteit_kvk' | 'koppeling_naam' | None
    bron: str | None
    sleutels: EntiteitSleutels


def sleutels_uit_voorstel(voorstel: UblVeldvoorstel) -> EntiteitSleutels:
    kvk = normaliseer_kvk_nummer(voorstel.kvk_nummer) if voorstel.kvk_nummer else None
    naam = (voorstel.leverancier_naam or "").strip() or None
    return EntiteitSleutels(kvk=kvk or None, naam_norm=naam_norm(naam) or None, weergave=naam)


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
    return EntiteitSleutels(
        kvk=velden.get("kvk") or None, naam_norm=velden.get("naam") or None, weergave=velden.get("weergave") or None
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


def resolve_administratie(session: Session, sleutels: EntiteitSleutels) -> EntiteitBesluit:
    """Deterministische resolutie (module-doc). Een koppeling naar een intussen gearchiveerde administratie telt
    niet (dan opnieuw koppelen — de bevinding zegt het)."""
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
                session.add(
                    VastlyEntiteitKoppeling(
                        sleutel_soort=SLEUTEL_KVK,
                        sleutel=sleutels.kvk,
                        administratie_id=administratie_id,
                        bron=BRON_IDENTITEIT,
                        weergave=sleutels.weergave,
                    )
                )
            return EntiteitBesluit(administratie_id=administratie_id, bron="identiteit_kvk", sleutels=sleutels)
    if sleutels.naam_norm:
        rij = _koppeling(session, SLEUTEL_NAAM, sleutels.naam_norm)
        if rij is not None and _actieve_administratie(session, rij.administratie_id) is not None:
            return EntiteitBesluit(administratie_id=rij.administratie_id, bron="koppeling_naam", sleutels=sleutels)
    return EntiteitBesluit(administratie_id=None, bron=None, sleutels=sleutels)


def koppel_entiteit(
    session: Session,
    *,
    sleutel_soort: str,
    sleutel: str,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    weergave: str | None = None,
) -> VastlyEntiteitKoppeling:
    """De mens-koppeling uit de bevinding (bron 'mens'): schrijft of overschrijft de rij op (soort, sleutel) mét audit
    oud → nieuw. Vereist een actieve administratie; de sleutel wordt genormaliseerd zoals de UBL-lezing dat doet."""
    if sleutel_soort not in (SLEUTEL_KVK, SLEUTEL_NAAM):
        raise EntiteitFout(f"onbekende sleutelsoort {sleutel_soort!r} (kvk | naam)")
    genormaliseerd = normaliseer_kvk_nummer(sleutel) if sleutel_soort == SLEUTEL_KVK else naam_norm(sleutel)
    if not genormaliseerd:
        raise EntiteitFout("lege of ongeldige sleutel")
    if _actieve_administratie(session, administratie_id) is None:
        raise EntiteitFout(f"administratie {administratie_id} is onbekend, inactief of gearchiveerd")
    rij = _koppeling(session, sleutel_soort, genormaliseerd)
    oud = None
    if rij is None:
        rij = VastlyEntiteitKoppeling(
            sleutel_soort=sleutel_soort,
            sleutel=genormaliseerd,
            administratie_id=administratie_id,
            bron=BRON_MENS,
            weergave=weergave,
            aangemaakt_door=actor_id,
        )
        session.add(rij)
    else:
        oud = {"administratie_id": str(rij.administratie_id), "bron": rij.bron}
        rij.administratie_id = administratie_id
        rij.bron = BRON_MENS
        rij.aangemaakt_door = actor_id
        if weergave:
            rij.weergave = weergave
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="vastly_entiteit_koppeling",
        record_id=rij.id,
        actie="vastly_entiteit_gekoppeld",
        correlatie_id=uuid.uuid4(),
        oude_waarde=oud,
        nieuwe_waarde={
            "sleutel_soort": sleutel_soort,
            "sleutel": genormaliseerd,
            "administratie_id": str(administratie_id),
            "bron": BRON_MENS,
            "weergave": weergave,
        },
    )
    return rij


def koppelingen_voor(session: Session, administratie_id: uuid.UUID) -> list[VastlyEntiteitKoppeling]:
    return list(
        session.scalars(
            select(VastlyEntiteitKoppeling)
            .where(VastlyEntiteitKoppeling.administratie_id == administratie_id)
            .order_by(VastlyEntiteitKoppeling.sleutel_soort, VastlyEntiteitKoppeling.sleutel)
        ).all()
    )
