"""Vragenworkflow (CLAUDE.md domeinbeslissing, mockup #vragen + #vraagmodal): een vraag blokkeert
het boeken van het document (DocumentStatus.VRAAG_OPEN — boeken.py laat een boekpoging vanuit die
status niet toe), is toegewezen aan één medewerker (default: de administratie-eigenaar, mockup
Instellingen "Eigenaar (krijgt vragen)") en afhandelen of intrekken zet het document terug naar
exact de status van vóór de vraag (vraag.status_voor_vraag: te_controleren, handmatig_afmaken of
klaar_om_te_boeken), waarna de normale route naar boeken weer open is. Intrekken en stellen vanuit
klaar_om_te_boeken zijn bewuste uitbreidingen op de goedgekeurde mockup — zie docs/BESLISSINGEN.md.

DIALOOG (besluit Peter 25-08, RLZ-feedbackronde punt B, migratie 0064 — herziet het één-antwoord-
model van 14-07): een vraag is een thread. Iedereen binnen de scope kan een bericht plaatsen
(`plaats_bericht`, append-only in `vraag_bericht`); na elk bericht wisselt "aan de beurt" naar de
andere kant van de dialoog en Document.toegewezen_aan (de bestaande melding: werkvoorraad-kolom
"Toegewezen" + tellers) volgt mee. De vraag blijft het boeken blokkeren tot de OORSPRONKELIJKE
vraagsteller op "Afgehandeld" drukt (`handel_vraag_af`) — niet al bij het eerste antwoord. Enige
uitzondering: een automatische vraag van de systeem-actor (omzet-/verkoop-autovraag) heeft geen
menselijke vraagsteller; dan mag de toegewezene afhandelen, anders zou zo'n vraag nooit dicht
kunnen. Legacy-rijen met status 'beantwoord' blijven staan; hun oude antwoord verschijnt als
laatste bericht in de thread.

"Antwoord voedt het geheugen" loopt in v1 via de bestaande boek-leerlus (app/geheugen/leerlus.py):
het antwoord leidt tot een correctie in het boekvoorstel + boeken, en dát legt de gekozen GB/btw
als app-observatie vast — geen apart leer-pad hier. Een doorzoekbare Q&A-kennisbank per crediteur
is een genoteerde latere verrijking (docs/BESLISSINGEN.md).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerAdministratie, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import (
    Boekvoorstel,
    Document,
    DocumentGebeurtenis,
    DocumentStatus,
    Vraag,
    VraagBericht,
    VraagStatus,
)
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.sync.models import VendorCache

logger = logging.getLogger(__name__)


class VraagFout(Exception):
    """Basis voor domeinfouten in de vragenworkflow."""


class VraagTekstVerplicht(VraagFout):
    """Een vraag zonder tekst wordt geweigerd — zelfde principe als afwijzen-met-verplichte-reden."""


class AntwoordTekstVerplicht(VraagFout):
    """Een bericht zonder tekst wordt geweigerd."""


class AlleenVraagstellerMagAfhandelen(VraagFout):
    """ "Afgehandeld" is uitsluitend aan de oorspronkelijke vraagsteller (besluit Peter 25-08);
    bij een automatische vraag van de systeem-actor aan de toegewezene."""


class ErIsAlEenOpenVraag(VraagFout):
    """Eén open vraag per document tegelijk (ook op DB-niveau afgedwongen, migratie 0022)."""


class GeenToewijzingMogelijk(VraagFout):
    """Geen expliciete toewijzing én geen administratie-eigenaar — zichtbare fout, geen stille
    default of onbeheerde vraag."""


class ToegewezeneBuitenScope(VraagFout):
    """De beoogde toegewezene is geen actieve gebruiker met toegang tot deze administratie
    (Beheerder is platform-breed en telt altijd als binnen scope)."""


class VraagNietGevonden(VraagFout):
    pass


class VraagNietOpen(VraagFout):
    """De vraag is al afgehandeld of ingetrokken — alleen op een open vraag kan gereageerd,
    afgehandeld of ingetrokken worden."""


class VraagNietAanDezeAccordeur(VraagFout):
    """De accordeur-app ziet en beantwoordt UITSLUITEND vragen die expliciet aan de ingelogde
    accordeur gericht zijn (blok B5 26-08) — intern kantooroverleg lekt nooit."""


# De enige herkomsten waarvandaan een vraag gesteld kan worden: beantwoorden/intrekken moet de
# herkomst exact kunnen herstellen, dus élke toegestane herkomst heeft een vraag_open -> herkomst-
# overgang in de statusmachine. De statusmachine kent daarnaast extractie_bezig -> vraag_open
# (gereserveerd voor een extractie die zelf een vraag opwerpt, geen route hierlangs) — dat pad
# heeft geen herstel-overgang en wordt hier dus bewust geweigerd, fail-closed.
_HERSTELBARE_HERKOMSTEN = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
    }
)

# Blok B5 (26-08, migratie 0079): een vraag op een document dat bij de klant ligt of al geboekt
# is verandert de DOCUMENTSTATUS NIET — het akkoord in de app blijft mogelijk (een
# open vraag blokkeert het boeken, niet het akkoord: `accordering.service._rond_af_en_boek` zet
# het document ná het laatste akkoord zichtbaar op vraag_open i.p.v. te boeken). Afhandelen/
# intrekken herstelt dan ook niets: de status is nooit veranderd.
_HERKOMSTEN_ZONDER_OVERGANG = frozenset({DocumentStatus.TER_ACCORDERING, DocumentStatus.GEBOEKT})


@dataclass(frozen=True)
class BerichtData:
    """Eén bijdrage in de dialoog (detached)."""

    id: uuid.UUID
    auteur_id: uuid.UUID
    tekst: str
    geplaatst_op: datetime


@dataclass(frozen=True)
class VraagData:
    """Detached snapshot van een vraag-rij (de sessie sluit bij het verlaten van de service)."""

    id: uuid.UUID
    document_id: uuid.UUID
    document_bestandsnaam: str
    document_status: DocumentStatus
    # Totaalbedrag uit het boekvoorstel (mockup #vragen toont het bedrag per vraag) — None als
    # er (nog) geen boekvoorstel is.
    totaalbedrag: Decimal | None
    vraag_tekst: str
    status: str
    status_voor_vraag: str
    gesteld_door: uuid.UUID
    gesteld_op: datetime
    toegewezen_aan: uuid.UUID
    antwoord_tekst: str | None
    beantwoord_door: uuid.UUID | None
    beantwoord_op: datetime | None
    ingetrokken_door: uuid.UUID | None
    ingetrokken_op: datetime | None
    ingetrokken_reden: str | None
    # Dialoog (0064): wie aan zet is, afhandeling en de berichten in chronologische volgorde
    # (oudste eerst — de UI toont het nieuwste onderaan).
    aan_de_beurt: uuid.UUID
    afgehandeld_door: uuid.UUID | None
    afgehandeld_op: datetime | None
    berichten: tuple[BerichtData, ...]


def _aan_de_beurt(vraag: Vraag) -> uuid.UUID:
    """NULL op rijen van vóór migratie 0064 betekent: de toegewezene is aan zet."""
    return vraag.aan_de_beurt or vraag.toegewezen_aan


def _tijdlijn_zonder_overgang(session: Session, *, document: Document, actor_id: uuid.UUID, detail: dict) -> None:
    """Tijdlijnregel zonder statuswissel (herinnering-patroon): voor vragen op documenten die bij
    de klant liggen of al geboekt zijn — zichtbaar in de tijdlijn, status onaangeroerd."""
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail=detail,
        )
    )


def _is_klant_accordeur(session: Session, gebruiker_id: uuid.UUID | None) -> bool:
    if gebruiker_id is None:
        return False
    gebruiker = session.get(Gebruiker, gebruiker_id)
    return gebruiker is not None and gebruiker.rol == GebruikerRol.KLANT_ACCORDEUR


def _meld_accordeur_indien_nodig(vraag_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    """Ná stel_vraag/plaats_bericht (buiten de transactie): staat de beurt bij een klant-accordeur,
    dan meteen melden via de bestaande kanalen — behalve in de stille uren (dan vangt de
    10-min-job `rlz-nieuwe-facturen` 'm op). Nooit een fout richting de aanroeper."""
    try:
        from app.berichten import vraag_meldingen

        vraag_meldingen.verstuur_vraag_meldingen(vraag_id=vraag_id, administratie_id=administratie_id)
    except Exception:  # noqa: BLE001 — melding mag de dialoog nooit breken; job herkanst
        logger.exception("Melding aan accordeur voor vraag %s mislukte — job herkanst", vraag_id)


def _berichten_van(vraag: Vraag, berichten: list[VraagBericht]) -> tuple[BerichtData, ...]:
    """Berichten van deze vraag, chronologisch. Een legacy-antwoord ('beantwoord', vóór 0064)
    verschijnt als laatste bericht zodat de historie in één vorm leesbaar blijft."""
    lijst = [
        BerichtData(id=b.id, auteur_id=b.auteur_id, tekst=b.tekst, geplaatst_op=b.geplaatst_op)
        for b in sorted(berichten, key=lambda b: (b.geplaatst_op, b.id.hex))
    ]
    if (
        vraag.status == VraagStatus.BEANTWOORD.value
        and vraag.antwoord_tekst
        and vraag.beantwoord_door is not None
        and vraag.beantwoord_op is not None
    ):
        lijst.append(
            BerichtData(
                id=vraag.id,
                auteur_id=vraag.beantwoord_door,
                tekst=vraag.antwoord_tekst,
                geplaatst_op=vraag.beantwoord_op,
            )
        )
    return tuple(lijst)


def _naar_data(
    vraag: Vraag, document: Document, totaalbedrag: Decimal | None, berichten: list[VraagBericht] | None = None
) -> VraagData:
    return VraagData(
        id=vraag.id,
        document_id=vraag.document_id,
        document_bestandsnaam=document.bestandsnaam,
        document_status=document.status,
        totaalbedrag=totaalbedrag,
        vraag_tekst=vraag.vraag_tekst,
        status=vraag.status,
        status_voor_vraag=vraag.status_voor_vraag,
        gesteld_door=vraag.gesteld_door,
        gesteld_op=vraag.gesteld_op,
        toegewezen_aan=vraag.toegewezen_aan,
        antwoord_tekst=vraag.antwoord_tekst,
        beantwoord_door=vraag.beantwoord_door,
        beantwoord_op=vraag.beantwoord_op,
        ingetrokken_door=vraag.ingetrokken_door,
        ingetrokken_op=vraag.ingetrokken_op,
        ingetrokken_reden=vraag.ingetrokken_reden,
        aan_de_beurt=_aan_de_beurt(vraag),
        afgehandeld_door=vraag.afgehandeld_door,
        afgehandeld_op=vraag.afgehandeld_op,
        berichten=_berichten_van(vraag, berichten or []),
    )


def _berichten_per_vraag(session: Session, vraag_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[VraagBericht]]:
    per_vraag: dict[uuid.UUID, list[VraagBericht]] = {vid: [] for vid in vraag_ids}
    if not vraag_ids:
        return per_vraag
    for bericht in session.scalars(select(VraagBericht).where(VraagBericht.vraag_id.in_(vraag_ids))):
        per_vraag.setdefault(bericht.vraag_id, []).append(bericht)
    return per_vraag


def _controleer_toegewezene_scope(session: Session, *, gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    """Toewijzen kan alleen aan een actieve gebruiker mét toegang tot deze administratie
    (CLAUDE.md autorisatie: geen scope = geen data — een vraag toewijzen aan iemand die de
    administratie niet mag zien is per definitie fout). Beheerder is platform-breed, zelfde
    bypass als deps.vereis_administratie_scope. Geldt ook voor de default (de administratie-
    eigenaar): een eigenaar wiens scope later is ingetrokken geeft een zichtbare fout, geen
    stille toewijzing aan iemand die er niet meer bij kan."""
    gebruiker = session.get(Gebruiker, gebruiker_id)
    if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
        raise ToegewezeneBuitenScope(f"Toegewezene is geen actieve gebruiker: {gebruiker_id}")
    if gebruiker.rol == GebruikerRol.BEHEERDER:
        return
    if session.get(GebruikerAdministratie, (gebruiker_id, administratie_id)) is None:
        raise ToegewezeneBuitenScope("Toegewezene heeft geen toegang tot deze administratie")


def stel_vraag(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    vraag_tekst: str,
    toegewezen_aan: uuid.UUID | None = None,
) -> VraagData:
    """Stelt een vraag over een document: document -> vraag_open (statusmachine bepaalt vanuit
    welke statussen dat mag; boeken is vanuit vraag_open geblokkeerd), toewijzing default naar de
    administratie-eigenaar. Document.toegewezen_aan volgt mee (werkvoorraad-kolom "Toegewezen")."""
    tekst = vraag_tekst.strip()
    if not tekst:
        raise VraagTekstVerplicht("Een vraag zonder tekst is niet toegestaan")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        # Eerst de open-vraag-check: een tweede vraag op een vraag_open-document verdient de
        # specifieke melding, niet de generieke statusfout.
        open_vraag = session.scalars(
            select(Vraag).where(Vraag.document_id == document_id, Vraag.status == VraagStatus.OPEN.value)
        ).first()
        if open_vraag is not None:
            raise ErIsAlEenOpenVraag("Er staat al een open vraag op dit document")

        zonder_overgang = document.status in _HERKOMSTEN_ZONDER_OVERGANG
        if document.status not in _HERSTELBARE_HERKOMSTEN and not zonder_overgang:
            # Zelfde foutsoort als de statusmachine zelf zou geven — de extra poort hier dekt
            # uitsluitend herkomsten mét een toegestane heenweg maar zonder herstel-terugweg
            # (extractie_bezig), zodat een vraag nooit onbeantwoordbaar/onintrekbaar wordt.
            raise OngeldigeStatusovergang(f"Vanuit status {document.status.value} kan geen vraag gesteld worden")

        toegewezene = toegewezen_aan
        if toegewezene is None:
            administratie = session.get(Administratie, administratie_id)
            toegewezene = administratie.eigenaar_gebruiker_id if administratie else None
        if toegewezene is None:
            raise GeenToewijzingMogelijk(
                "Deze administratie heeft geen eigenaar — wijs de vraag expliciet toe of stel een eigenaar in"
            )
        _controleer_toegewezene_scope(session, gebruiker_id=toegewezene, administratie_id=administratie_id)

        vraag = Vraag(
            id=uuid.uuid4(),
            administratie_id=administratie_id,
            document_id=document_id,
            gesteld_door=actor_id,
            vraag_tekst=tekst,
            toegewezen_aan=toegewezene,
            aan_de_beurt=toegewezene,
            aan_de_beurt_sinds=datetime.now(UTC),
            status_voor_vraag=document.status.value,
        )
        session.add(vraag)
        overgang_detail = {
            "vraag_id": str(vraag.id),
            "toegewezen_aan": str(toegewezene),
            "status_voor_vraag": vraag.status_voor_vraag,
            # Vangnet 28-08: een automatische (systeem-)vraag draagt haar tekst als reden.
            "reden": f"vraag gesteld: {vraag_tekst.strip()[:160]}",
        }
        if zonder_overgang:
            # Blok B5: document blijft bij de klant / geboekt — alleen een tijdlijnregel.
            _tijdlijn_zonder_overgang(
                session, document=document, actor_id=actor_id, detail={**overgang_detail, "vraag_gesteld": True}
            )
        else:
            # De overgang valideert tegen de statusmachine vóór er iets persisteert — een vraag op
            # bv. een extractie_bezig-document rolt de hele transactie (incl. de vraag-rij) terug.
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.VRAAG_OPEN, actor_id=actor_id, detail=overgang_detail
            )
        document.toegewezen_aan = toegewezene
        session.flush()
        meld_accordeur = _is_klant_accordeur(session, toegewezene)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="vraag",
            record_id=vraag.id,
            actie="vraag_gesteld",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "document_id": str(document_id),
                "vraag_tekst": tekst,
                "toegewezen_aan": str(toegewezene),
            },
            administratie_id=administratie_id,
        )
        session.flush()
        data = _naar_data(vraag, document, _totaalbedrag_van(session, document.id))
    if meld_accordeur:
        _meld_accordeur_indien_nodig(data.id, administratie_id)
    return data


