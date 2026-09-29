"""Omzetrekening deterministisch per administratie voor Vastly-verkoopregels zónder `cbc:AccountingCost`
(Peter 29-09 punt 2; migratie 0172). Nooit meer "mens kiest" per document.

Volgorde per regel (in `verkoop/voorstel.py`):
 (a) `AccountingCost` uit de UBL, aanwezig én bekend in het rekeningschema → die rekening (koppelcontract §2d v1.10;
     onbekende code blijft blokkerend + automatische vraag, ongewijzigd);
 (b) anders de vaste Vastly-omzetrekening per (administratie, regelsoort) uit `vastly_omzetrekening`;
 (c) staat er nog geen rij, dan wordt ze hier AFGELEID en vastgelegd (bron 'historie'), in deze volgorde:
     1. de eigen geboekte Vastly-verkoopregels van de administratie (`verkoop_voorstel_regel` × `verkoop_boeking`
        geboekt): de meest gebruikte omzetrekening voor deze regelsoort, anders over alle regelsoorten;
     2. het rekeningschema: precies één actieve, niet-totaal omzetrekening (soort 1, code 8xxx) waarvan de naam de
        regelsoort noemt (huur/servicekosten/waarborg) — één treffer of niets, nooit raden;
     3. precies één actieve omzetrekening 8xxx in het hele schema (kleine administraties) — anders niets.
 (d) niets afleidbaar → `None`: het autoboek-pad weigert mét reden `omzetrekening_ontbreekt` en het reconciliatieblok
     `vastly_verkoop` maakt de bevinding `vastly_omzetrekening_ontbreekt` mét de handeling "Rekening kiezen" (per
     administratie éénmalig; Instellingen › Administratie › Vastgoed-koppeling toont en wijzigt dezelfde rijen).

Regelsoort uit de regelomschrijving (`Item/Name`), pure tekst: huur · servicekosten · waarborg · overig. Geen AI, geen
RLZ-call — de RLZ-historie (verkoopregels op 8xxx buiten de module) is bewust NIET live gelezen: de module kent geen
JournalEntryLines-cache en een GET per administratie in het boekpad is een latentie- en storingsrisico; het
rekeningschema + de eigen historie dekken de zes vastgoed-administraties (rapport 29-09)."""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Grootboekrekening
from app.verkoop.models import (
    VASTLY_REGELSOORTEN,
    VastlyOmzetrekening,
    VerkoopBoeking,
    VerkoopBoekingStatus,
    VerkoopVoorstelRegel,
)

REGELSOORT_HUUR = "huur"
REGELSOORT_SERVICEKOSTEN = "servicekosten"
REGELSOORT_WAARBORG = "waarborg"
REGELSOORT_OVERIG = "overig"
BRON_HISTORIE = "historie"
BRON_MENS = "mens"
#: Herkomst-label op een regel waarvan de rekening uit deze motor komt (UI-chip + autoboek-poort).
GB_BRON_OMZETREKENING = "omzetrekening"
#: Weigerreden voor het autoboek-pad + de bevindingssoort in het reconciliatieblok.
REDEN_OMZETREKENING_ONTBREEKT = "omzetrekening_ontbreekt"

_SERVICE = re.compile(r"service\s*kost|servicekost|voorschot|stook|gas|water|elektr|energie|schoonmaak|vve", re.I)
_WAARBORG = re.compile(r"waarborg|borg", re.I)
_HUUR = re.compile(r"\bhuur|kale huur|rent\b|verhuur|indexering|huurverhoging", re.I)
_OMZET_SOORT = 1  # RLZ AccountTypeEnum Revenue
_NAAM_TREFWOORD = {
    REGELSOORT_HUUR: re.compile(r"huur", re.I),
    REGELSOORT_SERVICEKOSTEN: re.compile(r"service", re.I),
    REGELSOORT_WAARBORG: re.compile(r"waarborg|borg", re.I),
}


class OmzetrekeningFout(Exception):
    """Ongeldige regelsoort of rekening (Beheerder-invoer)."""


