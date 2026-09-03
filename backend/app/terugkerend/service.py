"""Terugkerende-facturen-signaal — deterministisch (opdracht 30-08 blok B; benchmark-besluit Peter 29-08).

Per (administratie, crediteur) geldt een leverancier als TERUGKEREND bij ≥ 3 facturen met een regelmatig
interval: maand (≈ 30,4 d) of kwartaal (≈ 91,3 d), élke tussenpoos binnen ±35 % van het nominale interval.
Bron = de documenthistorie in de app (Boekvoorstel: factuurdatum + totaalbedrag, alle niet-verwijderde
inkoopfacturen) aangevuld met het RLZ-boekingsgeheugen (BoekingObservatie: één datum per boekstuk; geen
bedragen — telt alleen mee voor het patroon en de laatste datum).

Signaal 1 "verwachte factuur ontbreekt": vandaag > laatste datum + interval × 1,35 zonder nieuwe factuur →
`ontbreekt_sinds` (oranje werkvoorraad-teller, geen blokkade); verdwijnt vanzelf bij de volgende factuur
(herberekening). Snooze (tot datum) / afmelden per leverancier = menskeuze mét audit.
Signaal 2 "prijsstijging": laatste factuurbedrag > (1 + drempel %) × het bedrag van de vorige vergelijkbare
factuur (drempel per administratie, default 10) → chip op het controlescherm + vermelding in het overzicht.
Alleen signaleren — nooit blokkeren of muteren; géén AI. Dagelijks meeliftend in sync-alles."""

from __future__ import annotations

import logging
import statistics
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Boekvoorstel, Document, DocumentSoort, DocumentStatus
from app.geheugen.models import BoekingObservatie
from app.sync.models import VendorCache
from app.terugkerend.models import TerugkerendSignaal

logger = logging.getLogger(__name__)

MIN_FACTUREN = 3
TOLERANTIE = Decimal("0.35")
# Nominale intervallen in dagen (gemiddelde maand / kwartaal).
NOMINAAL = {"maand": Decimal("30.44"), "kwartaal": Decimal("91.31")}
_HONDERDSTE = Decimal("0.01")


class TerugkerendFout(Exception):
    pass


@dataclass(frozen=True)
class Patroon:
    soort: str  # maand | kwartaal
    interval_dagen: int  # mediaan van de waargenomen tussenpozen
    aantal: int


def detecteer_patroon(datums: list[date]) -> Patroon | None:
    """Pure functie: ≥ 3 unieke datums, oplopend gesorteerd; élke tussenpoos binnen ±35 % van het
    nominale interval van maand óf kwartaal (de mediaan kiest het patroon). Onregelmatig, eenmalig of
    te weinig facturen = None (geen signaal, nooit gokken)."""
    uniek = sorted(set(datums))
    if len(uniek) < MIN_FACTUREN:
        return None
    gaten = [(b - a).days for a, b in zip(uniek, uniek[1:], strict=False)]
    if any(g <= 0 for g in gaten):
        return None
    mediaan = Decimal(str(statistics.median(gaten)))
    for soort, nominaal in NOMINAAL.items():
        onder, boven = nominaal * (1 - TOLERANTIE), nominaal * (1 + TOLERANTIE)
        if onder <= mediaan <= boven and all(onder <= Decimal(g) <= boven for g in gaten):
            return Patroon(soort=soort, interval_dagen=int(mediaan.to_integral_value(ROUND_HALF_UP)), aantal=len(uniek))
    return None


def verwachting(patroon: Patroon, laatste: date) -> tuple[date, date]:
    """(verwacht_op, uiterlijk_op): nominaal interval ná de laatste factuur, uiterlijk = + 35 % tolerantie."""
    nominaal = NOMINAAL[patroon.soort]
    verwacht = laatste + timedelta(days=int(nominaal.to_integral_value(ROUND_HALF_UP)))
    uiterlijk = laatste + timedelta(days=int((nominaal * (1 + TOLERANTIE)).to_integral_value(ROUND_HALF_UP)))
    return verwacht, uiterlijk