def _totaalbedrag_van(session, document_id: uuid.UUID) -> Decimal | None:
    return session.scalar(select(Boekvoorstel.totaalbedrag).where(Boekvoorstel.document_id == document_id))


def _open_vraag_met_document(session, *, administratie_id: uuid.UUID, vraag_id: uuid.UUID) -> tuple[Vraag, Document]:
    """Gedeelde poort van beantwoorden en intrekken: de vraag moet bestaan, van deze
    administratie zijn en nog open staan."""
    vraag = session.get(Vraag, vraag_id)
    if vraag is None or vraag.administratie_id != administratie_id:
        raise VraagNietGevonden(f"Onbekende vraag: {vraag_id}")
    if vraag.status != VraagStatus.OPEN.value:
        raise VraagNietOpen(f"Deze vraag is al {vraag.status}")
    document = session.get(Document, vraag.document_id)
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {vraag.document_id}")
    return vraag, document


def plaats_bericht(*, administratie_id: uuid.UUID, vraag_id: uuid.UUID, actor_id: uuid.UUID, tekst: str) -> VraagData:
    """Plaatst een bijdrage in de dialoog (append-only rij in vraag_bericht). De vraag blijft OPEN
    en het document blijft geblokkeerd — alleen `handel_vraag_af` sluit de thread. Na het bericht
    wisselt "aan de beurt": schrijft de vraagsteller, dan is de toegewezene aan zet; schrijft
    iemand anders (de toegewezene of een collega die namens hem antwoordt), dan de vraagsteller.
    Document.toegewezen_aan volgt mee — dat ís de bestaande melding (werkvoorraad-kolom
    "Toegewezen" + vragen-teller). Bij een systeem-vraag (geen menselijke vraagsteller) blijft
    de toegewezene aan zet."""
    inhoud = tekst.strip()
    if not inhoud:
        raise AntwoordTekstVerplicht("Een bericht zonder tekst is niet toegestaan")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        vraag, document = _open_vraag_met_document(session, administratie_id=administratie_id, vraag_id=vraag_id)
        bericht = VraagBericht(
            id=uuid.uuid4(),
            administratie_id=administratie_id,
            vraag_id=vraag.id,
            auteur_id=actor_id,
            tekst=inhoud,
            geplaatst_op=datetime.now(UTC),
        )
        session.add(bericht)

        vorige_beurt = _aan_de_beurt(vraag)
        # Systeem-vraag (geen menselijke vraagsteller) of de vraagsteller zelf schrijft → de
        # toegewezene is aan zet; ieder ander (toegewezene of collega namens hem) → de vraagsteller.
        if vraag.gesteld_door == SYSTEEM_ACTOR_ID or actor_id == vraag.gesteld_door:
            nieuwe_beurt = vraag.toegewezen_aan
        else:
            nieuwe_beurt = vraag.gesteld_door
        vraag.aan_de_beurt = nieuwe_beurt
        if nieuwe_beurt != vorige_beurt:
            vraag.aan_de_beurt_sinds = datetime.now(UTC)
        document.toegewezen_aan = nieuwe_beurt
        session.flush()
        meld_accordeur = nieuwe_beurt != vorige_beurt and _is_klant_accordeur(session, nieuwe_beurt)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="vraag_bericht",
            record_id=bericht.id,
            actie="vraag_bericht_geplaatst",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"aan_de_beurt": str(vorige_beurt)},
            nieuwe_waarde={
                "vraag_id": str(vraag.id),
                "document_id": str(document.id),
                "tekst": inhoud,
                "aan_de_beurt": str(nieuwe_beurt),
            },
            administratie_id=administratie_id,
        )
        session.flush()
        berichten = _berichten_per_vraag(session, [vraag.id])[vraag.id]
        data = _naar_data(vraag, document, _totaalbedrag_van(session, document.id), berichten)
    if meld_accordeur:
        _meld_accordeur_indien_nodig(data.id, administratie_id)
    return data