def classificeer_regel(omschrijving: str | None) -> str:
    """Regelsoort uit de UBL-regelomschrijving — pure tekst, eerste treffer wint in de volgorde waarborg → service →
    huur (een 'voorschot servicekosten huur' is servicekosten, een 'waarborg huur' is waarborg)."""
    tekst = (omschrijving or "").strip()
    if not tekst:
        return REGELSOORT_OVERIG
    if _WAARBORG.search(tekst):
        return REGELSOORT_WAARBORG
    if _SERVICE.search(tekst):
        return REGELSOORT_SERVICEKOSTEN
    if _HUUR.search(tekst):
        return REGELSOORT_HUUR
    return REGELSOORT_OVERIG


@dataclass(frozen=True)
class OmzetrekeningStand:
    regelsoort: str
    ledger_id: uuid.UUID | None
    code: str | None
    naam: str | None
    bron: str | None  # historie | mens | None


def _omzetrekeningen(session: Session, administratie_id: uuid.UUID) -> list[Grootboekrekening]:
    return list(
        session.scalars(
            select(Grootboekrekening)
            .where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
                Grootboekrekening.is_totaalrekening.is_(False),
                Grootboekrekening.soort == _OMZET_SOORT,
                Grootboekrekening.code.like("8%"),
            )
            .order_by(Grootboekrekening.code)
        ).all()
    )


def _uit_eigen_historie(session: Session, administratie_id: uuid.UUID, regelsoort: str) -> uuid.UUID | None:
    rijen = session.execute(
        select(VerkoopVoorstelRegel.omschrijving, VerkoopVoorstelRegel.ledger_id)
        .join(VerkoopBoeking, VerkoopBoeking.document_id == VerkoopVoorstelRegel.document_id)
        .where(
            VerkoopBoeking.administratie_id == administratie_id,
            VerkoopBoeking.status == VerkoopBoekingStatus.GEBOEKT.value,
            VerkoopVoorstelRegel.ledger_id.is_not(None),
        )
    ).all()
    if not rijen:
        return None
    geldig = {r.ledger_id for r in _omzetrekeningen(session, administratie_id)}
    per_soort = Counter(
        r.ledger_id for r in rijen if classificeer_regel(r.omschrijving) == regelsoort and r.ledger_id in geldig
    )
    if per_soort:
        return per_soort.most_common(1)[0][0]
    alles = Counter(r.ledger_id for r in rijen if r.ledger_id in geldig)
    return alles.most_common(1)[0][0] if alles else None


def _uit_rekeningschema(session: Session, administratie_id: uuid.UUID, regelsoort: str) -> uuid.UUID | None:
    rekeningen = _omzetrekeningen(session, administratie_id)
    patroon = _NAAM_TREFWOORD.get(regelsoort)
    if patroon is not None:
        treffers = [r for r in rekeningen if patroon.search(r.naam or "")]
        if len(treffers) == 1:
            return treffers[0].ledger_id
    if len(rekeningen) == 1:
        return rekeningen[0].ledger_id
    return None


def leid_af(session: Session, *, administratie_id: uuid.UUID, regelsoort: str) -> uuid.UUID | None:
    """Volgorde (c) uit de module-doc; None = niets afleidbaar (nooit raden)."""
    return _uit_eigen_historie(session, administratie_id, regelsoort) or _uit_rekeningschema(
        session, administratie_id, regelsoort
    )


def omzetrekening_voor(
    session: Session, *, administratie_id: uuid.UUID, regelsoort: str, actor_id: uuid.UUID | None = None
) -> uuid.UUID | None:
    """De vaste omzetrekening voor (administratie, regelsoort): bestaande rij → die; anders afleiden én vastleggen
    (bron 'historie', zichtbaar op Instellingen). None = bevinding. Een vastgelegde rij naar een intussen uit de bron
    verdwenen rekening telt niet (dan opnieuw afleiden; de oude rij wordt overschreven mét audit)."""
    if regelsoort not in VASTLY_REGELSOORTEN:
        raise OmzetrekeningFout(f"onbekende regelsoort {regelsoort!r}")
    rij = session.get(VastlyOmzetrekening, (administratie_id, regelsoort))
    geldig = {r.ledger_id for r in _omzetrekeningen(session, administratie_id)}
    if rij is not None and rij.ledger_id in geldig:
        return rij.ledger_id
    ledger_id = leid_af(session, administratie_id=administratie_id, regelsoort=regelsoort)
    if ledger_id is None:
        return None
    _schrijf(
        session,
        administratie_id=administratie_id,
        regelsoort=regelsoort,
        ledger_id=ledger_id,
        bron=BRON_HISTORIE,
        actor_id=actor_id,
        bestaand=rij,
    )
    return ledger_id