def prijsstijging_pct(laatste: Decimal | None, vorige: Decimal | None, drempel_pct: Decimal) -> Decimal | None:
    """Signaal 2, puur: stijging in % van vorige → laatste als die boven de drempel ligt, anders None.
    Negatieve/nul-bedragen (creditnota's) doen niet mee — nooit een vals signaal op een correctie."""
    if laatste is None or vorige is None or vorige <= 0 or laatste <= 0:
        return None
    stijging = ((laatste - vorige) / vorige * 100).quantize(_HONDERDSTE, rounding=ROUND_HALF_UP)
    return stijging if stijging > drempel_pct else None


@dataclass(frozen=True)
class _Factuur:
    datum: date
    bedrag: Decimal | None
    document_id: uuid.UUID | None


def _facturen_per_vendor(session: Session, administratie_id: uuid.UUID) -> dict[uuid.UUID, list[_Factuur]]:
    """App-documenten (met bedrag) + RLZ-historie (alleen datum, één per boekstuk) per crediteur."""
    per: dict[uuid.UUID, list[_Factuur]] = {}
    rijen = session.execute(
        select(Boekvoorstel.vendor_id, Boekvoorstel.factuurdatum, Boekvoorstel.totaalbedrag, Boekvoorstel.document_id)
        .join(Document, Document.id == Boekvoorstel.document_id)
        .where(
            Document.administratie_id == administratie_id,
            Document.soort == DocumentSoort.INKOOPFACTUUR.value,
            Document.status.notin_([DocumentStatus.VERWIJDERD, DocumentStatus.GESPLITST]),
            Boekvoorstel.vendor_id.is_not(None),
            Boekvoorstel.factuurdatum.is_not(None),
        )
    ).all()
    for vendor_id, datum, bedrag, document_id in rijen:
        per.setdefault(vendor_id, []).append(_Factuur(datum=datum, bedrag=bedrag, document_id=document_id))
    historie = session.execute(
        select(BoekingObservatie.vendor_id, BoekingObservatie.bron_datum, BoekingObservatie.boekstuk_ref)
        .where(BoekingObservatie.administratie_id == administratie_id, BoekingObservatie.bron == "rlz_seed")
        .distinct()
    ).all()
    gezien: set[tuple[uuid.UUID, str | None, date]] = set()
    for vendor_id, datum, boekstuk in historie:
        sleutel = (vendor_id, boekstuk, datum)
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        lijst = per.setdefault(vendor_id, [])
        if not any(f.datum == datum for f in lijst):
            lijst.append(_Factuur(datum=datum, bedrag=None, document_id=None))
    return per