def plaats_bericht_als_accordeur(
    *, administratie_id: uuid.UUID, vraag_id: uuid.UUID, actor_id: uuid.UUID, tekst: str
) -> VraagData:
    """Accordeur-app (blok B5): antwoorden mag uitsluitend op een vraag die aan déze accordeur
    gericht is — elke andere vraag is voor de app onbestaand (VraagNietAanDezeAccordeur → 404,
    nooit een 403 dat het bestaan verraadt). Daarna het gewone append-only pad."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        vraag = session.get(Vraag, vraag_id)
        if vraag is None or vraag.administratie_id != administratie_id or vraag.toegewezen_aan != actor_id:
            raise VraagNietAanDezeAccordeur(f"Onbekende vraag: {vraag_id}")
    return plaats_bericht(administratie_id=administratie_id, vraag_id=vraag_id, actor_id=actor_id, tekst=tekst)


def _herstel_document_na_sluiten(
    session: Session, *, vraag: Vraag, document: Document, actor_id: uuid.UUID, detail: dict
) -> None:
    """Afhandelen/intrekken: herstel de herkomst-status — behalve als de vraag zónder overgang
    gesteld was (document bij de klant/geboekt) of het document intussen zelf al verder is
    (ná het laatste akkoord zette de boek-poort 'm op vraag_open met herkomst klaar_om_te_boeken:
    dan wél herstellen). Regel: alleen een document dat NU op vraag_open staat wordt hersteld."""
    if document.status == DocumentStatus.VRAAG_OPEN:
        _schrijf_overgang(
            session, document=document, naar=DocumentStatus(vraag.status_voor_vraag), actor_id=actor_id, detail=detail
        )
    else:
        _tijdlijn_zonder_overgang(session, document=document, actor_id=actor_id, detail=detail)


def mag_afhandelen(vraag_gesteld_door: uuid.UUID, vraag_toegewezen_aan: uuid.UUID, actor_id: uuid.UUID) -> bool:
    """De ene bron voor de "Afgehandeld"-poort (server én UI-hint): uitsluitend de oorspronkelijke
    vraagsteller; bij een automatische vraag van de systeem-actor de toegewezene."""
    if vraag_gesteld_door == SYSTEEM_ACTOR_ID:
        return actor_id == vraag_toegewezen_aan
    return actor_id == vraag_gesteld_door


def handel_vraag_af(
    *, administratie_id: uuid.UUID, vraag_id: uuid.UUID, actor_id: uuid.UUID, slotbericht: str | None = None
) -> VraagData:
    """Sluit de dialoog (status open -> afgehandeld, nooit een delete) en zet het document terug
    naar exact de herkomst-status van vóór de vraag (vraag.status_voor_vraag) — boeken is daarna
    weer bereikbaar via de normale route. UITSLUITEND de oorspronkelijke vraagsteller (besluit
    Peter 25-08; systeem-vraag: de toegewezene). Optioneel slotbericht gaat als gewone bijdrage
    de thread in. "De uitkomst voedt het boekingsgeheugen zoals nu" = via de boek-leerlus, geen
    apart pad hier. Document.toegewezen_aan gaat terug naar leeg."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        vraag, document = _open_vraag_met_document(session, administratie_id=administratie_id, vraag_id=vraag_id)
        if not mag_afhandelen(vraag.gesteld_door, vraag.toegewezen_aan, actor_id):
            raise AlleenVraagstellerMagAfhandelen("Alleen de vraagsteller kan deze vraag als afgehandeld markeren")

        slot = slotbericht.strip() if slotbericht and slotbericht.strip() else None
        if slot:
            session.add(
                VraagBericht(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vraag_id=vraag.id,
                    auteur_id=actor_id,
                    tekst=slot,
                    geplaatst_op=datetime.now(UTC),
                )
            )
        vraag.status = VraagStatus.AFGEHANDELD.value
        vraag.afgehandeld_door = actor_id
        vraag.afgehandeld_op = datetime.now(UTC)
        vraag.aan_de_beurt = actor_id
        _herstel_document_na_sluiten(
            session,
            vraag=vraag,
            document=document,
            actor_id=actor_id,
            detail={"vraag_id": str(vraag.id), "vraag_afgehandeld": True},
        )
        document.toegewezen_aan = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="vraag",
            record_id=vraag.id,
            actie="vraag_afgehandeld",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": VraagStatus.OPEN.value},
            nieuwe_waarde={
                "status": VraagStatus.AFGEHANDELD.value,
                "afgehandeld_door": str(actor_id),
                "slotbericht": slot,
                "document_hersteld_naar": vraag.status_voor_vraag,
            },
            administratie_id=administratie_id,
        )
        session.flush()
        berichten = _berichten_per_vraag(session, [vraag.id])[vraag.id]
        return _naar_data(vraag, document, _totaalbedrag_van(session, document.id), berichten)