def _schrijf(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    regelsoort: str,
    ledger_id: uuid.UUID,
    bron: str,
    actor_id: uuid.UUID | None,
    bestaand: VastlyOmzetrekening | None,
) -> None:
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    oud = None
    if bestaand is None:
        session.add(
            VastlyOmzetrekening(
                administratie_id=administratie_id,
                regelsoort=regelsoort,
                ledger_id=ledger_id,
                bron=bron,
                gewijzigd_door=actor_id,
            )
        )
    else:
        oud = {"ledger_id": str(bestaand.ledger_id), "bron": bestaand.bron}
        bestaand.ledger_id = ledger_id
        bestaand.bron = bron
        bestaand.gewijzigd_door = actor_id
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id or SYSTEEM_ACTOR_ID,
        module="boekhouding",
        tabel="vastly_omzetrekening",
        record_id=administratie_id,
        actie="vastly_omzetrekening_gezet",
        correlatie_id=uuid.uuid4(),
        oude_waarde=oud,
        nieuwe_waarde={"regelsoort": regelsoort, "ledger_id": str(ledger_id), "bron": bron},
        administratie_id=administratie_id,
    )


def zet_omzetrekening(
    session: Session, *, administratie_id: uuid.UUID, regelsoort: str, ledger_id: uuid.UUID, actor_id: uuid.UUID
) -> OmzetrekeningStand:
    """Beheerder-keuze (Instellingen of de bevinding "Rekening kiezen"): alleen een actieve, niet-totaal
    omzetrekening 8xxx van déze administratie; audit oud → nieuw; bron 'mens' wint van elke latere afleiding."""
    if regelsoort not in VASTLY_REGELSOORTEN:
        raise OmzetrekeningFout(f"onbekende regelsoort {regelsoort!r}")
    rekening = next((r for r in _omzetrekeningen(session, administratie_id) if r.ledger_id == ledger_id), None)
    if rekening is None:
        raise OmzetrekeningFout(
            "de gekozen rekening is geen actieve omzetrekening (8xxx, soort opbrengsten) van deze administratie"
        )
    bestaand = session.get(VastlyOmzetrekening, (administratie_id, regelsoort))
    _schrijf(
        session,
        administratie_id=administratie_id,
        regelsoort=regelsoort,
        ledger_id=ledger_id,
        bron=BRON_MENS,
        actor_id=actor_id,
        bestaand=bestaand,
    )
    return OmzetrekeningStand(
        regelsoort=regelsoort, ledger_id=ledger_id, code=rekening.code, naam=rekening.naam, bron=BRON_MENS
    )


def standen_voor(session: Session, *, administratie_id: uuid.UUID) -> list[OmzetrekeningStand]:
    """Per regelsoort de stand (rij of niets — hier wordt níét afgeleid: lezen schrijft niet)."""
    rekeningen = {r.ledger_id: r for r in _omzetrekeningen(session, administratie_id)}
    uit: list[OmzetrekeningStand] = []
    for soort in VASTLY_REGELSOORTEN:
        rij = session.get(VastlyOmzetrekening, (administratie_id, soort))
        rekening = rekeningen.get(rij.ledger_id) if rij is not None else None
        uit.append(
            OmzetrekeningStand(
                regelsoort=soort,
                ledger_id=rij.ledger_id if rij is not None else None,
                code=rekening.code if rekening is not None else None,
                naam=rekening.naam if rekening is not None else None,
                bron=rij.bron if rij is not None else None,
            )
        )
    return uit


def keuzelijst(session: Session, *, administratie_id: uuid.UUID) -> list[Grootboekrekening]:
    """De omzetrekeningen (8xxx, soort opbrengsten, actief, geen totaal) waaruit een Beheerder kiest."""
    return _omzetrekeningen(session, administratie_id)