def herbereken_administratie(*, administratie_id: uuid.UUID, vandaag: date | None = None) -> dict[str, int]:
    """Dagelijkse herberekening (sync-alles) én op verzoek: per crediteur patroon → upsert; leveranciers
    zonder patroon verdwijnen uit de signaallaag (afgeleid, herrekenbaar). Snooze/afmelden blijven
    staan. Retourneert tellers voor de rapportage."""
    vandaag = vandaag or datetime.now(UTC).date()
    telling = {"terugkerend": 0, "ontbreekt": 0, "prijsstijging": 0, "vervallen": 0}
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        administratie = session.get(Administratie, administratie_id)
        drempel = administratie.terugkerend_prijsstijging_pct if administratie else Decimal("10")
        bestaand = {
            r.vendor_id: r
            for r in session.scalars(
                select(TerugkerendSignaal).where(TerugkerendSignaal.administratie_id == administratie_id)
            )
        }
        actueel: set[uuid.UUID] = set()
        for vendor_id, facturen in _facturen_per_vendor(session, administratie_id).items():
            patroon = detecteer_patroon([f.datum for f in facturen])
            if patroon is None:
                continue
            actueel.add(vendor_id)
            gesorteerd = sorted(facturen, key=lambda f: f.datum)
            laatste = gesorteerd[-1]
            # Vorige vergelijkbare factuur mét bedrag (RLZ-historie draagt geen bedrag).
            met_bedrag = [f for f in gesorteerd if f.bedrag is not None]
            vorige = met_bedrag[-2] if laatste.bedrag is not None and len(met_bedrag) >= 2 else None
            verwacht, uiterlijk = verwachting(patroon, laatste.datum)
            ontbreekt = uiterlijk if vandaag > uiterlijk else None
            stijging = prijsstijging_pct(laatste.bedrag, vorige.bedrag if vorige else None, drempel)
            rij = bestaand.get(vendor_id)
            if rij is None:
                rij = TerugkerendSignaal(administratie_id=administratie_id, vendor_id=vendor_id)
                session.add(rij)
            rij.patroon = patroon.soort
            rij.interval_dagen = patroon.interval_dagen
            rij.aantal_facturen = patroon.aantal
            rij.laatste_datum = laatste.datum
            rij.laatste_bedrag = laatste.bedrag
            rij.laatste_document_id = laatste.document_id
            rij.vorige_datum = vorige.datum if vorige else None
            rij.vorige_bedrag = vorige.bedrag if vorige else None
            rij.verwacht_op = verwacht
            rij.uiterlijk_op = uiterlijk
            rij.ontbreekt_sinds = ontbreekt
            rij.prijsstijging_pct = stijging
            # Een snooze die vóór de nieuwe laatste factuur lag is uitgewerkt.
            if rij.snooze_tot is not None and rij.snooze_tot <= laatste.datum:
                rij.snooze_tot = None
            telling["terugkerend"] += 1
            if ontbreekt is not None and rij.snooze_tot is None and rij.afgemeld_op is None:
                telling["ontbreekt"] += 1
            if stijging is not None:
                telling["prijsstijging"] += 1
        vervallen = [v for v in bestaand if v not in actueel]
        if vervallen:
            session.execute(
                delete(TerugkerendSignaal).where(
                    TerugkerendSignaal.administratie_id == administratie_id,
                    TerugkerendSignaal.vendor_id.in_(vervallen),
                )
            )
            telling["vervallen"] = len(vervallen)
    return telling


def herbereken_alle(
    *,
    vandaag: date | None = None,
    voortgang: Callable[[uuid.UUID, dict[str, int] | str], None] | None = None,
) -> dict[uuid.UUID, dict[str, int] | str]:
    """Voor élke actieve administratie (sync-alles-patroon): één kapotte stopt de rest niet.
    `voortgang` (kantoorbrede achtergrondrun, blok B1 03-09) krijgt ná élke administratie de uitkomst
    zodat de run-rij zichtbaar meetelt; de motor zelf is ongewijzigd."""
    with scoped_session(None) as session:
        ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    uit: dict[uuid.UUID, dict[str, int] | str] = {}
    for administratie_id in ids:
        try:
            uit[administratie_id] = herbereken_administratie(administratie_id=administratie_id, vandaag=vandaag)
        except Exception as exc:  # noqa: BLE001 — één administratie mag de rest niet raken
            logger.exception("Terugkerend-signaal mislukt voor %s", administratie_id)
            uit[administratie_id] = str(exc)
        if voortgang is not None:
            voortgang(administratie_id, uit[administratie_id])
    return uit


def actief_signaal(rij: TerugkerendSignaal, vandaag: date) -> bool:
    """Signaal 1 telt alleen als het niet gesnoozed/afgemeld is."""
    if rij.afgemeld_op is not None or rij.ontbreekt_sinds is None:
        return False
    return rij.snooze_tot is None or rij.snooze_tot <= vandaag


def tel_ontbrekend(session: Session, administratie_id: uuid.UUID, vandaag: date | None = None) -> int:
    """Werkvoorraad-teller (duplicaat-patroon): leveranciers met een actief 'ontbreekt'-signaal."""
    vandaag = vandaag or datetime.now(UTC).date()
    rijen = session.scalars(
        select(TerugkerendSignaal).where(
            TerugkerendSignaal.administratie_id == administratie_id,
            TerugkerendSignaal.ontbreekt_sinds.is_not(None),
            TerugkerendSignaal.afgemeld_op.is_(None),
        )
    )
    return sum(1 for r in rijen if actief_signaal(r, vandaag))