def open_vraag_ids_van_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[uuid.UUID]:
    """Alle OPEN vragen op een document (de één-open-vraag-regel geldt per document, maar de lezer blijft
    een lijst — fail-safe als die regel ooit versoepelt)."""
    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(Vraag.id).where(
                    Vraag.administratie_id == administratie_id,
                    Vraag.document_id == document_id,
                    Vraag.status == VraagStatus.OPEN.value,
                )
            ).all()
        )


def sluit_vraag_wegens_duplicaat(
    *, administratie_id: uuid.UUID, vraag_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> VraagData:
    """Blok A2 04-09 (besluit Peter "geen dubbeling"): het document waarop deze vraag staat wordt als duplicaat
    afgevoerd — de vraag gaat zichtbaar DICHT (status ingetrokken mét reden), én de reden staat als slotbericht
    in de thread zodat de vraagsteller het ziet (append-only `vraag_bericht`, auteur = de afvoerende actor —
    systeem óf mens). Géén "aan de beurt"-wissel en géén accordeur-push: er is niets meer te beantwoorden.
    Document op vraag_open keert terug naar zijn herkomst-status (daarna volgt de afwijzing)."""
    tekst = reden.strip()
    if not tekst:
        raise AntwoordTekstVerplicht("Een sluitreden zonder tekst is niet toegestaan")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        vraag, document = _open_vraag_met_document(session, administratie_id=administratie_id, vraag_id=vraag_id)
        nu = datetime.now(UTC)
        session.add(
            VraagBericht(
                id=uuid.uuid4(),
                administratie_id=administratie_id,
                vraag_id=vraag.id,
                auteur_id=actor_id,
                tekst=f"Vraag gesloten: document {tekst}.",
                geplaatst_op=nu,
            )
        )
        vraag.status = VraagStatus.INGETROKKEN.value
        vraag.ingetrokken_door = actor_id
        vraag.ingetrokken_op = nu
        vraag.ingetrokken_reden = tekst
        _herstel_document_na_sluiten(
            session,
            vraag=vraag,
            document=document,
            actor_id=actor_id,
            detail={
                "vraag_id": str(vraag.id),
                "vraag_ingetrokken": True,
                "vraag_gesloten_wegens_duplicaat": True,
                "reden": tekst,
            },
        )
        document.toegewezen_aan = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="vraag",
            record_id=vraag.id,
            actie="vraag_gesloten_wegens_duplicaat",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": VraagStatus.OPEN.value},
            nieuwe_waarde={
                "status": VraagStatus.INGETROKKEN.value,
                "reden": tekst,
                "ingetrokken_door": str(actor_id),
                "document_hersteld_naar": vraag.status_voor_vraag,
            },
            administratie_id=administratie_id,
        )
        session.flush()
        berichten = _berichten_per_vraag(session, [vraag.id])[vraag.id]
        return _naar_data(vraag, document, _totaalbedrag_van(session, document.id), berichten)


