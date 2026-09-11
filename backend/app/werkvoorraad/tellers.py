"""Tellers van de werkvoorraad-klantenlijst: set-based lezen + cache (blok 6 run 11-09 middag; migratie 0136).

Aanleiding (Cloud Logging 08-09 t/m 11-09, 71 administraties): `GET /werkvoorraad/overzicht` p50 2,8 s / p95 6,1 s. De
route liep per administratie een `scoped_session`-wissel en ±10 queries (status-GROUP BY + zeven signaaltellers, waarvan
voorraad/planning/terugkerend Python-motoren zijn) — lineair in N. Schaalregel 2 → 2000 (kernprincipe 7.4): het aantal
statements per request is CONSTANT, onafhankelijk van het aantal administraties (meetlat in
tests/werkvoorraad/test_tellers_querytelling.py).

Drie lagen, één definitie:
- `tel_direct(session, administratie_id)` — de TELLING over de brontabellen, de enige definitie van élke teller (de
  oude per-administratie-logica van `documenten/service.py::werkvoorraad_overzicht`, ongewijzigd in betekenis);
- de CACHE `werkvoorraad_teller_cache` (één rij per administratie × teller), bijgewerkt
  (a) INCREMENTEEL bij élke statusovergang van een document — `verwerk_statusovergang` vanuit de statusmachine-
      schrijver (`documenten/service.py::_schrijf_overgang`) en `verwerk_nieuw_document` bij aanmaak; de status-tellers
      verschuiven als delta (oude bucket −1, nieuwe bucket +1), de documentafhankelijke signaaltellers worden bij een
      wissel van/naar
      een terminale status herteld (goedkope COUNT's); vragen en spiegel-taken via `ververs_signalen` op hun eigen
      mutatiepunten;
  (b) NACHTELIJK volledig herrekend in `sync-alles` (`herreken_alle`, CLI `werkvoorraad-tellers-herrekenen`, óók los);
      `--dry-run` rapporteert alleen afwijkingen cache ↔ telling (lees-only, nameting-allowlist) — dezelfde vergelijking
      voedt de reconciliatie-LET-OP `werkvoorraad_tellers`;
  (c) FAIL-SAFE bij het lezen: ontbreekt (een deel van) de cache van een administratie, dan wordt direct geteld en de
      rij aangemaakt — er wordt nooit een lege teller getoond.
- `lees_voor_scope(actor_id, …)` — de leesroute: ÉÉN statement over alle administraties in de scope van de actor in
  `scoped_session(None, actor_id=…)`. RLS blijft de waarheid: de policy op de cache (0136) laat een niet-Beheerder
  uitsluitend rijen zien van administraties waarop hij een `gebruiker_administratie`-rij heeft (zelf-leesbaar sinds
  0007);
  een Beheerder ziet alles. Geen lus met scope-wissel per administratie meer.

Bekende versheid (bewust, gedocumenteerd): signalen die door hun eigen motor worden geschreven (terugkerend, voorraad,
planning, duplicaat-/match-/offertesignaal buiten een statusovergang) zijn in de klantenlijst hooguit één nacht oud —
hun motoren draaien in dezelfde `sync-alles` vóór de herberekening; de kantoorbrede lijsten achter de tellers tellen
live.
Geen AI, geen RLZ-/Odoo-calls; nooit een teller onder nul (CHECK + GREATEST)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentStatus, DuplicaatSignaal, DuplicaatSignaalUitkomst
from app.werkvoorraad.models import WerkvoorraadTellerCache

# --- tellers (machine-sleutels = kolomnamen in WerkvoorraadKlant / de DTO) ----------------------------------------

TE_CONTROLEREN = "te_controleren"
KLAAR_OM_TE_BOEKEN = "klaar_om_te_boeken"
AFGEWEZEN = "afgewezen"
BIJ_KLANT = "bij_klant"
IBAN_WACHTEND = "iban_wachtend"
VRAGEN = "vragen"
MATCH_AFWIJKINGEN = "match_afwijkingen"
DUPLICAAT_SIGNALEN = "duplicaat_signalen"
TERUGKEREND_SIGNALEN = "terugkerend_signalen"
VOORRAAD_VERSCHILLEN = "voorraad_verschillen"
BUITEN_OFFERTE = "buiten_offerte"
PLANNING_SIGNALEN = "planning_signalen"
SPIEGEL_TAKEN = "spiegel_taken"

#: Status-tellers: één document telt in precies één (of geen) bucket — incrementeel bij te houden.
STATUS_TELLERS: tuple[str, ...] = (TE_CONTROLEREN, KLAAR_OM_TE_BOEKEN, AFGEWEZEN, BIJ_KLANT, IBAN_WACHTEND)
#: Signaaltellers die van de documentstatus afhangen (rij-in-signaaltabel × document niet terminaal): herteld bij een
#: wissel van/naar een terminale status. `vragen` volgt de KPI-definitie (open vraag op een niet-verdwenen document).
DOCUMENT_SIGNAAL_TELLERS: tuple[str, ...] = (VRAGEN, MATCH_AFWIJKINGEN, DUPLICAAT_SIGNALEN, BUITEN_OFFERTE)
#: Signaaltellers met een eigen motor (dag-cadans in sync-alles) of eigen mutatiepunt.
OVERIGE_SIGNAAL_TELLERS: tuple[str, ...] = (
    TERUGKEREND_SIGNALEN,
    VOORRAAD_VERSCHILLEN,
    PLANNING_SIGNALEN,
    SPIEGEL_TAKEN,
)
ALLE_TELLERS: tuple[str, ...] = STATUS_TELLERS + DOCUMENT_SIGNAAL_TELLERS + OVERIGE_SIGNAAL_TELLERS

# Statusbuckets voor de werkvoorraad-klantenlijst (mockup #werkvoorraad "Overzicht per klant").
# boeken_mislukt telt bewust mee als "te controleren": het vraagt om menselijke actie en mag
# nooit stil in een verborgen bucket vallen.
TE_CONTROLEREN_STATUSSEN: frozenset[DocumentStatus] = frozenset(
    {
        DocumentStatus.ONTVANGEN,
        DocumentStatus.EXTRACTIE_WACHTRIJ,
        DocumentStatus.EXTRACTIE_BEZIG,
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.BOEKEN_MISLUKT,
    }
)

#: Terminale statussen voor de werkvoorraad-tellers: geboekt, verwijderd, gesplitst (de kinderen tellen zelf),
#: samengevoegd (nabundel-dubbelpaar 03-09), geaccordeerd (verplichting 04-09: geen boeking volgt) en afgevoerd
#: duplicaat (fixrun 08-09 blok 3: telt in GEEN werkvoorraad-teller/-tab mee, ook niet als "afgewezen").
TERMINAAL_VOOR_TELLERS: tuple[DocumentStatus, ...] = (
    DocumentStatus.VERWIJDERD,
    DocumentStatus.GEBOEKT,
    DocumentStatus.GESPLITST,
    DocumentStatus.SAMENGEVOEGD,
    DocumentStatus.GEACCORDEERD,
    DocumentStatus.AFGEVOERD_DUPLICAAT,
)
_TERMINAAL_SET = frozenset(TERMINAAL_VOOR_TELLERS)

_BUCKET_PER_STATUS: dict[DocumentStatus, str] = {
    **dict.fromkeys(TE_CONTROLEREN_STATUSSEN, TE_CONTROLEREN),
    DocumentStatus.KLAAR_OM_TE_BOEKEN: KLAAR_OM_TE_BOEKEN,
    DocumentStatus.AFGEWEZEN: AFGEWEZEN,
    # Klant-accordering (migratie 0033): "Bij klant" = documenten die op één of meer accorderingslagen wachten.
    DocumentStatus.TER_ACCORDERING: BIJ_KLANT,
    DocumentStatus.WACHT_OP_IBAN_ACCORDERING: IBAN_WACHTEND,
}


def bucket_van_status(status: DocumentStatus | str | None) -> str | None:
    """De status-teller waarin een document met deze status telt; None = telt in geen werkvoorraad-teller."""
    if status is None:
        return None
    return _BUCKET_PER_STATUS.get(DocumentStatus(status))


def is_terminaal(status: DocumentStatus | str | None) -> bool:
    return status is not None and DocumentStatus(status) in _TERMINAAL_SET


# --- laag 1: de telling (de definitie) --------------------------------------------------------------------------------


def _tel_status_tellers(session: Session, administratie_id: uuid.UUID) -> dict[str, int]:
    per_status = dict(
        session.execute(
            select(Document.status, func.count())
            .where(
                Document.administratie_id == administratie_id,
                Document.status.notin_(list(TERMINAAL_VOOR_TELLERS)),
            )
            .group_by(Document.status)
        ).all()
    )
    tellers = dict.fromkeys(STATUS_TELLERS, 0)
    for status, aantal in per_status.items():
        bucket = bucket_van_status(status)
        if bucket is not None:
            tellers[bucket] += int(aantal)
    return tellers


def _tel_document_signalen(session: Session, administratie_id: uuid.UUID, welke: Iterable[str]) -> dict[str, int]:
    from app.uren.models import Factuurmatch  # lazy: geen kringimport op moduleniveau
    from app.verplichting import match_pipeline as verplichting_match
    from app.vragen import service as vragen_kpi

    uit: dict[str, int] = {}
    for teller in welke:
        if teller == VRAGEN:
            # Open vragen (G1 03-09): de KPI-definitie uit app.vragen.service — één bron met de kaart "Open vragen".
            uit[teller] = vragen_kpi.tel_open_vragen(session, administratie_id)
        elif teller == MATCH_AFWIJKINGEN:
            # Factuurmatch-signaalteller (fase 2, besluit 3): afwijkingen op nog-open documenten.
            uit[teller] = (
                session.scalar(
                    select(func.count())
                    .select_from(Factuurmatch)
                    .join(Document, Document.id == Factuurmatch.document_id)
                    .where(
                        Factuurmatch.administratie_id == administratie_id,
                        Factuurmatch.uitkomst == "afwijking",
                        Document.status.notin_(list(TERMINAAL_VOOR_TELLERS)),
                    )
                )
                or 0
            )
        elif teller == DUPLICAAT_SIGNALEN:
            uit[teller] = (
                session.scalar(
                    select(func.count())
                    .select_from(DuplicaatSignaal)
                    .join(Document, Document.id == DuplicaatSignaal.document_id)
                    .where(
                        DuplicaatSignaal.administratie_id == administratie_id,
                        DuplicaatSignaal.uitkomst == DuplicaatSignaalUitkomst.MOGELIJK_DUPLICAAT.value,
                        Document.status.notin_(list(TERMINAAL_VOOR_TELLERS)),
                    )
                )
                or 0
            )
        elif teller == BUITEN_OFFERTE:
            # Buiten offerte (⑤, 04-09): één aggregaatquery op verplichting_match — signaal, geen status.
            uit[teller] = verplichting_match.tel_buiten_offerte(session, administratie_id)
    return uit


def _tel_overige_signalen(session: Session, administratie_id: uuid.UUID, welke: Iterable[str]) -> dict[str, int]:
    uit: dict[str, int] = {}
    for teller in welke:
        if teller == TERUGKEREND_SIGNALEN:
            from app.terugkerend import service as terugkerend_service

            uit[teller] = terugkerend_service.tel_ontbrekend(session, administratie_id)
        elif teller == VOORRAAD_VERSCHILLEN:
            # Voorraadverschil (C2 03-09): uitsluitend bij de voorraad-opt-in — dezelfde motorfunctie als de
            # kantoorbrede lijst.
            from app.voorraad import service as voorraad_service

            uit[teller] = voorraad_service.tel_verschillen(session, administratie_id)
        elif teller == PLANNING_SIGNALEN:
            # Geplande week zonder weekstaat (blok A 06-09): één definitie mét /uren/kantoor/planning-signalen.
            from app.uren import planning_signaal

            uit[teller] = planning_signaal.tel_signalen(session, administratie_id)
        elif teller == SPIEGEL_TAKEN:
            # Open spiegel-taken (doorbelasting): bron geboekt, spiegel-inkoopfactuur in de doel-administratie nog
            # niet —
            # tot blok 6 haalde de klantenlijst dit per administratie op (71 requests per schermopening).
            from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingBoekingStatus

            uit[teller] = (
                session.scalar(
                    select(func.count())
                    .select_from(DoorbelastingBoeking)
                    .where(
                        DoorbelastingBoeking.administratie_id == administratie_id,
                        DoorbelastingBoeking.status == DoorbelastingBoekingStatus.SPIEGEL_OPEN.value,
                    )
                )
                or 0
            )
    return uit


def tel_direct(session: Session, administratie_id: uuid.UUID) -> dict[str, int]:
    """Álle tellers van één administratie rechtstreeks uit de brontabellen — de definitie. Verwacht een op deze
    administratie gescoopte sessie (`scoped_session(administratie_id, …)`)."""
    tellers = _tel_status_tellers(session, administratie_id)
    tellers.update(_tel_document_signalen(session, administratie_id, DOCUMENT_SIGNAAL_TELLERS))
    tellers.update(_tel_overige_signalen(session, administratie_id, OVERIGE_SIGNAAL_TELLERS))
    return tellers


# --- laag 2: de cache -----------------------------------------------------------------------------------------------


def schrijf_cache(session: Session, administratie_id: uuid.UUID, tellers: dict[str, int]) -> None:
    """Upsert van de gegeven tellers (één statement)."""
    if not tellers:
        return
    nu = datetime.now(UTC)
    stmt = insert(WerkvoorraadTellerCache).values(
        [
            {"administratie_id": administratie_id, "teller": teller, "waarde": max(int(waarde), 0), "bijgewerkt_op": nu}
            for teller, waarde in tellers.items()
        ]
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[WerkvoorraadTellerCache.administratie_id, WerkvoorraadTellerCache.teller],
            set_={"waarde": stmt.excluded.waarde, "bijgewerkt_op": stmt.excluded.bijgewerkt_op},
        )
    )


def lees_cache(session: Session, administratie_id: uuid.UUID) -> dict[str, int]:
    return dict(
        session.execute(
            select(WerkvoorraadTellerCache.teller, WerkvoorraadTellerCache.waarde).where(
                WerkvoorraadTellerCache.administratie_id == administratie_id
            )
        ).all()
    )


def _verschuif(session: Session, administratie_id: uuid.UUID, teller: str, delta: int) -> None:
    """Incrementele delta op één cache-rij. Ontbreekt de rij, dan gebeurt er bewust niets: de leesroute telt dan
    direct en maakt de rij aan (fail-safe) — een halve cache is erger dan geen cache."""
    if delta == 0:
        return
    session.execute(
        update(WerkvoorraadTellerCache)
        .where(
            WerkvoorraadTellerCache.administratie_id == administratie_id,
            WerkvoorraadTellerCache.teller == teller,
        )
        .values(
            waarde=func.greatest(WerkvoorraadTellerCache.waarde + delta, 0),
            bijgewerkt_op=datetime.now(UTC),
        )
    )


def _cache_compleet(session: Session, administratie_id: uuid.UUID) -> bool:
    aanwezig = session.scalar(
        select(func.count())
        .select_from(WerkvoorraadTellerCache)
        .where(WerkvoorraadTellerCache.administratie_id == administratie_id)
    )
    return int(aanwezig or 0) >= len(ALLE_TELLERS)


def ververs_signalen(session: Session, administratie_id: uuid.UUID | None, welke: Sequence[str]) -> None:
    """Hertel de gegeven signaaltellers en schrijf ze in de cache — voor mutatiepunten buiten de statusmachine (vraag
    gesteld/afgehandeld/ingetrokken, spiegel-taak ontstaan/geboekt). Alleen als de cache van de administratie al
    bestaat (anders vult de fail-safe hem compleet); administratie_id None (verzamelbak) = niets."""
    if administratie_id is None or not welke:
        return
    if not _cache_compleet(session, administratie_id):
        return
    tellers: dict[str, int] = {}
    tellers.update(
        _tel_document_signalen(session, administratie_id, [t for t in welke if t in DOCUMENT_SIGNAAL_TELLERS])
    )
    tellers.update(_tel_overige_signalen(session, administratie_id, [t for t in welke if t in OVERIGE_SIGNAAL_TELLERS]))
    schrijf_cache(session, administratie_id, tellers)


def verwerk_nieuw_document(session: Session, administratie_id: uuid.UUID | None, status: DocumentStatus) -> None:
    """Aanmaak van een document in een administratie: +1 op de bucket van de beginstatus (zelfde sessie/transactie)."""
    if administratie_id is None:
        return
    bucket = bucket_van_status(status)
    if bucket is not None:
        _verschuif(session, administratie_id, bucket, +1)


def verwerk_statusovergang(
    session: Session, administratie_id: uuid.UUID | None, van: DocumentStatus | None, naar: DocumentStatus
) -> None:
    """Statusovergang van een document (vanuit `_schrijf_overgang`, zelfde transactie): oude bucket −1, nieuwe bucket
    +1;
    bij een wissel van/naar een terminale status worden de documentafhankelijke signaaltellers herteld (4 COUNT's)."""
    if administratie_id is None:
        return
    oud, nieuw = bucket_van_status(van), bucket_van_status(naar)
    if oud != nieuw:
        if oud is not None:
            _verschuif(session, administratie_id, oud, -1)
        if nieuw is not None:
            _verschuif(session, administratie_id, nieuw, +1)
    if is_terminaal(van) != is_terminaal(naar):
        ververs_signalen(session, administratie_id, DOCUMENT_SIGNAAL_TELLERS)


# --- laag 3: lezen voor de scope (set-based) + herrekenen -----------------------------------------------------------


@dataclass(frozen=True)
class TellersVanAdministratie:
    administratie_id: uuid.UUID
    naam: str
    tellers: dict[str, int]
    uit_cache: bool


def _vul_fail_safe(administratie_id: uuid.UUID, *, actor_id: uuid.UUID) -> dict[str, int]:
    """Ontbrekende (of onvolledige) cache: direct tellen in de gescoopte sessie en de rijen aanmaken."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        tellers = tel_direct(session, administratie_id)
        schrijf_cache(session, administratie_id, tellers)
    return tellers


def lees_voor_scope(
    *, actor_id: uuid.UUID, administratie_ids_met_naam: Sequence[tuple[uuid.UUID, str]]
) -> list[TellersVanAdministratie]:
    """De leesroute van de klantenlijst: ÉÉN statement over alle administraties in de scope van de actor
    (`scoped_session(None, actor_id=…)`; RLS op de cache = de scope-waarheid). Administraties zónder (complete) cache
    krijgen de fail-safe (direct tellen + rij aanmaken) — daarna zijn ze gecachet. Volgorde = aangeleverde volgorde."""
    ids = [aid for aid, _ in administratie_ids_met_naam]
    per_administratie: dict[uuid.UUID, dict[str, int]] = {aid: {} for aid in ids}
    if ids:
        with scoped_session(None, actor_id=actor_id) as session:
            rijen = session.execute(
                select(
                    WerkvoorraadTellerCache.administratie_id,
                    WerkvoorraadTellerCache.teller,
                    WerkvoorraadTellerCache.waarde,
                ).where(WerkvoorraadTellerCache.administratie_id.in_(ids))
            ).all()
        for aid, teller, waarde in rijen:
            per_administratie[aid][teller] = int(waarde)
    uit: list[TellersVanAdministratie] = []
    for aid, naam in administratie_ids_met_naam:
        tellers = per_administratie[aid]
        uit_cache = all(t in tellers for t in ALLE_TELLERS)
        if not uit_cache:
            tellers = _vul_fail_safe(aid, actor_id=actor_id)
        uit.append(TellersVanAdministratie(administratie_id=aid, naam=naam, tellers=tellers, uit_cache=uit_cache))
    return uit


@dataclass(frozen=True)
class Afwijking:
    administratie_id: uuid.UUID
    naam: str
    teller: str
    cache: int | None  # None = rij ontbrak
    telling: int


@dataclass
class HerrekenRapport:
    dry_run: bool
    administraties: int = 0
    ontbrekend: int = 0  # administraties zonder enige cache-rij (nog nooit gelezen) — geen drift
    afwijkingen: list[Afwijking] = field(default_factory=list)
    fouten: list[str] = field(default_factory=list)

    @property
    def administraties_met_afwijking(self) -> int:
        return len({a.administratie_id for a in self.afwijkingen})


@dataclass(frozen=True)
class HerrekenUitkomst:
    afwijkingen: list[Afwijking]
    cache_ontbrak: bool  # geen enkele rij: nog nooit gelezen/herrekend — géén drift (de fail-safe vult hem)


def herreken(administratie_id: uuid.UUID, *, naam: str = "", dry_run: bool = False) -> HerrekenUitkomst:
    """Eén administratie: telling ↔ cache vergelijken en (tenzij dry-run) de cache overschrijven. Een administratie
    ZONDER enige cache-rij is geen afwijking maar `cache_ontbrak` (een halve cache is wél drift: dan ontbreken rijen die
    er hadden moeten zijn)."""
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        telling = tel_direct(session, administratie_id)
        cache = lees_cache(session, administratie_id)
        afwijkingen = (
            []
            if not cache
            else [
                Afwijking(administratie_id=administratie_id, naam=naam, teller=t, cache=cache.get(t), telling=w)
                for t, w in telling.items()
                if cache.get(t) != w
            ]
        )
        if not dry_run:
            schrijf_cache(session, administratie_id, telling)
    return HerrekenUitkomst(afwijkingen=afwijkingen, cache_ontbrak=not cache)


def actieve_administraties() -> list[tuple[uuid.UUID, str]]:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        return [
            (a.id, a.naam)
            for a in session.scalars(
                select(Administratie).where(Administratie.actief.is_(True)).order_by(Administratie.naam)
            )
        ]


def herreken_alle(*, administratie_ids: Sequence[uuid.UUID] | None = None, dry_run: bool = False) -> HerrekenRapport:
    """Alle actieve administraties (of de gegeven) herrekenen; één kapotte administratie stopt de rest niet."""
    rapport = HerrekenRapport(dry_run=dry_run)
    kandidaten = actieve_administraties()
    if administratie_ids is not None:
        gewenst = set(administratie_ids)
        kandidaten = [(aid, naam) for aid, naam in kandidaten if aid in gewenst]
    for aid, naam in kandidaten:
        rapport.administraties += 1
        try:
            uitkomst = herreken(aid, naam=naam, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 — zichtbaar in het rapport, nooit stil
            rapport.fouten.append(f"{naam} ({aid}): {exc}")
            continue
        if uitkomst.cache_ontbrak:
            rapport.ontbrekend += 1
        rapport.afwijkingen.extend(uitkomst.afwijkingen)
    return rapport