@dataclass(frozen=True)
class SignaalData:
    id: uuid.UUID
    vendor_id: uuid.UUID
    leverancier: str | None
    patroon: str
    interval_dagen: int
    aantal_facturen: int
    laatste_datum: date
    laatste_bedrag: Decimal | None
    laatste_document_id: uuid.UUID | None
    vorige_datum: date | None
    vorige_bedrag: Decimal | None
    verwacht_op: date
    uiterlijk_op: date
    ontbreekt_sinds: date | None
    dagen_te_laat: int | None
    prijsstijging_pct: Decimal | None
    snooze_tot: date | None
    afgemeld_op: datetime | None
    status: str  # ontbreekt | op_schema | gesnoozed | afgemeld
    berekend_op: datetime


def _status(rij: TerugkerendSignaal, vandaag: date) -> str:
    if rij.afgemeld_op is not None:
        return "afgemeld"
    if rij.snooze_tot is not None and rij.snooze_tot > vandaag:
        return "gesnoozed"
    if rij.ontbreekt_sinds is not None:
        return "ontbreekt"
    return "op_schema"


def overzicht(*, administratie_id: uuid.UUID, vandaag: date | None = None) -> list[SignaalData]:
    """Signaal-overzicht per administratie: ontbrekend eerst, dan prijsstijgingen, dan op schema."""
    vandaag = vandaag or datetime.now(UTC).date()
    with scoped_session(administratie_id) as session:
        rijen = list(
            session.scalars(select(TerugkerendSignaal).where(TerugkerendSignaal.administratie_id == administratie_id))
        )
        namen = dict(
            session.execute(
                select(VendorCache.id, VendorCache.naam).where(VendorCache.administratie_id == administratie_id)
            ).all()
        )
        session.expunge_all()
    uit = [
        SignaalData(
            id=r.id,
            vendor_id=r.vendor_id,
            leverancier=namen.get(r.vendor_id),
            patroon=r.patroon,
            interval_dagen=r.interval_dagen,
            aantal_facturen=r.aantal_facturen,
            laatste_datum=r.laatste_datum,
            laatste_bedrag=r.laatste_bedrag,
            laatste_document_id=r.laatste_document_id,
            vorige_datum=r.vorige_datum,
            vorige_bedrag=r.vorige_bedrag,
            verwacht_op=r.verwacht_op,
            uiterlijk_op=r.uiterlijk_op,
            ontbreekt_sinds=r.ontbreekt_sinds,
            dagen_te_laat=(vandaag - r.uiterlijk_op).days if r.ontbreekt_sinds is not None else None,
            prijsstijging_pct=r.prijsstijging_pct,
            snooze_tot=r.snooze_tot,
            afgemeld_op=r.afgemeld_op,
            status=_status(r, vandaag),
            berekend_op=r.berekend_op,
        )
        for r in rijen
    ]
    volgorde = {"ontbreekt": 0, "op_schema": 1, "gesnoozed": 2, "afgemeld": 3}
    uit.sort(key=lambda s: (volgorde[s.status], s.prijsstijging_pct is None, s.leverancier or ""))
    return uit


@dataclass(frozen=True)
class DocumentSignaal:
    """Prijsstijging-chip voor het controlescherm: alleen als DIT document de laatste factuur van een
    terugkerende leverancier is én boven de drempel ligt."""

    prijsstijging_pct: Decimal
    vorige_bedrag: Decimal
    vorige_datum: date | None
    laatste_bedrag: Decimal
    patroon: str
    leverancier: str | None


def signaal_voor_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> DocumentSignaal | None:
    with scoped_session(administratie_id) as session:
        rij = session.scalars(
            select(TerugkerendSignaal).where(
                TerugkerendSignaal.administratie_id == administratie_id,
                TerugkerendSignaal.laatste_document_id == document_id,
                TerugkerendSignaal.prijsstijging_pct.is_not(None),
            )
        ).first()
        if rij is None or rij.vorige_bedrag is None or rij.laatste_bedrag is None:
            return None
        vendor = session.get(VendorCache, (rij.vendor_id, administratie_id))
        return DocumentSignaal(
            prijsstijging_pct=rij.prijsstijging_pct,
            vorige_bedrag=rij.vorige_bedrag,
            vorige_datum=rij.vorige_datum,
            laatste_bedrag=rij.laatste_bedrag,
            patroon=rij.patroon,
            leverancier=vendor.naam if vendor else None,
        )