def trek_vraag_in(
    *, administratie_id: uuid.UUID, vraag_id: uuid.UUID, actor_id: uuid.UUID, reden: str | None = None
) -> VraagData:
    """Trekt een open vraag in (status open -> ingetrokken, nooit een delete) en zet het document
    terug naar de herkomst-status — bewuste uitbreiding op de mockup (docs/BESLISSINGEN.md):
    zonder intrekken dwingt een per ongeluk gestelde vraag een pro-forma nep-antwoord af, dat
    daarna als échte kennis in de historie zou staan. Reden optioneel, maar altijd in het
    audit_event (ook als None — zelfde patroon als verwijderen). De één-open-vraag-regel blijft:
    na intrekken kan er gewoon weer een nieuwe vraag gesteld worden."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        vraag, document = _open_vraag_met_document(session, administratie_id=administratie_id, vraag_id=vraag_id)

        vraag.status = VraagStatus.INGETROKKEN.value
        vraag.ingetrokken_door = actor_id
        vraag.ingetrokken_op = datetime.now(UTC)
        vraag.ingetrokken_reden = reden.strip() if reden and reden.strip() else None
        _herstel_document_na_sluiten(
            session,
            vraag=vraag,
            document=document,
            actor_id=actor_id,
            detail={"vraag_id": str(vraag.id), "vraag_ingetrokken": True, "reden": vraag.ingetrokken_reden},
        )
        document.toegewezen_aan = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="vraag",
            record_id=vraag.id,
            actie="vraag_ingetrokken",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": VraagStatus.OPEN.value},
            nieuwe_waarde={
                "status": VraagStatus.INGETROKKEN.value,
                "reden": vraag.ingetrokken_reden,
                "ingetrokken_door": str(actor_id),
                "document_hersteld_naar": vraag.status_voor_vraag,
            },
            administratie_id=administratie_id,
        )
        session.flush()
        berichten = _berichten_per_vraag(session, [vraag.id])[vraag.id]
        return _naar_data(vraag, document, _totaalbedrag_van(session, document.id), berichten)


def lijst_vragen(
    *,
    administratie_id: uuid.UUID,
    status: VraagStatus | None = None,
    document_id: uuid.UUID | None = None,
) -> list[VraagData]:
    """Vragen van één administratie, nieuwste eerst (voedt de #vragen-view en de vraag-weergave
    in het controlescherm; PART B). Optioneel gefilterd op status en/of document."""
    with scoped_session(administratie_id) as session:
        query = (
            select(Vraag, Document, Boekvoorstel.totaalbedrag)
            .join(Document, Vraag.document_id == Document.id)
            .outerjoin(Boekvoorstel, Boekvoorstel.document_id == Document.id)
            .where(Vraag.administratie_id == administratie_id)
        )
        if status is not None:
            query = query.where(Vraag.status == status.value)
        if document_id is not None:
            query = query.where(Vraag.document_id == document_id)
        query = query.order_by(Vraag.gesteld_op.desc())
        rijen = list(session.execute(query))
        berichten = _berichten_per_vraag(session, [vraag.id for vraag, _document, _bedrag in rijen])
        return [
            _naar_data(vraag, document, totaalbedrag, berichten.get(vraag.id, []))
            for vraag, document, totaalbedrag in rijen
        ]


@dataclass(frozen=True)
class AccordeurVraag:
    """Vraag zoals de accordeur-app 'm ziet (blok B5): de thread + documentcontext (leverancier,
    bedrag, administratie, status) — uitsluitend vragen die aan déze accordeur gericht zijn."""

    vraag: VraagData
    administratie_id: uuid.UUID
    administratie_naam: str | None
    leverancier_naam: str | None
    ik_ben_aan_de_beurt: bool


def vragen_aan_accordeur(*, actor_id: uuid.UUID, administratie_ids: list[uuid.UUID]) -> list[AccordeurVraag]:
    """Alle OPEN vragen die expliciet aan deze accordeur zijn toegewezen, over zijn administraties
    (scope-bron van de aanroeper; RLS dwingt het nogmaals af). Intern kantooroverleg (vragen aan
    kantoormedewerkers) komt hier per definitie nooit uit — de filter is `toegewezen_aan == actor`."""
    uit: list[AccordeurVraag] = []
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            administratie = session.get(Administratie, administratie_id)
            rijen = list(
                session.execute(
                    select(Vraag, Document, Boekvoorstel)
                    .join(Document, Vraag.document_id == Document.id)
                    .outerjoin(Boekvoorstel, Boekvoorstel.document_id == Document.id)
                    .where(
                        Vraag.administratie_id == administratie_id,
                        Vraag.status == VraagStatus.OPEN.value,
                        Vraag.toegewezen_aan == actor_id,
                    )
                    .order_by(Vraag.gesteld_op.desc())
                )
            )
            berichten = _berichten_per_vraag(session, [v.id for v, _d, _b in rijen])
            for vraag, document, voorstel in rijen:
                leverancier = None
                if voorstel is not None and voorstel.vendor_id is not None:
                    vendor = session.get(VendorCache, (voorstel.vendor_id, administratie_id))
                    leverancier = vendor.naam if vendor else None
                uit.append(
                    AccordeurVraag(
                        vraag=_naar_data(
                            vraag, document, voorstel.totaalbedrag if voorstel else None, berichten.get(vraag.id, [])
                        ),
                        administratie_id=administratie_id,
                        administratie_naam=administratie.naam if administratie else None,
                        leverancier_naam=leverancier,
                        ik_ben_aan_de_beurt=_aan_de_beurt(vraag) == actor_id,
                    )
                )
    uit.sort(key=lambda a: a.vraag.gesteld_op, reverse=True)
    return uit


def open_vraag_aan_accordeur_op_document(
    session: Session, *, document_id: uuid.UUID, actor_id: uuid.UUID
) -> VraagData | None:
    """Voor de wachtrij-kaart (blok B5): de open vraag op dít document, alleen als die aan deze
    accordeur gericht is. Sessie van de aanroeper (al gescoopt op de administratie)."""
    vraag = session.scalars(
        select(Vraag).where(
            Vraag.document_id == document_id,
            Vraag.status == VraagStatus.OPEN.value,
            Vraag.toegewezen_aan == actor_id,
        )
    ).first()
    if vraag is None:
        return None
    document = session.get(Document, document_id)
    berichten = _berichten_per_vraag(session, [vraag.id])[vraag.id]
    return _naar_data(vraag, document, _totaalbedrag_van(session, document_id), berichten)
