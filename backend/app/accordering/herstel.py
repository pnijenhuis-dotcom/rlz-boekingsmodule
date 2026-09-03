"""Herstelroute bugfix-run 28-08: `make accordering-herstel-boeken` — documenten waarvan de LAATSTE
klant-accorderingsronde AFGEROND is (alle lagen akkoord) maar die NIET geboekt staan, alsnog door
het gefixte na-laatste-akkoord-pad boeken (`service.boek_na_afgerond_akkoord`: systeem-actor,
orkestratie mét klaargezette doorbelasting, álle harde checks en poorten onverkort).

Aanleiding: vóór de fix zette `_rond_af_en_boek` het document éérst op klaar_om_te_boeken en bleef
het dáár stil hangen zodra de boekpoging faalde (casus Kempen Facilities 27-08: ±34 documenten om
15:40 + de gouden casus 226181551.pdf / Van Happen om 17:57). Die documenten zijn hier de kandidaten
(status klaar_om_te_boeken mét afgeronde ronde); documenten die ná de fix stranden staan op
ter_accordering mét `boek_fout` en zijn óók kandidaat.

Regels (opdracht Peter 28-08): NOOIT automatisch — dry-run is de default in de make-target
(`DRY_RUN=1` telt, toont de lijst én per document de diagnose: wat zou blokkeren), uitvoeren is een
expliciete actie. Volumerem wordt VOORAF getoetst — sinds punt 23 (28-08) de hoge noodrem ná
klant-akkoord (200/dag/administratie), niet de 20/dag-automatiseringsrem: bij het bereiken
stopt de run zichtbaar i.p.v. per document een boekfout te registreren. Eén mislukking stopt de rest
niet — alles in het rapport, per document geauditeerd via het gewone pad."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.accordering import service as accordering_service
from app.accordering.models import AccorderingStatus, DocumentAccordering
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken as boeken_service
from app.documenten.models import Boekvoorstel, Document, DocumentStatus, Vraag, VraagStatus
from app.sync.models import VendorCache

logger = logging.getLogger(__name__)

# Statussen waarin een document mét afgeronde ronde "nog niet geboekt" is en herstel zinvol:
# klaar_om_te_boeken = de oude stille terugval; ter_accordering = ná de fix mét boek_fout;
# boeken_mislukt = RLZ-fout tijdens de poging (retry hoort óók hier).
HERSTELBARE_STATUSSEN = frozenset(
    {DocumentStatus.KLAAR_OM_TE_BOEKEN, DocumentStatus.TER_ACCORDERING, DocumentStatus.BOEKEN_MISLUKT}
)


@dataclass(frozen=True)
class HerstelKandidaat:
    administratie_id: uuid.UUID
    administratie_naam: str
    document_id: uuid.UUID
    bestandsnaam: str
    leverancier: str | None
    totaalbedrag: Decimal | None
    documentstatus: str
    accordering_id: uuid.UUID
    afgerond_op: datetime | None
    doorbelasting_klaargezet: bool
    laatste_boek_fout: str | None


@dataclass
class HerstelResultaat:
    dry_run: bool
    kandidaten: list[HerstelKandidaat] = field(default_factory=list)
    # dry-run: per document de blokkades (leeg = "groen — boekt bij uitvoering")
    diagnose: dict[uuid.UUID, list[str]] = field(default_factory=dict)
    geboekt: list[uuid.UUID] = field(default_factory=list)
    mislukt: dict[uuid.UUID, str] = field(default_factory=dict)
    # niet geprobeerd: volumerem bereikt / --max bereikt — mét reden
    overgeslagen: dict[uuid.UUID, str] = field(default_factory=dict)


def kandidaten(*, administratie_id: uuid.UUID | None = None) -> list[HerstelKandidaat]:
    """Per (actieve) administratie: documenten met LAATSTE ronde afgerond én status in
    HERSTELBARE_STATUSSEN. Scope per administratie (RLS), geen N+1 per document."""
    with scoped_session(None) as session:
        stmt = select(Administratie).where(Administratie.actief.is_(True))
        if administratie_id is not None:
            stmt = stmt.where(Administratie.id == administratie_id)
        administraties = {a.id: a.naam for a in session.scalars(stmt)}
    resultaat: list[HerstelKandidaat] = []
    for aid, naam in sorted(administraties.items(), key=lambda kv: kv[1]):
        with scoped_session(aid) as session:
            rondes = list(
                session.scalars(
                    select(DocumentAccordering)
                    .where(DocumentAccordering.administratie_id == aid)
                    .order_by(DocumentAccordering.aangeboden_op.asc())
                )
            )
            laatste_per_document: dict[uuid.UUID, DocumentAccordering] = {}
            for ronde in rondes:
                laatste_per_document[ronde.document_id] = ronde
            afgerond = {
                d_id: r for d_id, r in laatste_per_document.items() if r.status == AccorderingStatus.AFGEROND.value
            }
            if not afgerond:
                continue
            documenten = {
                d.id: d
                for d in session.scalars(select(Document).where(Document.id.in_(list(afgerond))))
                if d.status in HERSTELBARE_STATUSSEN
            }
            if not documenten:
                continue
            voorstellen = {
                v.document_id: v
                for v in session.scalars(select(Boekvoorstel).where(Boekvoorstel.document_id.in_(list(documenten))))
            }
            vendor_ids = {v.vendor_id for v in voorstellen.values() if v.vendor_id is not None}
            vendors = (
                {
                    v.id: v.naam
                    for v in session.scalars(
                        select(VendorCache).where(VendorCache.administratie_id == aid, VendorCache.id.in_(vendor_ids))
                    )
                }
                if vendor_ids
                else {}
            )
            from app.doorbelasting import service as doorbelasting_service

            for d_id, document in sorted(documenten.items(), key=lambda kv: kv[1].bestandsnaam):
                ronde = afgerond[d_id]
                voorstel = voorstellen.get(d_id)
                fout, _ = accordering_service._boek_fout_van(ronde)
                resultaat.append(
                    HerstelKandidaat(
                        administratie_id=aid,
                        administratie_naam=naam,
                        document_id=d_id,
                        bestandsnaam=document.bestandsnaam,
                        leverancier=vendors.get(voorstel.vendor_id) if voorstel and voorstel.vendor_id else None,
                        totaalbedrag=Decimal(voorstel.totaalbedrag)
                        if voorstel and voorstel.totaalbedrag is not None
                        else None,
                        documentstatus=document.status.value,
                        accordering_id=ronde.id,
                        afgerond_op=ronde.afgerond_op,
                        doorbelasting_klaargezet=doorbelasting_service.klaargezette_run(session, document_id=d_id)
                        is not None,
                        laatste_boek_fout=fout,
                    )
                )
    return resultaat


def diagnose(kandidaat: HerstelKandidaat) -> list[str]:
    """Dry-run-toets zonder één schrijfactie: welke poorten zouden het boeken nu blokkeren?
    Zelfde volgorde als de motor (accorderingspoort → open vraag → doorbelasting-checks → harde
    checks → toggle/kill-switch → volumerem). Harde checks lezen RLZ (alleen GET's); onleesbaar =
    zichtbaar als blokkade, nooit stil 'groen'."""
    blokkades: list[str] = []
    aid, d_id = kandidaat.administratie_id, kandidaat.document_id
    with scoped_session(aid) as session:
        poort = accordering_service.accordering_blokkade_voor_boeken(session, document_id=d_id)
        if poort:
            blokkades.append(f"accorderingspoort: {poort}")
        open_vraag = session.scalars(
            select(Vraag).where(Vraag.document_id == d_id, Vraag.status == VraagStatus.OPEN.value)
        ).first()
        if open_vraag is not None:
            blokkades.append(f"open vraag {open_vraag.id} blokkeert boeken")
        if not boeken_service._is_boeken_toegestaan(session, administratie_id=aid):
            blokkades.append("boeken staat UIT (administratie-toggle of 'Boeken platformbreed')")
        limiet, na_akkoord = boeken_service.volumerem_limiet(administratie_id=aid, document_id=d_id)
        vandaag = boeken_service._boekingen_vandaag(session, administratie_id=aid)
        if vandaag >= limiet:
            blokkades.append(
                f"{'noodrem ná klant-akkoord' if na_akkoord else 'volumerem'}: vandaag al {vandaag} van max {limiet} "
                "boekingen voor deze administratie"
            )
    if kandidaat.doorbelasting_klaargezet:
        from app.doorbelasting import orkestratie

        try:
            orkestratie.toets_klaargezette_doorbelasting(
                administratie_id=aid, document_id=d_id, actor_id=SYSTEEM_ACTOR_ID
            )
        except orkestratie.DoorbelastingChecksNietGroen as exc:
            blokkades.append(
                "doorbelasting-checks: " + "; ".join(r.melding for r in exc.rapport.resultaten if not r.ok)
            )
        except Exception as exc:  # noqa: BLE001 — diagnose mag nooit zelf stranden
            blokkades.append(f"doorbelasting-toets onleesbaar: {exc}")
    try:
        from app.documenten.boekvoorstel import voer_checks_uit

        with boeken_service._port_voor(aid) as port:
            rapport = voer_checks_uit(administratie_id=aid, document_id=d_id, client=port.leesclient())
        if rapport.geblokkeerd:
            blokkades.append("harde checks: " + "; ".join(r.melding for r in rapport.resultaten if not r.ok))
    except Exception as exc:  # noqa: BLE001
        blokkades.append(f"harde checks niet uitvoerbaar (RLZ/credentials): {exc}")
    return blokkades


def herstel_boeken(
    *, dry_run: bool, administratie_id: uuid.UUID | None = None, max_aantal: int | None = None
) -> HerstelResultaat:
    """Alle kandidaten langs. `dry_run=True` = lijst + diagnose, niets geschreven. Anders per
    document `boek_na_afgerond_akkoord` (het gefixte pad — mislukking = boek_fout + tijdlijn +
    audit via dat pad, hier alleen gerapporteerd). Volumerem vooraf per administratie; `max_aantal`
    begrenst de run (bv. eerst één document als proef)."""
    resultaat = HerstelResultaat(dry_run=dry_run, kandidaten=kandidaten(administratie_id=administratie_id))
    if dry_run:
        for k in resultaat.kandidaten:
            resultaat.diagnose[k.document_id] = diagnose(k)
        return resultaat

    geprobeerd = 0
    for k in resultaat.kandidaten:
        if max_aantal is not None and geprobeerd >= max_aantal:
            resultaat.overgeslagen[k.document_id] = f"--max {max_aantal} bereikt"
            continue
        # Punt 23: de herstel-CLI boekt ná een compleet klant-akkoord → dezelfde noodrem als het
        # accorderingspad (20/dag geldt hier niet meer; de env-var-truc van 28-08 is niet meer nodig).
        limiet, na_akkoord = boeken_service.volumerem_limiet(
            administratie_id=k.administratie_id, document_id=k.document_id
        )
        with scoped_session(k.administratie_id) as session:
            vandaag = boeken_service._boekingen_vandaag(session, administratie_id=k.administratie_id)
        if vandaag >= limiet:
            rem = "noodrem ná klant-akkoord" if na_akkoord else "volumerem"
            env = (
                "MAX_BOEKINGEN_NA_KLANT_AKKOORD_PER_DAG_PER_ADMINISTRATIE"
                if na_akkoord
                else "MAX_BOEKINGEN_PER_DAG_PER_ADMINISTRATIE"
            )
            resultaat.overgeslagen[k.document_id] = (
                f"{rem}: vandaag al {vandaag} van max {limiet} boekingen voor {k.administratie_naam} — "
                f"rest morgen, of {env} voor déze run verhogen"
            )
            continue
        geprobeerd += 1
        try:
            uitkomst = accordering_service.boek_na_afgerond_akkoord(
                administratie_id=k.administratie_id, document_id=k.document_id
            )
        except Exception as exc:  # noqa: BLE001 — één document stopt de rest niet
            logger.exception("Herstel accordering-boeken: document %s onverwacht mislukt", k.document_id)
            resultaat.mislukt[k.document_id] = f"onverwachte fout: {exc}"
            continue
        if uitkomst.geboekt and not uitkomst.boek_fout:
            resultaat.geboekt.append(k.document_id)
        elif uitkomst.geboekt:
            resultaat.geboekt.append(k.document_id)
            resultaat.mislukt[k.document_id] = uitkomst.boek_fout or "doorbelasting (deels) mislukt"
        else:
            resultaat.mislukt[k.document_id] = uitkomst.boek_fout or "boeken mislukt (zie tijdlijn)"
    return resultaat