def snooze(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID, tot: date | None, actor_id: uuid.UUID) -> None:
    """Snooze tot datum (None = opheffen) — audit oud→nieuw; het signaal blijft bestaan, telt niet."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.scalars(
            select(TerugkerendSignaal).where(
                TerugkerendSignaal.administratie_id == administratie_id, TerugkerendSignaal.vendor_id == vendor_id
            )
        ).first()
        if rij is None:
            raise TerugkerendFout("Geen terugkerend patroon bekend voor deze leverancier")
        if tot is not None and tot <= datetime.now(UTC).date():
            raise TerugkerendFout("Snooze-datum moet in de toekomst liggen")
        oud = rij.snooze_tot
        rij.snooze_tot = tot
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="terugkerend_signaal",
            record_id=rij.id,
            actie="terugkerend_signaal_gesnoozed" if tot else "terugkerend_signaal_snooze_opgeheven",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"snooze_tot": oud.isoformat() if oud else None},
            nieuwe_waarde={"snooze_tot": tot.isoformat() if tot else None, "vendor_id": str(vendor_id)},
            administratie_id=administratie_id,
        )


def zet_afgemeld(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID, afgemeld: bool, actor_id: uuid.UUID) -> None:
    """Afmelden per leverancier (omkeerbaar): geen signaal 1 meer voor deze leverancier; audit."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.scalars(
            select(TerugkerendSignaal).where(
                TerugkerendSignaal.administratie_id == administratie_id, TerugkerendSignaal.vendor_id == vendor_id
            )
        ).first()
        if rij is None:
            raise TerugkerendFout("Geen terugkerend patroon bekend voor deze leverancier")
        oud = rij.afgemeld_op
        rij.afgemeld_op = datetime.now(UTC) if afgemeld else None
        rij.afgemeld_door = actor_id if afgemeld else None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="terugkerend_signaal",
            record_id=rij.id,
            actie="terugkerend_signaal_afgemeld" if afgemeld else "terugkerend_signaal_heractiveerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"afgemeld_op": oud.isoformat() if oud else None},
            nieuwe_waarde={"afgemeld": afgemeld, "vendor_id": str(vendor_id)},
            administratie_id=administratie_id,
        )


def zet_drempel(*, administratie_id: uuid.UUID, prijsstijging_pct: Decimal, actor_id: uuid.UUID) -> Decimal:
    """Drempel signaal 2 per administratie (Beheerder-only in de router), 0 < X ≤ 1000; audit oud→nieuw;
    herberekent direct zodat het overzicht klopt."""
    if not (Decimal(0) < prijsstijging_pct <= Decimal(1000)):
        raise TerugkerendFout("Drempel moet tussen 0 en 1000 procent liggen")
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise TerugkerendFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.terugkerend_prijsstijging_pct
        administratie.terugkerend_prijsstijging_pct = prijsstijging_pct
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="terugkerend_prijsstijging_pct_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"terugkerend_prijsstijging_pct": str(oud)},
            nieuwe_waarde={"terugkerend_prijsstijging_pct": str(prijsstijging_pct)},
        )
    herbereken_administratie(administratie_id=administratie_id)
    return prijsstijging_pct


def haal_drempel_op(*, administratie_id: uuid.UUID) -> Decimal:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise TerugkerendFout(f"Onbekende administratie: {administratie_id}")
        return administratie.terugkerend_prijsstijging_pct


def tel_signalen(session: Session, administratie_id: uuid.UUID) -> int:
    """Alias voor de werkvoorraad (documenten/service.py)."""
    return tel_ontbrekend(session, administratie_id)


__all__ = [
    "detecteer_patroon",
    "herbereken_administratie",
    "herbereken_alle",
    "overzicht",
    "prijsstijging_pct",
    "signaal_voor_document",
    "snooze",
    "tel_ontbrekend",
    "verwachting",
    "zet_afgemeld",
    "zet_drempel",
]
