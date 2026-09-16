"""Store → administratie, PLATFORMBREED (Peter 16-09 avond; migratie 0151).

Aanleiding: Sunshine Island is een eigen BV en dus een ándere administratie dan Elderveld. De per-administratie-lijst
`bron_instellingen.stores` (15-09) kon een dagstaat nooit naar een ándere administratie sturen dan de administratie
waarin hij was ingesteld — en kende geen uniciteit over administraties heen. Nu: één tabel `omzet_store_routering`
(genormaliseerde storenaam → administratie, actief, wie/wanneer), unieke index op de storenaam, audit oud→nieuw.

Regels (KP7 "minimale mens"): de dagstaat noemt de store zélf ("Store Used: X"), dus bij dit brontype is de store
LEIDEND boven de tenaamstelling/afzender van de mail (die blijven hint). Onbekende store → verzamelbak mét reden
`omzetbron_store_onbekend: X` + link naar het Stores-blok (lege stand = actie). Nooit raden, nooit een tweede bron:
de per-administratie-lijst is sinds 0151 een AFGELEIDE weergave ("stores die hier landen")."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.omzet.models import OmzetInstelling, OmzetStoreRoutering

logger = logging.getLogger(__name__)

MODULE = "boekhouding"
TABEL = "omzet_store_routering"
BRON_MENS = "mens"
BRON_MIGRATIE = "migratie"
#: Verzamelbak-reden (prefix) voor een herkende dagstaat waarvan de store niet gekoppeld is; `redenen.py` maakt er
#: het leesbare label mét de link naar het Stores-blok van; de frontend toont "Stores koppelen →".
REDEN_STORE_ONBEKEND = "omzetbron_store_onbekend"
REDEN_STORE_ONTBREEKT = "omzetbron_store_ontbreekt"
#: Deeplink naar het Beheerder-blok (Instellingen › Boeken platformbreed › Stores).
DOEL_PAD_STORES = "/instellingen/boeken#stores"

_WIT = re.compile(r"\s+")


class StoreFout(Exception):
    """Ongeldige invoer (lege naam, onbekende administratie) → 422 in de router."""


class StoreOnbekend(StoreFout):
    """Rij bestaat niet → 404."""


def normaliseer_store(store: str | None) -> str | None:
    """Sleutel voor de unieke index: casefold, leestekens/whitespace ingeklapt tot één spatie. "Sunshine  Island" ≡
    "sunshine island" ≡ "Sunshine-Island"; leeg/None → None (nooit routeren op niets)."""
    if store is None:
        return None
    kaal = _WIT.sub(" ", re.sub(r"[^\w\s]", " ", str(store)).casefold()).strip()
    return kaal or None


@dataclass(frozen=True)
class StoreInfo:
    id: uuid.UUID
    store_naam: str
    store_norm: str
    administratie_id: uuid.UUID
    administratie_naam: str
    actief: bool
    bron: str
    gewijzigd_op: datetime | None


def _info(rij: OmzetStoreRoutering, namen: dict[uuid.UUID, str]) -> StoreInfo:
    return StoreInfo(
        id=rij.id,
        store_naam=rij.store_naam,
        store_norm=rij.store_norm,
        administratie_id=rij.administratie_id,
        administratie_naam=namen.get(rij.administratie_id, "?"),
        actief=bool(rij.actief),
        bron=rij.bron,
        gewijzigd_op=rij.gewijzigd_op,
    )


def _namen(session: Session) -> dict[uuid.UUID, str]:
    return {a.id: a.naam for a in session.scalars(select(Administratie))}


def lijst(*, actor_id: uuid.UUID | None = None) -> list[StoreInfo]:
    """Alle routeringen (actief én ontkoppeld), alfabetisch op storenaam — het Stores-blok."""
    # Scope-loze sessie zónder actor: zo leest ook `actieve_administraties_per_backend` de administratietabel; de
    # routering zelf is een referentietabel (RLS: iedereen in de app-rol leest).
    with scoped_session(None) as session:
        namen = _namen(session)
        rijen = session.scalars(select(OmzetStoreRoutering).order_by(OmzetStoreRoutering.store_norm)).all()
        return [_info(r, namen) for r in rijen]


def stores_voor_administratie(session: Session, administratie_id: uuid.UUID) -> list[str]:
    """Afgeleide weergave voor het per-administratie-blok: de actieve stores die in déze administratie landen."""
    rijen = session.scalars(
        select(OmzetStoreRoutering)
        .where(OmzetStoreRoutering.administratie_id == administratie_id, OmzetStoreRoutering.actief.is_(True))
        .order_by(OmzetStoreRoutering.store_norm)
    ).all()
    return [r.store_naam for r in rijen]


def administratie_voor_store(store: str | None) -> uuid.UUID | None:
    """ "Store Used" uit de dagstaat → de administratie van de ACTIEVE routering; None = niet gekoppeld (verzamelbak,
    nooit raden). De unieke index garandeert hooguit één rij per store."""
    norm = normaliseer_store(store)
    if norm is None:
        return None
    with scoped_session(None) as session:
        rij = session.scalar(
            select(OmzetStoreRoutering).where(
                OmzetStoreRoutering.store_norm == norm, OmzetStoreRoutering.actief.is_(True)
            )
        )
        return rij.administratie_id if rij is not None else None


def koppel(
    *, store: str, administratie_id: uuid.UUID, actor_id: uuid.UUID, bron: str = BRON_MENS, actief: bool = True
) -> StoreInfo:
    """Upsert op de genormaliseerde storenaam: nieuw → rij; bestaand → administratie/actief/naam bijgewerkt (één rij per
    store, dus 'verhuizen' naar een andere administratie = dezelfde rij wijzigen). Audit oud→nieuw, mét
    administratie."""
    norm = normaliseer_store(store)
    if norm is None:
        raise StoreFout("Storenaam is verplicht (zoals hij in de dagstaat staat, bv. 'Sunshine Island').")
    naam = _WIT.sub(" ", str(store)).strip()
    # Bestaan + namen in de scope-loze sessie zonder actor (zoals `actieve_administraties_per_backend`).
    with scoped_session(None) as session:
        namen = _namen(session)
    if administratie_id not in namen:
        raise StoreFout(f"Onbekende administratie {administratie_id}")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.scalar(select(OmzetStoreRoutering).where(OmzetStoreRoutering.store_norm == norm))
        if rij is None:
            rij = OmzetStoreRoutering(
                id=uuid.uuid4(),
                store_norm=norm,
                store_naam=naam,
                administratie_id=administratie_id,
                actief=actief,
                bron=bron,
                gewijzigd_door=actor_id,
            )
            session.add(rij)
            oud: dict | None = None
            actie = "omzet_store_gekoppeld"
        else:
            oud = _als_dict(rij)
            if (rij.administratie_id, bool(rij.actief)) == (administratie_id, actief):
                session.flush()
                return _info(rij, namen)
            # De weergavenaam blijft de eerste spelling (zoals de dagstaat 'm print); de sleutel is de normvorm.
            rij.administratie_id = administratie_id
            rij.actief = actief
            rij.bron = bron
            rij.gewijzigd_door = actor_id
            actie = "omzet_store_gewijzigd"
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel=TABEL,
            record_id=rij.id,
            actie=actie,
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde=_als_dict(rij),
            administratie_id=administratie_id,
        )
        session.flush()
        return _info(rij, namen)


def zet_actief(*, routering_id: uuid.UUID, actief: bool, actor_id: uuid.UUID) -> StoreInfo:
    """Ontkoppelen (actief=False) of opnieuw activeren — de rij blijft (nooit verwijderen)."""
    with scoped_session(None) as session:
        rij = session.get(OmzetStoreRoutering, routering_id)
        if rij is None:
            raise StoreOnbekend(f"Onbekende store-routering {routering_id}")
        aid = rij.administratie_id
        namen = _namen(session)
    with scoped_session(aid, actor_id=actor_id) as session:
        rij = session.get(OmzetStoreRoutering, routering_id)
        assert rij is not None
        if bool(rij.actief) == actief:
            return _info(rij, namen)
        oud = _als_dict(rij)
        rij.actief = actief
        rij.gewijzigd_door = actor_id
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel=TABEL,
            record_id=rij.id,
            actie="omzet_store_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde=_als_dict(rij),
            administratie_id=aid,
        )
        session.flush()
        return _info(rij, namen)


def _als_dict(rij: OmzetStoreRoutering) -> dict:
    return {
        "store_naam": rij.store_naam,
        "store_norm": rij.store_norm,
        "administratie_id": str(rij.administratie_id),
        "actief": bool(rij.actief),
        "bron": rij.bron,
    }


@dataclass(frozen=True)
class MigratieRegel:
    administratie_id: uuid.UUID
    administratie_naam: str
    store: str
    uitkomst: str  # 'aangemaakt' | 'bestaat_al' | 'conflict' | 'dry_run'
    detail: str | None = None


def migreer_uit_bron_instellingen(
    *, schrijf: bool = False, actor_id: uuid.UUID = SYSTEEM_ACTOR_ID
) -> list[MigratieRegel]:
    """Data-stap 0151 (éénmalig, idempotent): élke `stores`-naam in `omzet_instelling.bron_instellingen` (0146, per
    administratie) wordt een rij in de routeringstabel voor díe administratie. Bestaat de store al (zelfde
    administratie) → 'bestaat_al'; bestaat hij voor een ÁNDERE administratie → 'conflict' (nooit overschrijven — de
    Beheerder beslist in het Stores-blok). Default dry-run: alleen de lijst; `schrijf=True` maakt de rijen aan (bron
    'migratie'). De JSON-lijst blijft staan als historisch spoor; hij wordt sinds 0151 niet meer gelezen."""
    uit: list[MigratieRegel] = []
    with scoped_session(None) as session:
        namen = _namen(session)
        bestaande = {r.store_norm: r for r in session.scalars(select(OmzetStoreRoutering))}
    rijen: list[tuple[uuid.UUID, list]] = []
    for aid in namen:
        # omzet_instelling is administratie-gescoopt (RLS): per administratie lezen.
        with scoped_session(aid, actor_id=actor_id) as session:
            rij = session.get(OmzetInstelling, aid)
            if rij is not None and (rij.bron_instellingen or {}).get("stores"):
                rijen.append((aid, list(rij.bron_instellingen["stores"])))
    for aid, stores in sorted(rijen, key=lambda x: namen.get(x[0], "")):
        for store in stores:
            norm = normaliseer_store(store)
            if norm is None:
                continue
            bestaand = bestaande.get(norm)
            if bestaand is not None:
                if bestaand.administratie_id == aid:
                    uit.append(MigratieRegel(aid, namen.get(aid, "?"), str(store), "bestaat_al"))
                else:
                    uit.append(
                        MigratieRegel(
                            aid,
                            namen.get(aid, "?"),
                            str(store),
                            "conflict",
                            f"al gekoppeld aan {namen.get(bestaand.administratie_id, bestaand.administratie_id)}",
                        )
                    )
                continue
            if not schrijf:
                uit.append(MigratieRegel(aid, namen.get(aid, "?"), str(store), "dry_run"))
                continue
            info = koppel(store=str(store), administratie_id=aid, actor_id=actor_id, bron=BRON_MIGRATIE)
            bestaande[norm] = OmzetStoreRoutering(
                id=info.id,
                store_norm=norm,
                store_naam=info.store_naam,
                administratie_id=aid,
                actief=True,
                bron=BRON_MIGRATIE,
            )
            uit.append(MigratieRegel(aid, namen.get(aid, "?"), str(store), "aangemaakt"))
    return uit


def print_migratie(regels: list[MigratieRegel], *, schrijf: bool) -> None:
    print(
        "Store-routering migreren uit bron_instellingen.stores — "
        f"{'GESCHREVEN' if schrijf else 'DRY-RUN (niets geschreven)'}: "
        f"{len(regels)} store(s)"
    )
    for r in regels:
        print(
            f"  {r.uitkomst:<11} {r.store!r:<28} → {r.administratie_naam} ({r.administratie_id})"
            + (f"  — {r.detail}" if r.detail else "")
        )
    if not regels:
        print("  (geen stores in bron_instellingen gevonden)")
