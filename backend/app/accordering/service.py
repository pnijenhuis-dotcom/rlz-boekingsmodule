"""Klant-accorderingsflow — geldlogica (mockup #autorisatie; BESLISSINGEN "Mobiele bouwstenen
accordeur-PWA" punten 1/5/6; migratie 0033).

Flow: kantoor biedt een boekklaar document "ter accordering" aan → stappen worden bevroren uit
de actieve lagen (bedragdrempel geëvalueerd op het totaalbedrag; onbekend bedrag = laag
vereist, fail-closed) → accordeurs besluiten SEQUENTIEEL (laag n pas na laag n-1) → na het
laatste akkoord draait de flow de bestaande boekmotor MET ALLE HARDE CHECKS opnieuw (CLAUDE.md,
hard — een akkoord is nooit een bypass). Het document BLIJFT daarbij op ter_accordering tot de
boeking écht staat (bugfix-run 28-08): faalt het boeken (poort, toggle, volumerem, checks,
RLZ-fout), dan is dat een zichtbare `boek_fout` op de ronde + een reden op de tijdlijn — nooit
een stille terugval naar klaar_om_te_boeken. Zie `_rond_af_en_boek` / `_boek_na_laatste_akkoord`.

Staande goedkeuring (besluit Peter 2026-08-08): een accordeur kan bij zijn akkoord "voortaan
automatisch bij exact dit bedrag" vastleggen — per accordeur + leverancier (vendor_id) + exact
bedrag. Bij het aanbieden van een volgend document wordt de regel toegepast als automatisch
akkoord in de betreffende laag, mét audit-spoor + tijdlijn-vermelding; afwijkend bedrag =
gewoon ter accordering; de regel is zichtbaar + intrekbaar en gaat NOOIT over de harde checks
heen (die draaien bij het boeken).

Afwijzen door de accordeur = verplichte reden en hergebruikt het bestaande
afwijzen-met-reden-patroon (app/documenten/afwijzen.py): het document gaat eerst zichtbaar
terug naar klaar_om_te_boeken ("terug uit accordering") en wordt dan afgewezen — heropenen
brengt het gewoon terug in de kantoorbak.

Autorisatie: alle leesroutes zijn scope-gecontroleerd (RLS + dependency); accordeur-besluiten
worden bovendien hard op de stap-eigenaar getoetst (alleen de accordeur van de eerstvolgende
open vereiste stap), kantoor-acties (aanbieden/intrekken/instellingen) weigeren de rol
klant-accordeur."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accordering import herberekening as herberekening_module
from app.accordering.models import (
    AccorderingLaag,
    AccorderingStap,
    AccorderingStatus,
    DocumentAccordering,
    StaandeGoedkeuring,
    StaandeGoedkeuringVoorstelStil,
    StapBesluit,
    StapBesluitBron,
    VoorstelStilSoort,
)
from app.afdelingen.models import Afdeling
from app.auth.rollen import is_externe_app_rol
from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import afwijzen as afwijzen_service
from app.documenten import boeken as boeken_service
from app.documenten.models import (
    Boekvoorstel,
    Document,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
    Vraag,
    VraagStatus,
)
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang
from app.documenten.vragen import open_vragen_aan_accordeur_per_document
from app.doorbelasting.intercompany import OVERGESLAGEN_REDEN_INTERCOMPANY, intercompany_tegenpartij
from app.sync.models import VendorCache
from app.terugkerend import service as _terugkerend
from app.terugkerend.service import ReeksClassificatie, classificeer_reeks, gelijke_facturen_per_vendor_bedrag
from app.tijd import vandaag_nl

logger = logging.getLogger(__name__)


class AccorderingFout(Exception):
    """Basis voor domeinfouten in de accorderingsflow."""


class AccorderingUitgeschakeld(AccorderingFout):
    pass


class GeenLagenIngesteld(AccorderingFout):
    pass


class OngeldigeAanbieding(AccorderingFout):
    pass


class DocumentNietAanbiedbaar(OngeldigeAanbieding):
    """Statuspoort (aanvulling blok 3, 08-09): het document staat niet op klaar_om_te_boeken — bv. een
    `samengevoegd`-huls of een afgevoerd duplicaat. Conflict met de actuele stand (409, zoals de boek-route
    met `OngeldigeBoekpoging`), geen invoerfout (400)."""


class KlantAkkoordAlCompleet(OngeldigeAanbieding):
    """Punt 24 (opruimrun 28-08): de LAATSTE ronde is al afgerond (alle lagen akkoord), het bedrag
    is ongewijzigd en het document is daarna nog niet geboekt — opnieuw aanbieden zou de klant
    een tweede keer om hetzelfde akkoord vragen (casus 28-08: bulk-route omzeilde de
    BoekvoorstelPanel-guard). De juiste actie is BOEKEN (de accorderingspoort staat open)."""


class NietAanDeBeurt(AccorderingFout):
    """De actor is niet de accordeur van de eerstvolgende open vereiste stap."""


class RedenVerplicht(AccorderingFout):
    pass


class GeenOpenAccordering(AccorderingFout):
    pass


class StaandeRegelNietMogelijk(AccorderingFout):
    """Zonder leverancier (vendor_id) of totaalbedrag valt er geen exacte regel vast te leggen."""


class KantoorActieVereist(AccorderingFout):
    """Aanbieden/intrekken/instellingen zijn kantoor-acties — niet voor de rol klant-accordeur."""


class VoorstelUitzonderingFout(AccorderingFout):
    """Onbekende of al opgeheven voorstel-uitzondering, of een accordeur die aan een ander zit."""


#: "Nee"/"niet nu" op het staande-goedkeuring-voorstel = zoveel dagen stil voor deze accordeur + leverancier
#: (blok 7 run 11-09 middag).
VOORSTEL_STIL_DAGEN = 90
VOORSTEL_ANTWOORDEN = ("ja", "niet_nu", "nooit")
# Leesbare drempels voor de nameting-CLI (één bron: app/terugkerend/service.py).
PERIODIEK_MIN_FACTUREN_TEKST = str(_terugkerend.PERIODIEK_MIN_FACTUREN)
PERIODIEK_MIN_TUSSENPOOS_TEKST = str(_terugkerend.PERIODIEK_MIN_TUSSENPOOS_DAGEN)
BATCH_VENSTER_TEKST = str(_terugkerend.BATCH_VENSTER_DAGEN)


class ChecksNietGroen(AccorderingFout):
    """Aanbieden vanaf te_controleren/handmatig_afmaken vereist dezelfde groene harde checks als
    boeken — een document met blokkerende checks gaat nooit naar de klant."""

    def __init__(self, rapport) -> None:
        self.rapport = rapport
        super().__init__("Ter accordering geblokkeerd door harde checks")


@dataclass(frozen=True)
class StapData:
    id: uuid.UUID
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str | None
    bedrag_drempel: Decimal | None
    vereist: bool
    besluit: str | None
    besluit_bron: str | None
    reden: str | None
    besloten_op: datetime | None
    aan_de_beurt: bool


@dataclass(frozen=True)
class AccorderingData:
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    aangeboden_op: datetime
    afgerond_op: datetime | None
    stappen: list[StapData]
    # Bugfix-run 28-08: de laatste boekfout ná het laatste akkoord (persistent op de ronde —
    # `detail["boek_fout"]`), zichtbaar op het controlescherm + in de documentenlijst. None = geen.
    boek_fout: str | None = None
    boek_fout_op: datetime | None = None
    # Blok 4 (08-09): status "overgeslagen" — geen ronde, de klant-accordering is voor dit document overgeslagen
    # op de leveranciersregel (`reden` = "intercompany"); `stappen` is dan leeg en er zijn geen acties.
    overgeslagen_reden: str | None = None
    overgeslagen_leverancier_naam: str | None = None


@dataclass(frozen=True)
class AkkoordResultaat:
    # None uitsluitend bij een overgeslagen accordering (blok 4, 08-09): er is dan geen ronde — het document is
    # direct via de bestaande boekstap gegaan (`geboekt`/`boek_fout` dragen de uitkomst).
    accordering: AccorderingData | None
    alles_akkoord: bool
    geboekt: bool
    boek_fout: str | None
    staande_regel_id: uuid.UUID | None
    overgeslagen_reden: str | None = None


def _gebruikersnamen_publiek(ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Namen voor een lijst gebruiker-id's zonder administratie-scope (platform.gebruiker is niet
    RLS-gescoped op administratie) — voor de vervallen-melding."""
    if not ids:
        return {}
    with scoped_session(None) as session:
        return _gebruikersnamen(session, ids)


def _gebruikersnamen(session: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rijen = session.scalars(select(Gebruiker).where(Gebruiker.id.in_(ids))).all()
    return {g.id: g.naam for g in rijen}


def _eerstvolgende_open_stap(stappen: list[AccorderingStap]) -> AccorderingStap | None:
    for stap in sorted(stappen, key=lambda s: s.volgnummer):
        if stap.vereist and stap.besluit is None:
            return stap
    return None


def _boek_fout_van(accordering: DocumentAccordering) -> tuple[str | None, datetime | None]:
    """De persistente boekfout op de ronde (`detail["boek_fout"] = {fout, tijdstip, geboekt}`)."""
    boek_fout = (accordering.detail or {}).get("boek_fout")
    if not isinstance(boek_fout, dict) or not boek_fout.get("fout"):
        return None, None
    tijdstip: datetime | None = None
    if isinstance(boek_fout.get("tijdstip"), str):
        try:
            tijdstip = datetime.fromisoformat(boek_fout["tijdstip"])
        except ValueError:  # pragma: no cover — defensief
            tijdstip = None
    return str(boek_fout["fout"]), tijdstip


def _naar_data(session: Session, accordering: DocumentAccordering, stappen: list[AccorderingStap]) -> AccorderingData:
    namen = _gebruikersnamen(session, {s.accordeur_gebruiker_id for s in stappen})
    volgende = _eerstvolgende_open_stap(stappen) if accordering.status == AccorderingStatus.OPEN.value else None
    boek_fout, boek_fout_op = _boek_fout_van(accordering)
    return AccorderingData(
        id=accordering.id,
        document_id=accordering.document_id,
        status=accordering.status,
        aangeboden_op=accordering.aangeboden_op,
        afgerond_op=accordering.afgerond_op,
        boek_fout=boek_fout,
        boek_fout_op=boek_fout_op,
        stappen=[
            StapData(
                id=s.id,
                volgnummer=s.volgnummer,
                accordeur_gebruiker_id=s.accordeur_gebruiker_id,
                accordeur_naam=namen.get(s.accordeur_gebruiker_id),
                bedrag_drempel=s.bedrag_drempel,
                vereist=s.vereist,
                besluit=s.besluit,
                besluit_bron=s.besluit_bron,
                reden=s.reden,
                besloten_op=s.besloten_op,
                aan_de_beurt=volgende is not None and s.id == volgende.id,
            )
            for s in sorted(stappen, key=lambda s: s.volgnummer)
        ],
    )


def _stappen_van(session: Session, accordering_id: uuid.UUID) -> list[AccorderingStap]:
    """De stappen van een ronde — zonder de bij een herberekening vervallen stappen (bundel 09-09 blok 2): die
    rijen blijven als historie staan (audit draagt de volledige oude stand) maar zijn geen deel van de ronde meer."""
    return list(
        session.scalars(
            select(AccorderingStap).where(
                AccorderingStap.accordering_id == accordering_id,
                AccorderingStap.besluit.is_distinct_from(StapBesluit.VERVALLEN.value),
            )
        )
    )


def _open_accordering(session: Session, document_id: uuid.UUID) -> DocumentAccordering | None:
    return session.scalars(
        select(DocumentAccordering).where(
            DocumentAccordering.document_id == document_id,
            DocumentAccordering.status == AccorderingStatus.OPEN.value,
        )
    ).first()


@dataclass(frozen=True)
class OvergeslagenAccordering:
    """Blok 4 (08-09): waarom de klant-accordering voor dit document niet nodig is — nu alleen de
    intercompany-leveranciersregel (`reden` = OVERGESLAGEN_REDEN_INTERCOMPANY)."""

    reden: str
    vendor_id: uuid.UUID
    leverancier_naam: str


def accordering_overgeslagen(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID
) -> OvergeslagenAccordering | None:
    """Puur lezen: heeft dit document een leverancier met IC-vlag in de ADMINISTRATIE VAN HET DOCUMENT
    (`intercompany_tegenpartij`, app/doorbelasting/intercompany.py)? Dan wordt de stap "ter accordering"
    overgeslagen — de rest van de flow (extractie, checks, boeken/autoboek) is ongewijzigd. Géén leverancier op het
    voorstel, geen rij of een inactieve rij = None = gewone flow (kernprincipe 7: lege IC-tabel = niets bijzonders).
    Toetst NIET of accordering aanstaat — dat doet de aanroeper (zonder accordering is er niets over te slaan)."""
    voorstel = session.get(Boekvoorstel, document_id)
    if voorstel is None or voorstel.vendor_id is None:
        return None
    rij = intercompany_tegenpartij(session, administratie_id=administratie_id, vendor_id=voorstel.vendor_id)
    if rij is None:
        return None
    return OvergeslagenAccordering(
        reden=OVERGESLAGEN_REDEN_INTERCOMPANY, vendor_id=voorstel.vendor_id, leverancier_naam=rij.naam
    )


def accordering_overgeslagen_reden_voor_dto(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> str | None:
    """Additief DTO-veld `accordering_overgeslagen_reden` op het boekvoorstel (kantoor-frontend: knop "Boeken" i.p.v.
    "Ter accordering"): alleen gevuld als accordering aanstaat én de leveranciersregel geldt, anders None."""
    if not is_accordering_ingeschakeld(administratie_id=administratie_id):
        return None
    with scoped_session(administratie_id) as session:
        overgeslagen = accordering_overgeslagen(session, administratie_id=administratie_id, document_id=document_id)
    return overgeslagen.reden if overgeslagen is not None else None


OVERGESLAGEN_TIJDLIJN_SLEUTEL = "accordering_overgeslagen"
OVERGESLAGEN_AUDIT_ACTIE = "accordering_overgeslagen_intercompany"


def registreer_accordering_overgeslagen(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> bool:
    """Tijdlijnregel (status blijft) + audit-event "intercompany — klant-accordering overgeslagen (leveranciersregel)"
    mét vendor-id/naam. Aangeroepen door de boekmotor zodra de accorderingspoort op de leveranciersregel openging
    (app/documenten/boeken.py) — dus op het autoboek-pad én het handmatige boek-pad. Idempotent per boek-cyclus (een
    herboeking ná tegenboeken krijgt een nieuwe regel, een retry na boekfout niet). False = niets geschreven: geen
    IC-leverancier, of de laatste ronde is écht afgerond (dan is er niets overgeslagen)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            return False
        overgeslagen = accordering_overgeslagen(session, administratie_id=administratie_id, document_id=document_id)
        if overgeslagen is None:
            return False
        laatste = _laatste_accordering(session, document_id)
        if laatste is not None and laatste.status == AccorderingStatus.AFGEROND.value:
            return False
        voorstel = session.get(Boekvoorstel, document_id)
        boek_cyclus = int(voorstel.boek_cyclus) if voorstel is not None else 0
        al_geschreven = session.scalar(
            select(func.count())
            .select_from(DocumentGebeurtenis)
            .where(
                DocumentGebeurtenis.document_id == document_id,
                DocumentGebeurtenis.detail[OVERGESLAGEN_TIJDLIJN_SLEUTEL]["boek_cyclus"].as_integer() == boek_cyclus,
            )
        )
        if al_geschreven:
            return False
        detail = {
            "reden": overgeslagen.reden,
            "vendor_id": str(overgeslagen.vendor_id),
            "leverancier_naam": overgeslagen.leverancier_naam,
            "boek_cyclus": boek_cyclus,
            "tekst": "intercompany — klant-accordering overgeslagen (leveranciersregel)",
        }
        session.add(
            DocumentGebeurtenis(
                document_id=document_id,
                van_status=document.status,
                naar_status=document.status,
                actor_id=actor_id,
                detail={OVERGESLAGEN_TIJDLIJN_SLEUTEL: detail},
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie=OVERGESLAGEN_AUDIT_ACTIE,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"document_id": str(document_id), **detail},
            administratie_id=administratie_id,
        )
    return True


def _overgeslagen_tijdstip(session: Session, document_id: uuid.UUID) -> datetime | None:
    return session.scalar(
        select(func.min(DocumentGebeurtenis.tijdstip)).where(
            DocumentGebeurtenis.document_id == document_id,
            DocumentGebeurtenis.detail.has_key(OVERGESLAGEN_TIJDLIJN_SLEUTEL),
        )
    )


def accordering_blokkade_voor_boeken(session: Session, *, document_id: uuid.UUID) -> str | None:
    """Poort voor de boekmotor bij accordering-aan (app/documenten/boeken.py — nooit de client
    vertrouwen): None = boeken mag, anders de leesbare reden waarom niet. Sinds de bugfix-run
    28-08 telt uitsluitend de LAATSTE ronde (een oudere afgeronde ronde naast een nieuwe open
    ronde was een bypass) én moet het totaalbedrag van het voorstel nog gelijk zijn aan het
    bedrag waarop de klant akkoord gaf (aangrenzend gat: voorstel wijzigen ná akkoord).

    Blok 4 (08-09, besluit Peter): een document van een leverancier met IC-vlag in déze administratie heeft
    geen klant-accordering nodig — de poort staat open zonder ronde. Uitzondering: loopt er op dit moment tóch
    een OPEN ronde (IC-rij ná het aanbieden ontstaan), dan blijft die zichtbaar leidend (niets verdwijnt stil;
    het kantoor kan 'm terughalen)."""
    laatste = _laatste_accordering(session, document_id)
    document = session.get(Document, document_id)
    if (
        document is not None
        and document.administratie_id is not None
        and (laatste is None or laatste.status != AccorderingStatus.OPEN.value)
        and accordering_overgeslagen(session, administratie_id=document.administratie_id, document_id=document_id)
        is not None
    ):
        return None
    if laatste is None:
        return (
            "Klant-accordering staat aan voor deze administratie — bied het document ter "
            "accordering aan; na het laatste akkoord wordt automatisch geboekt"
        )
    if laatste.status == AccorderingStatus.OPEN.value:
        return (
            "Het document ligt bij de klant-accordeur (ronde loopt) — boeken volgt automatisch ná het laatste akkoord"
        )
    if laatste.status != AccorderingStatus.AFGEROND.value:
        return f"De laatste accorderingsronde is {laatste.status} — bied het document opnieuw ter accordering aan"
    akkoord_bedrag = _als_decimal((laatste.detail or {}).get("totaalbedrag"))
    voorstel = session.get(Boekvoorstel, document_id)
    huidig_bedrag = _als_decimal(voorstel.totaalbedrag) if voorstel is not None else None
    if akkoord_bedrag is not None and huidig_bedrag is not None and akkoord_bedrag != huidig_bedrag:
        return (
            f"Het totaalbedrag is gewijzigd ná het klant-akkoord (€ {akkoord_bedrag} → € {huidig_bedrag}) — "
            "bied het document opnieuw ter accordering aan"
        )
    return None


def klant_akkoord_compleet_onverzilverd(session: Session, *, document_id: uuid.UUID) -> bool:
    """Punt 24: True als de LAATSTE ronde afgerond is, het bedrag ongewijzigd (de boekpoort staat
    dus open) én er sinds die afronding géén boeking (GEBOEKT-overgang) meer geweest is — het
    akkoord is compleet maar nog niet 'verzilverd'. Een herboeking ná tegenboeken (GEBOEKT →
    te_controleren, boek_cyclus+1) telt als verzilverd: dáár mag het kantoor kiezen tussen
    opnieuw aanbieden en direct boeken. Sessie van de aanroeper (al gescoopt)."""
    laatste = _laatste_accordering(session, document_id)
    if laatste is None or laatste.status != AccorderingStatus.AFGEROND.value:
        return False
    if accordering_blokkade_voor_boeken(session, document_id=document_id) is not None:
        return False
    geboekt_na_akkoord = session.scalar(
        select(func.count())
        .select_from(DocumentGebeurtenis)
        .where(
            DocumentGebeurtenis.document_id == document_id,
            DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
            DocumentGebeurtenis.van_status != DocumentStatus.GEBOEKT,
            DocumentGebeurtenis.tijdstip >= (laatste.afgerond_op or laatste.aangeboden_op),
        )
    )
    return not geboekt_na_akkoord


def is_na_compleet_klant_akkoord(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    """Punt 23 (besluit Peter 28-08): loopt deze boekpoging ná een COMPLEET klant-akkoord? Dan
    heeft een mens al per document op de knop gedrukt en geldt niet de 20/dag-automatiseringsrem
    maar de hoge noodrem (`max_boekingen_na_klant_akkoord_per_dag_per_administratie`). Alleen
    waar als accordering aan staat én de laatste ronde afgerond is mét ongewijzigd bedrag —
    autoboek-paden (opt-ins, bank, verkoop) komen hier nooit doorheen."""
    if not is_accordering_ingeschakeld(administratie_id=administratie_id):
        return False
    with scoped_session(administratie_id) as session:
        laatste = _laatste_accordering(session, document_id)
        if laatste is None or laatste.status != AccorderingStatus.AFGEROND.value:
            return False
        return accordering_blokkade_voor_boeken(session, document_id=document_id) is None


def klant_akkoord_compleet_per_document(session: Session, document_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Bulk (geen N+1) voor de documentenlijst (punt 24): de documenten waarvan het klant-akkoord
    compleet én onverzilverd is — de bulk-selectie zet die uit mét uitleg ('boek direct')."""
    if not document_ids:
        return set()
    rondes = list(
        session.scalars(
            select(DocumentAccordering)
            .where(DocumentAccordering.document_id.in_(document_ids))
            .order_by(DocumentAccordering.aangeboden_op.asc())
        )
    )
    laatste_per_document: dict[uuid.UUID, DocumentAccordering] = {}
    for ronde in rondes:
        laatste_per_document[ronde.document_id] = ronde
    return {
        d_id
        for d_id, ronde in laatste_per_document.items()
        if ronde.status == AccorderingStatus.AFGEROND.value
        and klant_akkoord_compleet_onverzilverd(session, document_id=d_id)
    }


def heeft_afgeronde_accordering(session: Session, *, document_id: uuid.UUID) -> bool:
    """True als de boekmotor door de accorderingspoort mag (laatste ronde afgerond, bedrag
    ongewijzigd) — leesbare variant van `accordering_blokkade_voor_boeken`."""
    return accordering_blokkade_voor_boeken(session, document_id=document_id) is None


def is_accordering_ingeschakeld(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        return administratie is not None and administratie.accordering_ingeschakeld


def _vereis_kantoor(actor_rol: str) -> None:
    # Externe app-rollen (accordeur + veldrollen, app/auth/rollen.py) mogen nooit
    # kantoor-acties — toets tegen de centrale set, niet alleen klant_accordeur.
    if is_externe_app_rol(GebruikerRol(actor_rol)):
        raise KantoorActieVereist("Deze actie is voorbehouden aan het kantoor")


# --- instellingen (toggle + lagen) ---------------------------------------------------------------


def instellingen_ophalen(*, administratie_id: uuid.UUID) -> tuple[bool, list[AccorderingLaag], dict[uuid.UUID, str]]:
    with scoped_session(administratie_id) as session:
        lagen = _actieve_lagen(session, administratie_id=administratie_id, afdeling_id=None)
        namen = _gebruikersnamen(session, {laag.accordeur_gebruiker_id for laag in lagen})
        session.expunge_all()
    return is_accordering_ingeschakeld(administratie_id=administratie_id), lagen, namen


def _actieve_lagen(
    session: Session, *, administratie_id: uuid.UUID, afdeling_id: uuid.UUID | None
) -> list[AccorderingLaag]:
    """De actieve lagen van één route: `afdeling_id=None` = de administratie-route (bestaand),
    anders de eigen route van die afdeling (blok A 28-08, migratie 0084)."""
    return list(
        session.scalars(
            select(AccorderingLaag)
            .where(
                AccorderingLaag.administratie_id == administratie_id,
                AccorderingLaag.actief.is_(True),
                AccorderingLaag.afdeling_id.is_(None)
                if afdeling_id is None
                else AccorderingLaag.afdeling_id == afdeling_id,
            )
            .order_by(AccorderingLaag.volgnummer)
        )
    )


def afdeling_route_ophalen(
    *, administratie_id: uuid.UUID, afdeling_id: uuid.UUID
) -> tuple[list[AccorderingLaag], dict[uuid.UUID, str]]:
    with scoped_session(administratie_id) as session:
        afdeling = session.get(Afdeling, afdeling_id)
        if afdeling is None or afdeling.administratie_id != administratie_id:
            raise AccorderingFout(f"Onbekende afdeling: {afdeling_id}")
        if afdeling.is_terugval:
            # De terugval volgt de administratie-route (mockup: "Route van de administratie").
            lagen = _actieve_lagen(session, administratie_id=administratie_id, afdeling_id=None)
        else:
            lagen = _actieve_lagen(session, administratie_id=administratie_id, afdeling_id=afdeling_id)
        namen = _gebruikersnamen(session, {laag.accordeur_gebruiker_id for laag in lagen})
        session.expunge_all()
    return lagen, namen


def afdeling_route_opslaan(
    *,
    administratie_id: uuid.UUID,
    afdeling_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_rol: str,
    lagen: list[LaagInput],
) -> RondeUitkomst:
    """Route per afdeling (blok A 28-08): zelfde lagen-bouwstenen en dezelfde herberekeningsregel als
    de administratie-route (bundel 09-09 blok 2), maar alleen rondes van documenten in DEZE afdeling
    worden herberekend. De terugval-afdeling heeft geen eigen route (409 — wijzig de
    administratie-route). Minstens één laag: een lege route zou elk document van de afdeling stil
    laten stranden op GeenLagenIngesteld. Geeft de ronde-telling (herberekend/vervallen) terug."""
    _vereis_kantoor(actor_rol)
    if not lagen:
        raise GeenLagenIngesteld("Een afdelingsroute vereist minstens één accorderingslaag")
    volgnummers = [laag.volgnummer for laag in lagen]
    if len(volgnummers) != len(set(volgnummers)):
        raise OngeldigeAanbieding("Volgnummers van de lagen moeten uniek zijn")
    uitkomst = RondeUitkomst()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        afdeling = session.get(Afdeling, afdeling_id)
        if afdeling is None or afdeling.administratie_id != administratie_id:
            raise AccorderingFout(f"Onbekende afdeling: {afdeling_id}")
        if afdeling.is_terugval:
            raise OngeldigeAanbieding(
                "De terugval-afdeling volgt de accorderingsroute van de administratie — wijzig die route"
            )
        if not afdeling.actief:
            raise OngeldigeAanbieding("Deze afdeling is gearchiveerd")
        bestaande = _actieve_lagen(session, administratie_id=administratie_id, afdeling_id=afdeling_id)
        nu = datetime.now(UTC)
        schema_gewijzigd = _schema_gewijzigd(bestaande, lagen)
        for laag in bestaande:
            laag.actief = False
            laag.gedeactiveerd_door = actor_id
            laag.gedeactiveerd_op = nu
        if schema_gewijzigd:
            uitkomst = _herbereken_open_rondes(
                session,
                administratie_id=administratie_id,
                actor_id=actor_id,
                nu=nu,
                lagen=lagen,
                afdeling_ids={afdeling_id},
            )
        for invoer in lagen:
            session.add(
                AccorderingLaag(
                    administratie_id=administratie_id,
                    volgnummer=invoer.volgnummer,
                    accordeur_gebruiker_id=invoer.accordeur_gebruiker_id,
                    bedrag_drempel=invoer.bedrag_drempel,
                    afdeling_id=afdeling_id,
                    aangemaakt_door=actor_id,
                )
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="accordering_laag",
            record_id=afdeling_id,
            actie="accordering_afdelingsroute_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={
                "lagen": [{"volgnummer": b.volgnummer, "accordeur": str(b.accordeur_gebruiker_id)} for b in bestaande]
            },
            nieuwe_waarde={
                "afdeling": afdeling.naam,
                "lagen": [
                    {
                        "volgnummer": laag.volgnummer,
                        "accordeur": str(laag.accordeur_gebruiker_id),
                        "bedrag_drempel": str(laag.bedrag_drempel) if laag.bedrag_drempel is not None else None,
                    }
                    for laag in lagen
                ],
                "rondes_herberekend": uitkomst.herberekend,
                "rondes_vervallen": uitkomst.vervallen,
            },
            administratie_id=administratie_id,
        )
    _rond_herberekende_rondes_af(administratie_id=administratie_id, uitkomst=uitkomst)
    return uitkomst


@dataclass(frozen=True)
class LaagInput:
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    bedrag_drempel: Decimal | None


def instellingen_opslaan(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_rol: str,
    ingeschakeld: bool,
    lagen: list[LaagInput],
    aanleiding: str | None = None,
) -> RondeUitkomst:
    """Beheerder-only (router-dependency) + nooit door een accordeur. Lagen zijn append-only:
    de bestaande actieve lagen worden gedeactiveerd, de nieuwe set aangemaakt. Aanzetten zonder
    lagen is geweigerd (een toggle zonder schema zou elke boeking stil blokkeren).

    Lopende rondes (bundel 09-09 blok 2, besluit Peter 08-09 — herziet punt 2a van 27/28-08): een OPEN
    ronde draagt de stappen die op het aanbied-moment uit de tóén actieve lagen bevroren zijn. Wijzigt
    het effectieve schema (andere lagen/accordeurs/drempels), dan wordt de ronde HERBEREKEND tegen de
    nieuwe lagen (`herberekening.herbereken`): gegeven akkoorden blijven staan waar ze nog passen,
    ontbrekende lagen worden opnieuw aangevraagd, en is alles gedekt dan volgt de bestaande
    afrondingsroute. Alleen als géén enkel gegeven akkoord meer past — of de toggle uitgaat — VERVALT de
    ronde via het bestaande pad (status `vervallen`, document terug naar klaar_om_te_boeken, tijdlijn mét
    reden `VERVALLEN_REDEN` + batch-id voor de werkvoorraad-melding, audit per ronde). Niets verdwijnt
    stil. Een opslag die het schema niet verandert (bv. alleen opnieuw opslaan) raakt geen ronde.
    Geeft de ronde-telling terug (herberekend = geraakt, vervallen ⊆ herberekend).

    `aanleiding` (blok 5 herstelrun 08-09, bv. "verwijderd via Klant-accordeurs"): reist mee in beide audit-events
    én in het tijdlijn-detail van élke geraakte ronde — de aanleiding van een uitschakeling blijft zo leesbaar."""
    _vereis_kantoor(actor_rol)
    if ingeschakeld and not lagen:
        raise GeenLagenIngesteld("Accordering aanzetten vereist minstens één accorderingslaag")
    volgnummers = [laag.volgnummer for laag in lagen]
    if len(volgnummers) != len(set(volgnummers)):
        raise OngeldigeAanbieding("Volgnummers van de lagen moeten uniek zijn")

    uitkomst = RondeUitkomst()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        # Alleen de administratie-route (afdeling_id NULL); afdelingsroutes hebben hun eigen
        # opslag (afdeling_route_opslaan) en blijven hier ongemoeid.
        bestaande = _actieve_lagen(session, administratie_id=administratie_id, afdeling_id=None)
        administratie_vooraf = session.get(Administratie, administratie_id)
        was_ingeschakeld = bool(administratie_vooraf and administratie_vooraf.accordering_ingeschakeld)
        schema_gewijzigd = _schema_gewijzigd(bestaande, lagen) or (was_ingeschakeld and not ingeschakeld)
        nu = datetime.now(UTC)
        for laag in bestaande:
            laag.actief = False
            laag.gedeactiveerd_door = actor_id
            laag.gedeactiveerd_op = nu
        if schema_gewijzigd:
            detail_extra = {"aanleiding": aanleiding} if aanleiding else None
            if not ingeschakeld:
                # Toggle uit = álle rondes vervallen (er is geen configuratie meer om tegen te herberekenen).
                vervallen = _laat_open_rondes_vervallen(
                    session,
                    administratie_id=administratie_id,
                    actor_id=actor_id,
                    nu=nu,
                    afdeling_ids=None,
                    detail_extra=detail_extra,
                )
                uitkomst = RondeUitkomst(herberekend=vervallen, vervallen=vervallen)
            else:
                # Schema-wijziging = alleen rondes die op de administratie-route liepen (geen afdeling, of
                # de terugval-afdeling "Algemeen") worden herberekend; afdelingsroutes blijven ongemoeid.
                from app.afdelingen.service import terugval_id

                uitkomst = _herbereken_open_rondes(
                    session,
                    administratie_id=administratie_id,
                    actor_id=actor_id,
                    nu=nu,
                    lagen=lagen,
                    afdeling_ids={None, terugval_id(session, administratie_id)},
                    detail_extra=detail_extra,
                )
        for invoer in lagen:
            session.add(
                AccorderingLaag(
                    administratie_id=administratie_id,
                    volgnummer=invoer.volgnummer,
                    accordeur_gebruiker_id=invoer.accordeur_gebruiker_id,
                    bedrag_drempel=invoer.bedrag_drempel,
                    aangemaakt_door=actor_id,
                )
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="accordering_laag",
            record_id=administratie_id,
            actie="accordering_schema_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={
                "lagen": [{"volgnummer": b.volgnummer, "accordeur": str(b.accordeur_gebruiker_id)} for b in bestaande]
            },
            nieuwe_waarde={
                "ingeschakeld": ingeschakeld,
                "lagen": [
                    {
                        "volgnummer": laag.volgnummer,
                        "accordeur": str(laag.accordeur_gebruiker_id),
                        "bedrag_drempel": str(laag.bedrag_drempel) if laag.bedrag_drempel is not None else None,
                    }
                    for laag in lagen
                ],
                "rondes_herberekend": uitkomst.herberekend,
                "rondes_vervallen": uitkomst.vervallen,
                **({"aanleiding": aanleiding} if aanleiding else {}),
            },
            administratie_id=administratie_id,
        )

    # Zelfde patroon als beheer/service.py::zet_boeken_ingeschakeld: platformbrede
    # Beheerder-handeling, sessie gescoped op None en audit_event.administratie_id bewust NULL
    # (de RLS WITH CHECK op audit_event kent geen beheerder-bypass).
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise DocumentNietGevonden(f"Onbekende administratie: {administratie_id}")
        oud = administratie.accordering_ingeschakeld
        administratie.accordering_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="accordering_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"accordering_ingeschakeld": oud},
            nieuwe_waarde={
                "accordering_ingeschakeld": ingeschakeld,
                **({"aanleiding": aanleiding} if aanleiding else {}),
            },
        )
    # Ná de configuratie-transactie: staande goedkeuringen op de opnieuw aangevraagde stappen en — is alles
    # gedekt — de bestaande afrondingsroute (exact zoals bij een laatste akkoord).
    _rond_herberekende_rondes_af(administratie_id=administratie_id, uitkomst=uitkomst)
    return uitkomst


# Reden op de tijdlijnregel van een vervallen ronde (punt 2a, casus 34 facturen 27-08): letterlijk
# zichtbaar in het controlescherm én in de werkvoorraad-melding — dit was eerder een raadsel.
VERVALLEN_REDEN = "accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist"
# Vensterbreedte van de werkvoorraad-melding: een vervallen-batch ouder dan dit wordt niet meer
# gemeld (de tijdlijn per document blijft de bron, altijd).
VERVALLEN_MELDING_DAGEN = 14


def _schema_gewijzigd(bestaande: list[AccorderingLaag], nieuw: list[LaagInput]) -> bool:
    """Effectieve vergelijking van het lagen-schema — volgorde-onafhankelijk, drempel op waarde
    (Decimal('1000') == Decimal('1000.00'))."""
    oud_set = {(b.volgnummer, b.accordeur_gebruiker_id, b.bedrag_drempel) for b in bestaande}
    nieuw_set = {(n.volgnummer, n.accordeur_gebruiker_id, n.bedrag_drempel) for n in nieuw}
    return oud_set != nieuw_set


def _ronde_afdeling_id(accordering: DocumentAccordering) -> uuid.UUID | None:
    ruw = (accordering.detail or {}).get("afdeling_id")
    return uuid.UUID(ruw) if ruw else None


def _laat_open_rondes_vervallen(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    nu: datetime,
    afdeling_ids: set[uuid.UUID | None] | None = None,
    document_ids: set[uuid.UUID] | None = None,
    reden: str = VERVALLEN_REDEN,
    detail_extra: dict | None = None,
) -> int:
    """OPEN rondes → `vervallen`; document → klaar_om_te_boeken mét tijdlijn-detail (reden +
    batch_id) en audit per ronde. Eén batch_id per configuratiewijziging zodat de
    werkvoorraad-melding de wijziging als één gebeurtenis kan tonen. `afdeling_ids` (blok A
    28-08) beperkt tot rondes van díe afdelingen (None-lid = rondes zonder afdeling);
    `document_ids` tot díe documenten (afdeling gewijzigd ná aanbieden). Zonder filters: alles."""
    open_rondes = [
        r
        for r in session.scalars(
            select(DocumentAccordering).where(
                DocumentAccordering.administratie_id == administratie_id,
                DocumentAccordering.status == AccorderingStatus.OPEN.value,
            )
        )
        if (afdeling_ids is None or _ronde_afdeling_id(r) in afdeling_ids)
        and (document_ids is None or r.document_id in document_ids)
    ]
    if not open_rondes:
        return 0
    batch_id = uuid.uuid4()
    for accordering in open_rondes:
        accordering.status = AccorderingStatus.VERVALLEN.value
        accordering.afgerond_op = nu
        document = session.get(Document, accordering.document_id)
        if document is None:  # pragma: no cover — FK maakt dit onmogelijk
            continue
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=actor_id,
            detail={
                "accordering_id": str(accordering.id),
                "accordering_vervallen": True,
                "reden": reden,
                "batch_id": str(batch_id),
                **(detail_extra or {}),
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document_accordering",
            record_id=accordering.id,
            actie="accordering_vervallen",
            correlatie_id=batch_id,
            oude_waarde={"status": AccorderingStatus.OPEN.value},
            nieuwe_waarde={
                "status": AccorderingStatus.VERVALLEN.value,
                "document_id": str(accordering.document_id),
                "reden": reden,
            },
            administratie_id=administratie_id,
        )
    return len(open_rondes)


# --- Herberekening van lopende rondes bij een configuratiewijziging (bundel 09-09 blok 2) ---------
#
# Besluit Peter 08-09 (herziet "GECOMBINEERDE RUN 01-09" blok A beslispunt 2): een configuratiewijziging
# (lagen/accordeurs/drempels via de detail-tab, bulk-instellen, het accordeur-venster of een
# afdelingsroute) laat een lopende ronde niet meer vervallen maar HERBEREKENT haar. De pure regel staat
# in `herberekening.py`; hier de schrijfkant: stappen bijwerken, tijdlijn + audit per document, en ná de
# transactie de bestaande afrondingsroute voor rondes die nu volledig gedekt zijn.

HERBEREKEND_REDEN = "accorderingsconfiguratie gewijzigd — ronde herberekend"
HERBEREKEND_AUDIT_ACTIE = "accordering_ronde_herberekend"
HERBEREKEND_TIJDLIJN_SLEUTEL = "accordering_herberekend"
STAP_VERVALLEN_REDEN = "vervallen bij herberekening — laag past niet meer in de nieuwe configuratie"


@dataclass(frozen=True)
class RondeUitkomst:
    """Telling van één configuratiewijziging: `herberekend` = lopende rondes die geraakt zijn (incl. de
    vervallen), `vervallen` = het deel dat verviel omdat geen enkel gegeven akkoord meer paste (of de
    toggle uitging). `af_te_ronden` = (ronde, document) die ná de transactie de staande-regel-/
    afrondingsroute krijgen — puur intern, niet in DTO's."""

    herberekend: int = 0
    vervallen: int = 0
    af_te_ronden: tuple[tuple[uuid.UUID, uuid.UUID], ...] = ()


def _stap_stand(stap: AccorderingStap) -> herberekening_module.StapStand:
    return herberekening_module.StapStand(
        volgnummer=stap.volgnummer,
        accordeur_gebruiker_id=stap.accordeur_gebruiker_id,
        bedrag_drempel=stap.bedrag_drempel,
        vereist=stap.vereist,
        besluit=stap.besluit,
    )


def _laag_specs(lagen: list[LaagInput]) -> list[herberekening_module.LaagSpec]:
    return [
        herberekening_module.LaagSpec(
            volgnummer=laag.volgnummer,
            accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
            bedrag_drempel=laag.bedrag_drempel,
        )
        for laag in lagen
    ]


def _open_rondes_gefilterd(
    session: Session, *, administratie_id: uuid.UUID, afdeling_ids: set[uuid.UUID | None] | None
) -> list[DocumentAccordering]:
    """Exact het filter van `_laat_open_rondes_vervallen`: open rondes van de administratie, beperkt tot de
    gegeven afdelingen (None-lid = rondes zonder afdeling)."""
    return [
        r
        for r in session.scalars(
            select(DocumentAccordering).where(
                DocumentAccordering.administratie_id == administratie_id,
                DocumentAccordering.status == AccorderingStatus.OPEN.value,
            )
        )
        if afdeling_ids is None or _ronde_afdeling_id(r) in afdeling_ids
    ]


def _stap_naar_dict(stap: AccorderingStap) -> dict:
    return {
        "volgnummer": stap.volgnummer,
        "accordeur": str(stap.accordeur_gebruiker_id),
        "bedrag_drempel": str(stap.bedrag_drempel) if stap.bedrag_drempel is not None else None,
        "vereist": stap.vereist,
        "besluit": stap.besluit,
        "besluit_bron": stap.besluit_bron,
    }


def telling_herberekening(
    session: Session, *, administratie_id: uuid.UUID, lagen: list[LaagInput], afdeling_ids: set[uuid.UUID | None] | None
) -> RondeUitkomst:
    """Preview-telling (leest alleen): hoeveel lopende rondes deze lagen zouden herberekenen en hoeveel daarvan
    zouden vervallen — met dezelfde pure functie als de echte wijziging, zodat vooraf en achteraf nooit uiteenlopen."""
    rondes = _open_rondes_gefilterd(session, administratie_id=administratie_id, afdeling_ids=afdeling_ids)
    specs = _laag_specs(lagen)
    vervallen = 0
    for ronde in rondes:
        stappen = _stappen_van(session, ronde.id)
        h = herberekening_module.herbereken(
            [_stap_stand(s) for s in stappen], specs, _als_decimal((ronde.detail or {}).get("totaalbedrag"))
        )
        if h.ronde_vervalt:
            vervallen += 1
    return RondeUitkomst(herberekend=len(rondes), vervallen=vervallen)


def _herbereken_open_rondes(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    nu: datetime,
    lagen: list[LaagInput],
    afdeling_ids: set[uuid.UUID | None] | None,
    detail_extra: dict | None = None,
) -> RondeUitkomst:
    """Alle OPEN rondes in het filter herberekenen tegen `lagen` (pure regel: `herberekening.herbereken`).

    Per ronde die blijft lopen: behouden akkoorden en hergebruikte onbesliste stappen krijgen de nieuwe
    positie/drempel (rij bijgewerkt, besluit onaangeroerd), nieuwe lagen krijgen een verse stap, en oude
    stappen die niet meer passen worden gemarkeerd `besluit='vervallen'` + `vereist=False` (historie blijft
    staan — de app-rol heeft bewust geen DELETE op accordering_stap). Tijdlijn-notitie (geen statusovergang)
    + audit `accordering_ronde_herberekend` oud→nieuw per document, één batch_id per wijziging. Een
    accordeur wiens akkoord verviel én die opnieuw aan de beurt komt, wordt via de bestaande bundelmelding
    opnieuw gemeld (claim heropend). Rondes waarvan géén enkel gegeven akkoord meer past gaan in één batch
    door het bestaande vervallen-pad (`_laat_open_rondes_vervallen`). Afgeronde rondes (compleet klant-akkoord)
    zijn niet OPEN en worden dus nooit geraakt (regel 28-08)."""
    rondes = _open_rondes_gefilterd(session, administratie_id=administratie_id, afdeling_ids=afdeling_ids)
    if not rondes:
        return RondeUitkomst()
    specs = _laag_specs(lagen)
    batch_id = uuid.uuid4()
    te_vervallen: set[uuid.UUID] = set()
    af_te_ronden: list[tuple[uuid.UUID, uuid.UUID]] = []
    for ronde in rondes:
        stappen = _stappen_van(session, ronde.id)
        totaalbedrag = _als_decimal((ronde.detail or {}).get("totaalbedrag"))
        h = herberekening_module.herbereken([_stap_stand(s) for s in stappen], specs, totaalbedrag)
        if h.ronde_vervalt:
            te_vervallen.add(ronde.document_id)
            continue
        oude_stand = [_stap_naar_dict(s) for s in sorted(stappen, key=lambda s: s.volgnummer)]
        vervallen_akkoord_accordeurs = {
            stappen[i].accordeur_gebruiker_id
            for i in h.vervallen_indices
            if stappen[i].besluit == StapBesluit.AKKOORD.value
        }
        for index in h.vervallen_indices:
            oud = stappen[index]
            oud.besluit = StapBesluit.VERVALLEN.value
            oud.vereist = False
            oud.reden = STAP_VERVALLEN_REDEN
            oud.besloten_op = nu
        nieuwe_rijen: list[AccorderingStap] = []
        for nieuw in h.stappen:
            if nieuw.bron_index is not None:
                rij = stappen[nieuw.bron_index]
                rij.volgnummer = nieuw.volgnummer
                rij.bedrag_drempel = nieuw.bedrag_drempel
                rij.vereist = nieuw.vereist
            else:
                rij = AccorderingStap(
                    administratie_id=administratie_id,
                    accordering_id=ronde.id,
                    volgnummer=nieuw.volgnummer,
                    accordeur_gebruiker_id=nieuw.accordeur_gebruiker_id,
                    bedrag_drempel=nieuw.bedrag_drempel,
                    vereist=nieuw.vereist,
                )
                session.add(rij)
            nieuwe_rijen.append(rij)
        session.flush()
        nieuwe_stand = [_stap_naar_dict(s) for s in sorted(nieuwe_rijen, key=lambda s: s.volgnummer)]
        ronde.detail = {
            **(ronde.detail or {}),
            "herberekend": {
                "aantal": int(((ronde.detail or {}).get("herberekend") or {}).get("aantal", 0)) + 1,
                "laatste_op": nu.isoformat(),
                "batch_id": str(batch_id),
            },
        }
        samenvatting = {
            "akkoorden_behouden": h.akkoorden_behouden,
            "akkoorden_vervallen": h.akkoorden_vervallen,
            "opnieuw_aangevraagd": list(h.opnieuw_aangevraagd),
            "alles_akkoord": h.alles_akkoord,
            "lagen": nieuwe_stand,
        }
        document = session.get(Document, ronde.document_id)
        if document is not None:
            session.add(
                DocumentGebeurtenis(
                    id=uuid.uuid4(),
                    document_id=ronde.document_id,
                    van_status=document.status,
                    naar_status=document.status,
                    actor_id=actor_id,
                    detail={
                        "accordering_id": str(ronde.id),
                        HERBEREKEND_TIJDLIJN_SLEUTEL: samenvatting,
                        "reden": HERBEREKEND_REDEN,
                        "batch_id": str(batch_id),
                        **(detail_extra or {}),
                    },
                )
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document_accordering",
            record_id=ronde.id,
            actie=HERBEREKEND_AUDIT_ACTIE,
            correlatie_id=batch_id,
            oude_waarde={"stappen": oude_stand},
            nieuwe_waarde={
                "document_id": str(ronde.document_id),
                "reden": HERBEREKEND_REDEN,
                "stappen": nieuwe_stand,
                **samenvatting,
                **(detail_extra or {}),
            },
            administratie_id=administratie_id,
        )
        # Opnieuw aangevraagd bij een accordeur wiens akkoord zojuist verviel: de bundelmelding meldt een
        # document nooit tweemaal aan dezelfde accordeur — hier is het een nieuwe vraag, dus claim heropenen.
        opnieuw_bij = {
            s.accordeur_gebruiker_id for s in h.stappen if s.vereist and not s.akkoord_behouden
        } & vervallen_akkoord_accordeurs
        if opnieuw_bij:
            _heropen_bundelmelding(session, document_id=ronde.document_id, accordeur_ids=opnieuw_bij, nu=nu)
        af_te_ronden.append((ronde.id, ronde.document_id))
    vervallen = 0
    if te_vervallen:
        vervallen = _laat_open_rondes_vervallen(
            session,
            administratie_id=administratie_id,
            actor_id=actor_id,
            nu=nu,
            document_ids=te_vervallen,
            detail_extra=detail_extra,
        )
    return RondeUitkomst(herberekend=len(rondes), vervallen=vervallen, af_te_ronden=tuple(af_te_ronden))


def _heropen_bundelmelding(
    session: Session, *, document_id: uuid.UUID, accordeur_ids: set[uuid.UUID], nu: datetime
) -> None:
    """Idempotentie-log van de nieuwe-facturen-bundelmelding (platform.accordeur_nieuw_gemeld): een 'verzonden'
    claim terug naar 'overgeslagen' zodat de volgende run (`berichten/nieuwe_facturen.py`, push-anders-mail)
    de accordeur opnieuw meldt zodra hij aan de beurt is. Geen eigen verzending hier — de bestaande route."""
    from app.berichten.models import AccordeurNieuwGemeld, HerinneringStatus

    rijen = session.scalars(
        select(AccordeurNieuwGemeld).where(
            AccordeurNieuwGemeld.document_id == document_id,
            AccordeurNieuwGemeld.gebruiker_id.in_(accordeur_ids),
            AccordeurNieuwGemeld.status == HerinneringStatus.VERZONDEN.value,
        )
    ).all()
    for rij in rijen:
        rij.status = HerinneringStatus.OVERGESLAGEN.value
        rij.detail = {
            **(rij.detail or {}),
            "heropend": {"reden": HERBEREKEND_REDEN, "op": nu.isoformat()},
        }


def _rond_herberekende_rondes_af(*, administratie_id: uuid.UUID, uitkomst: RondeUitkomst) -> None:
    """Ná de configuratie-transactie, per herberekende ronde: staande goedkeuringen op de opnieuw aangevraagde
    stappen en — alle vereiste lagen gedekt — de bestaande afrondingsroute (`_rond_af_en_boek`: ronde AFGEROND,
    boekmotor mét alle harde checks, boekfout zichtbaar op de ronde). Precies het pad van een laatste akkoord.
    Een onverwachte fout in één ronde blokkeert de configuratie-opslag niet en verdwijnt niet stil: log +
    tijdlijnregel mét reden."""
    for accordering_id, document_id in uitkomst.af_te_ronden:
        try:
            _pas_staande_regels_toe_en_rond_af(
                administratie_id=administratie_id, accordering_id=accordering_id, document_id=document_id
            )
        except Exception as exc:  # noqa: BLE001 — nooit stil, nooit de configuratie-opslag laten stranden
            logger.exception("Afronding ná herberekening faalde voor ronde %s", accordering_id)
            with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
                document = session.get(Document, document_id)
                if document is not None:
                    session.add(
                        DocumentGebeurtenis(
                            id=uuid.uuid4(),
                            document_id=document_id,
                            van_status=document.status,
                            naar_status=document.status,
                            actor_id=SYSTEEM_ACTOR_ID,
                            detail={
                                "accordering_id": str(accordering_id),
                                "accordering_herberekend_afronding_fout": str(exc) or exc.__class__.__name__,
                                "reden": f"afronding ná herberekening mislukt: {exc}",
                            },
                        )
                    )


# Blok A 28-08: afdeling gewijzigd ná aanbieden — zelfde regel als een configuratiewijziging.
AFDELING_GEWIJZIGD_REDEN = "afdeling gewijzigd — opnieuw aanbieden vereist"


def laat_ronde_vervallen_bij_duplicaat(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> int:
    """Blok A2 04-09 (besluit Peter "geen dubbeling"): het document wordt als duplicaat afgevoerd terwijl het
    bij de klant-accordeur ligt — de lopende ronde vervalt mét reden "afgevoerd als duplicaat van ‹ref›"
    (bestaand vervallen-patroon: ronde → vervallen, document → klaar_om_te_boeken, tijdlijn + audit), maar
    gemarkeerd `accordering_vervallen_duplicaat` zodat de werkvoorraad-banner "accorderingsconfiguratie
    gewijzigd — opnieuw aanbieden" 'm níét als herstelwerk telt. Ligt er geen OPEN ronde meer (klant-akkoord
    al compleet, boeking mislukt = `boek_fout`) dan gaat het document alsnog terug naar klaar_om_te_boeken
    mét dezelfde reden op de tijdlijn — nooit stil vast op ter_accordering."""
    aantal = _laat_open_rondes_vervallen(
        session,
        administratie_id=administratie_id,
        actor_id=actor_id,
        nu=datetime.now(UTC),
        document_ids={document_id},
        reden=reden,
        detail_extra={"accordering_vervallen_duplicaat": True},
    )
    if aantal:
        return aantal
    document = session.get(Document, document_id)
    if document is not None and document.status == DocumentStatus.TER_ACCORDERING:
        laatste = _laatste_accordering(session, document_id)
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=actor_id,
            detail={
                "accordering_id": str(laatste.id) if laatste is not None else None,
                "accordering_vervallen_duplicaat": True,
                "reden": reden,
            },
        )
    return 0


def laat_ronde_vervallen_bij_afdelingwijziging(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> int:
    """Aangeroepen vanuit het boekvoorstel-opslaan (zelfde transactie) zodra de afdeling van een
    document mét open ronde verandert: de bevroren stappen horen bij de oude route."""
    return _laat_open_rondes_vervallen(
        session,
        administratie_id=administratie_id,
        actor_id=actor_id,
        nu=datetime.now(UTC),
        document_ids={document_id},
        reden=AFDELING_GEWIJZIGD_REDEN,
    )


@dataclass(frozen=True)
class VervallenMelding:
    """Eén configuratiewijziging die rondes liet vervallen (punt 2a): voedt de eenmalige
    werkvoorraad-banner op de documentenlijst van de administratie."""

    batch_id: uuid.UUID
    tijdstip: datetime
    door_gebruiker_id: uuid.UUID
    aantal: int
    # Documenten uit de batch die nu nog op klaar_om_te_boeken staan (= nog niet opnieuw
    # aangeboden/geboekt): 0 → melding is vanzelf klaar.
    nog_niet_opnieuw_aangeboden: int


def vervallen_meldingen(*, administratie_id: uuid.UUID) -> list[VervallenMelding]:
    """Vervallen-batches van de afgelopen VERVALLEN_MELDING_DAGEN, nieuwste eerst. Bron = de
    tijdlijn (document_gebeurtenis met detail.accordering_vervallen), geen extra tabel."""
    from datetime import timedelta

    from sqlalchemy import Text, cast, func

    grens = datetime.now(UTC) - timedelta(days=VERVALLEN_MELDING_DAGEN)
    # Eén expressie-object voor select én group_by: zo krijgt Postgres dezelfde bind-parameter en
    # geen "must appear in the GROUP BY"-fout.
    batch_expr = DocumentGebeurtenis.detail["batch_id"].astext
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(
                batch_expr.label("batch_id"),
                func.min(DocumentGebeurtenis.tijdstip).label("tijdstip"),
                # min() bestaat niet voor uuid in Postgres — via tekst (één actor per batch).
                func.min(cast(DocumentGebeurtenis.actor_id, Text)).label("actor_id"),
                func.count().label("aantal"),
                func.count().filter(Document.status == DocumentStatus.KLAAR_OM_TE_BOEKEN).label("nog_open"),
            )
            .join(Document, Document.id == DocumentGebeurtenis.document_id)
            .where(
                Document.administratie_id == administratie_id,
                DocumentGebeurtenis.tijdstip >= grens,
                DocumentGebeurtenis.detail["accordering_vervallen"].astext == "true",
                # Blok A2 04-09: een ronde die verviel omdat het document als duplicaat is afgevoerd is géén
                # herstelwerk ("opnieuw aanbieden") — die batches blijven buiten deze melding.
                DocumentGebeurtenis.detail["accordering_vervallen_duplicaat"].astext.is_(None),
                batch_expr.isnot(None),
            )
            .group_by(batch_expr)
            .order_by(func.min(DocumentGebeurtenis.tijdstip).desc())
        ).all()
        # Een document dat ná het vervallen wél opnieuw is aangeboden en daarna wéér vervallen
        # is, telt in beide batches — bewust: elke wijziging is een eigen gebeurtenis.
        return [
            VervallenMelding(
                batch_id=uuid.UUID(r.batch_id),
                tijdstip=r.tijdstip,
                door_gebruiker_id=uuid.UUID(r.actor_id),
                aantal=int(r.aantal),
                nog_niet_opnieuw_aangeboden=int(r.nog_open),
            )
            for r in rijen
        ]


# --- Bulk klant-accordering instellen (mockup bulk-accordering.html, besluiten Peter 01-09) -------
#
# Eén dialoog past de lagen toe op álle geselecteerde administraties. Server-side is dit een
# ORKESTRATIE over de bestaande per-administratie-configuratieroute (instellingen_opslaan) —
# geen tweede configuratie-schrijver: elke administratie krijgt exact dezelfde validatie,
# vervallen-regel (punt 2a) en audit als een losse wijziging. Besluiten 01-09: (1) ontbrekende
# accordeur-scope automatisch aanmaken mét expliciete vink (audit via de DB-trigger op
# gebruiker_administratie); (2) bestaande config wordt VERVANGEN mét vooraf de telling van de
# lopende rondes die daarbij vervallen; (3) de bulk zet de klant-accordering-toggle aan waar
# die uit staat. Preview en resultaat delen dezelfde uitkomst-vorm (mockup-notitie ⑥).


@dataclass(frozen=True)
class BulkScopeOntbreekt:
    """Vooraf-melding per accordeur (mockup: "J.W.F. Gerritsen heeft nog geen toegang tot
    Molenhof Beheer en Mantelzorgwoningen MN")."""

    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str
    administratie_ids: list[uuid.UUID]
    administratie_namen: list[str]


@dataclass(frozen=True)
class BulkInstelUitkomst:
    """Eén regel van de uitkomstenlijst — zelfde vorm vóór (preview) en ná (resultaat)."""

    administratie_id: uuid.UUID
    administratie_naam: str
    # 'ingesteld' (had geen config) | 'vervangen' (had config) | 'overgeslagen' (mét reden) |
    # 'fout' (alleen ná toepassen: deelfout per BV zichtbaar, nooit stil half).
    uitkomst: str
    # Bundel 09-09 blok 2: lopende rondes worden herberekend (vervallen ⊆ herberekend).
    rondes_herberekend: int = 0
    rondes_vervallen: int = 0
    toggle_aangezet: bool = False
    scope_toegevoegd_voor: list[str] | None = None
    reden: str | None = None


@dataclass(frozen=True)
class _BulkEvaluatie:
    uitkomst: BulkInstelUitkomst
    ontbrekende_scope_ids: list[uuid.UUID]


def _valideer_bulk_lagen(lagen: list[LaagInput]) -> dict[uuid.UUID, str]:
    """Zelfde basisvalidatie als instellingen_opslaan, plus — omdat de bulk-kiezer over álle
    klant-accordeurs gaat (scope kan immers nog ontbreken) — een harde rol/status-toets op
    élke gekozen accordeur. Geeft de namen per accordeur terug (voor de scope-meldingen)."""
    from app.db.models import GebruikerStatus

    if not lagen:
        raise GeenLagenIngesteld("Bulk instellen vereist minstens één accorderingslaag")
    volgnummers = [laag.volgnummer for laag in lagen]
    if len(volgnummers) != len(set(volgnummers)):
        raise OngeldigeAanbieding("Volgnummers van de lagen moeten uniek zijn")
    accordeur_ids = {laag.accordeur_gebruiker_id for laag in lagen}
    with scoped_session(None) as session:
        rijen = session.execute(
            select(Gebruiker.id, Gebruiker.naam, Gebruiker.rol, Gebruiker.status).where(
                Gebruiker.id.in_(accordeur_ids)
            )
        ).all()
    per_id = {r.id: r for r in rijen}
    for accordeur_id in accordeur_ids:
        rij = per_id.get(accordeur_id)
        if rij is None:
            raise OngeldigeAanbieding(f"Onbekende accordeur: {accordeur_id}")
        if rij.rol != GebruikerRol.KLANT_ACCORDEUR:
            raise OngeldigeAanbieding(f"'{rij.naam}' is geen klant-accordeur — alleen die rol kan accorderen")
        if rij.status != GebruikerStatus.ACTIEF:
            raise OngeldigeAanbieding(f"'{rij.naam}' is niet actief ({rij.status.value}) — kies een actieve accordeur")
    return {r.id: r.naam for r in rijen}


def _telling_administratie_route(
    session: Session, administratie_id: uuid.UUID, lagen: list[LaagInput]
) -> RondeUitkomst:
    """Telling voor de preview: open rondes die bij deze schema-wijziging herberekend zouden worden en
    hoeveel daarvan zouden vervallen — exact het filter én de pure regel van instellingen_opslaan
    (administratie-route: rondes zonder afdeling of op de terugval-afdeling; afdelingsroutes blijven
    ongemoeid)."""
    from app.afdelingen.service import terugval_id

    return telling_herberekening(
        session,
        administratie_id=administratie_id,
        lagen=lagen,
        afdeling_ids={None, terugval_id(session, administratie_id)},
    )


def _bulk_evalueer_administratie(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    lagen: list[LaagInput],
    accordeur_namen: dict[uuid.UUID, str],
    scope_toevoegen: bool,
) -> _BulkEvaluatie:
    from app.db.models import GebruikerAdministratie

    accordeur_ids = sorted({laag.accordeur_gebruiker_id for laag in lagen}, key=str)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            return _BulkEvaluatie(
                BulkInstelUitkomst(
                    administratie_id=administratie_id,
                    administratie_naam=str(administratie_id),
                    uitkomst="overgeslagen",
                    reden="onbekende administratie",
                ),
                [],
            )
        naam = administratie.naam
        if not administratie.actief:
            return _BulkEvaluatie(
                BulkInstelUitkomst(
                    administratie_id=administratie_id,
                    administratie_naam=naam,
                    uitkomst="overgeslagen",
                    reden="administratie is gearchiveerd",
                ),
                [],
            )
        bestaande = _actieve_lagen(session, administratie_id=administratie_id, afdeling_id=None)
        was_ingeschakeld = administratie.accordering_ingeschakeld
        heeft_config = was_ingeschakeld or bool(bestaande)
        rondes = (
            _telling_administratie_route(session, administratie_id, lagen)
            if _schema_gewijzigd(bestaande, lagen)
            else RondeUitkomst()
        )
        ontbrekend = [
            accordeur_id
            for accordeur_id in accordeur_ids
            if session.get(GebruikerAdministratie, (accordeur_id, administratie_id)) is None
        ]
    if ontbrekend and not scope_toevoegen:
        namen = ", ".join(accordeur_namen[a] for a in ontbrekend)
        return _BulkEvaluatie(
            BulkInstelUitkomst(
                administratie_id=administratie_id,
                administratie_naam=naam,
                uitkomst="overgeslagen",
                reden=f"scope ontbreekt voor {namen} (vink 'Scope toevoegen' aan om die aan te maken)",
            ),
            ontbrekend,
        )
    return _BulkEvaluatie(
        BulkInstelUitkomst(
            administratie_id=administratie_id,
            administratie_naam=naam,
            uitkomst="vervangen" if heeft_config else "ingesteld",
            rondes_herberekend=rondes.herberekend,
            rondes_vervallen=rondes.vervallen,
            toggle_aangezet=not was_ingeschakeld,
            scope_toegevoegd_voor=[accordeur_namen[a] for a in ontbrekend],
        ),
        ontbrekend,
    )


def bulk_instellen_preview(
    *,
    administratie_ids: list[uuid.UUID],
    lagen: list[LaagInput],
    scope_toevoegen: bool,
    actor_id: uuid.UUID,
    actor_rol: str,
) -> tuple[list[BulkInstelUitkomst], list[BulkScopeOntbreekt]]:
    """Preview vóór toepassen (mockup: scope-melding + overschrijf-waarschuwing mét telling +
    uitkomstenlijst) — leest alleen, verandert niets."""
    _vereis_kantoor(actor_rol)
    accordeur_namen = _valideer_bulk_lagen(lagen)
    uitkomsten: list[BulkInstelUitkomst] = []
    ontbrekend_per_accordeur: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
    for administratie_id in administratie_ids:
        evaluatie = _bulk_evalueer_administratie(
            administratie_id=administratie_id,
            actor_id=actor_id,
            lagen=lagen,
            accordeur_namen=accordeur_namen,
            scope_toevoegen=scope_toevoegen,
        )
        uitkomsten.append(evaluatie.uitkomst)
        for accordeur_id in evaluatie.ontbrekende_scope_ids:
            ontbrekend_per_accordeur.setdefault(accordeur_id, []).append(
                (administratie_id, evaluatie.uitkomst.administratie_naam)
            )
    scope_meldingen = [
        BulkScopeOntbreekt(
            accordeur_gebruiker_id=accordeur_id,
            accordeur_naam=accordeur_namen[accordeur_id],
            administratie_ids=[a for a, _ in paren],
            administratie_namen=[n for _, n in paren],
        )
        for accordeur_id, paren in sorted(ontbrekend_per_accordeur.items(), key=lambda kv: str(kv[0]))
    ]
    return uitkomsten, scope_meldingen


def bulk_instellen(
    *,
    administratie_ids: list[uuid.UUID],
    lagen: list[LaagInput],
    scope_toevoegen: bool,
    actor_id: uuid.UUID,
    actor_rol: str,
) -> list[BulkInstelUitkomst]:
    """Toepassen: per administratie éérst de ontbrekende scopes (Beheerder-exclusief — de router
    poort dit endpoint op require_beheerder; de aanmaak audit via de DB-trigger oud→nieuw),
    dan de bestaande configuratieroute (vervallen-patroon + audits inbegrepen). Elke
    administratie in een eigen transactiegang: een deelfout is per BV zichtbaar in de uitkomst
    ('fout' mét reden) en raakt de rest niet — nooit stil half."""
    _vereis_kantoor(actor_rol)
    accordeur_namen = _valideer_bulk_lagen(lagen)
    uitkomsten: list[BulkInstelUitkomst] = []
    for administratie_id in administratie_ids:
        evaluatie = _bulk_evalueer_administratie(
            administratie_id=administratie_id,
            actor_id=actor_id,
            lagen=lagen,
            accordeur_namen=accordeur_namen,
            scope_toevoegen=scope_toevoegen,
        )
        if evaluatie.uitkomst.uitkomst == "overgeslagen":
            uitkomsten.append(evaluatie.uitkomst)
            continue
        try:
            from app.auth import service as auth_service

            for accordeur_id in evaluatie.ontbrekende_scope_ids:
                auth_service.voeg_scope_toe(
                    actor_id=actor_id, doel_gebruiker_id=accordeur_id, administratie_id=administratie_id
                )
            rondes = instellingen_opslaan(
                administratie_id=administratie_id,
                actor_id=actor_id,
                actor_rol=actor_rol,
                ingeschakeld=True,
                lagen=lagen,
            )
            uitkomsten.append(
                replace(evaluatie.uitkomst, rondes_herberekend=rondes.herberekend, rondes_vervallen=rondes.vervallen)
            )
        except Exception as exc:  # noqa: BLE001 — deelfout per BV zichtbaar, nooit stil half
            logger.exception("Bulk klant-accordering instellen faalde voor %s", administratie_id)
            uitkomsten.append(
                BulkInstelUitkomst(
                    administratie_id=administratie_id,
                    administratie_naam=evaluatie.uitkomst.administratie_naam,
                    uitkomst="fout",
                    reden=str(exc) or exc.__class__.__name__,
                )
            )
    return uitkomsten


def alle_accordeur_kandidaten() -> list[AccordeurKandidaat]:
    """Keuzelijst voor de bulk-dialoog (Beheerder-only via de router): álle actieve
    klant-accordeurs, platform-breed — de scope kan immers nog ontbreken (dat is precies wat
    de scope-vink oplost). Alleen id + naam (dataminimalisatie)."""
    from app.db.models import GebruikerStatus

    with scoped_session(None) as session:
        rijen = session.execute(
            select(Gebruiker.id, Gebruiker.naam).where(
                Gebruiker.status == GebruikerStatus.ACTIEF,
                Gebruiker.rol == GebruikerRol.KLANT_ACCORDEUR,
            )
        ).all()
    return sorted((AccordeurKandidaat(id=rij.id, naam=rij.naam) for rij in rijen), key=lambda k: k.naam.lower())


# --- aanbieden -----------------------------------------------------------------------------------


def _afdeling_gelijk(kolom, afdeling_id: uuid.UUID | None):  # noqa: ANN001, ANN202 — SQLAlchemy-expressie
    """NULL-veilige gelijkheid op een afdeling-kolom (blok A 28-08)."""
    return kolom.is_(None) if afdeling_id is None else kolom == afdeling_id


def _als_decimal(waarde: object) -> Decimal | None:
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde))
    except InvalidOperation:
        return None


def bied_ter_accordering_aan(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_rol: str,
    match_afwijking_bevestigd: bool = False,
    materiaal_afwijking_bevestigd: bool = False,
) -> AkkoordResultaat:
    """De "Ter accordering"-knop (kantoor): bevriest de actieve lagen tot stappen (drempel op
    het totaalbedrag; onbekend bedrag = vereist, fail-closed), zet het document op
    ter_accordering en past daarna staande goedkeuringen toe — zijn álle stappen daarmee al
    akkoord, dan boekt de motor direct (met alle harde checks).

    VERPLICHTINGEN (offerte/prijsopgave/opdrachtbevestiging, wens Peter 04-09, ⑥): exact dezelfde
    lagen/drempels/app, maar met de VERPLICHTING-checks, het bedrag exclusief btw als
    drempelbedrag, zónder factuurmatch-/materiaal-/doorbelasting-poorten (die gaan over facturen)
    en zónder staande goedkeuringen. Ná het laatste akkoord volgt géén boeking maar de terminale
    status `geaccordeerd` — zie `_rond_af_verplichting`."""
    _vereis_kantoor(actor_rol)
    if not is_accordering_ingeschakeld(administratie_id=administratie_id):
        raise AccorderingUitgeschakeld("Accordering staat uit voor deze administratie")

    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        is_verplichting = document.soort == DocumentSoort.VERPLICHTING.value
        status_vooraf = document.status

    if not is_verplichting:
        # Factuurmatch-poort (fase 2, besluit 2): een match-afwijking vraagt de expliciete
        # kantoor-bevestiging al bij het AANBIEDEN — de klant-accordeur is niet degene die de
        # urenmatch beoordeelt, en het boeken ná het laatste akkoord (systeem-actor) leunt op de
        # hier persistent vastgelegde bevestiging (migratie 0058). Zelfde 409-vorm als de
        # boek-route (router vertaalt MatchAfwijkingBevestigingVereist).
        boeken_service.toets_match_afwijking_poort(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor_id,
            bevestigd=match_afwijking_bevestigd,
        )
        from app.materiaal.match import toets_materiaalmatch_poort  # D6, zelfde poort-vorm

        toets_materiaalmatch_poort(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor_id,
            bevestigd=materiaal_afwijking_bevestigd,
        )

    # De "Ter accordering"-knop vervangt de boekknop op het controlescherm — dus ook vanaf
    # te_controleren/handmatig_afmaken, mét exact dezelfde checks-poort als boek_document:
    # een document met blokkerende checks gaat nooit naar de klant.
    if status_vooraf in (DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN):
        if is_verplichting:
            from app.verplichting import service as verplichting_service

            rapport = verplichting_service.voer_checks_uit(
                administratie_id=administratie_id, document_id=document_id
            )
        else:
            from app.documenten.boeken import _port_voor
            from app.documenten.boekvoorstel import voer_checks_uit

            with _port_voor(administratie_id) as port:
                rapport = voer_checks_uit(
                    administratie_id=administratie_id, document_id=document_id, client=port.leesclient()
                )
        if rapport.geblokkeerd:
            raise ChecksNietGroen(rapport)
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            document = session.get(Document, document_id)
            assert document is not None
            if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
                _schrijf_overgang(
                    session,
                    document=document,
                    naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                    actor_id=actor_id,
                    detail={"harde_checks": "doorstaan"},
                )

    if not is_verplichting:
        # Klaargezette doorbelasting (besluit 25-08, A2/A3): boek-checks én doorbelasting-checks
        # moeten samen groen zijn vóór het document naar de klant gaat — de accordeur ziet de
        # verdeling alleen-lezen en ná het laatste akkoord boekt alles in één gang. Lazy import.
        from app.doorbelasting import orkestratie

        try:
            orkestratie.toets_klaargezette_doorbelasting(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
            )
        except orkestratie.DoorbelastingChecksNietGroen as exc:
            raise ChecksNietGroen(exc.rapport) from exc

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
            raise DocumentNietAanbiedbaar(
                f"Document staat op {document.status.value} — alleen een boekklaar document kan ter accordering"
            )
        if _open_accordering(session, document_id) is not None:
            raise OngeldigeAanbieding("Er loopt al een accorderingsronde voor dit document")
        # Punt 24 (opruimrun 28-08): een compleet, nog niet verzilverd klant-akkoord vraagt om BOEKEN,
        # niet om een tweede ronde — zelfde poort voor de losse knop én de bulk-route.
        if klant_akkoord_compleet_onverzilverd(session, document_id=document_id):
            raise KlantAkkoordAlCompleet(
                "Klant-akkoord is al compleet voor dit document — boek het direct (opnieuw aanbieden "
                "zou de klant een tweede keer om hetzelfde akkoord vragen)"
            )
        # Blok 4 (08-09, besluit Peter): leverancier met IC-vlag → géén ronde; het document gaat direct de
        # bestaande boekstap in (zelfde poorten/checks als "Boeken (+ doorbelasten)", actor = de mens die klikte).
        # Geen opt-in, geen knop — de knop op het controlescherm zegt al "Boeken"; deze tak vangt de bulk-route
        # en een verouderd scherm. De tijdlijn-/auditregel schrijft de boekmotor zelf (poort).
        overgeslagen = (
            None
            if is_verplichting
            else accordering_overgeslagen(session, administratie_id=administratie_id, document_id=document_id)
        )

    if overgeslagen is not None:
        return _boek_direct_zonder_ronde(administratie_id=administratie_id, document_id=document_id, actor_id=actor_id)

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None

        if is_verplichting:
            # Verplichting (04-09): het drempelbedrag is het totaalbedrag EXCLUSIEF btw uit de
            # verplichting-rij (de accordeur beoordeelt precies dát bedrag) en de crediteur komt
            # daar ook uit — een verplichting heeft geen boekvoorstel. Onbekend bedrag = laag
            # vereist (fail-closed, zelfde regel als bij facturen).
            from app.verplichting.models import Verplichting

            verplichting_rij = session.get(Verplichting, document_id)
            totaalbedrag = _als_decimal(verplichting_rij.totaalbedrag_excl) if verplichting_rij else None
            vendor_id = verplichting_rij.vendor_id if verplichting_rij else None
            voorstel = None
        else:
            voorstel = session.get(Boekvoorstel, document_id)
            totaalbedrag = _als_decimal(voorstel.totaalbedrag) if voorstel else None
            vendor_id = voorstel.vendor_id if voorstel else None

        # Route per afdeling (blok A 28-08): een gekozen afdeling vervángt de administratie-route;
        # de terugval-afdeling "Algemeen" volgt de administratie-route. Een afdeling zónder eigen
        # route = expliciete fout (nooit stil op de administratie-route terugvallen).
        # Een verplichting kent geen afdeling-keuze (geen boekvoorstel) — de administratie-route geldt.
        afdeling_id = voorstel.afdeling_id if voorstel else None
        afdeling = session.get(Afdeling, afdeling_id) if afdeling_id is not None else None
        administratie_rij = session.get(Administratie, administratie_id)
        if administratie_rij is not None and administratie_rij.afdelingen_ingeschakeld and not is_verplichting:
            # Afdeling-poort óók vanaf klaar_om_te_boeken (de checks-poort hierboven draait alleen
            # vanaf te_controleren): een document zonder actieve afdeling gaat nooit naar de klant.
            from app.documenten.checks import CheckRapport, check_afdeling

            afdeling_check = check_afdeling(
                afdelingen_ingeschakeld=True,
                afdeling_id=afdeling_id,
                afdeling_actief=afdeling.actief if afdeling is not None else None,
                afdeling_naam=afdeling.naam if afdeling is not None else None,
                administratie_naam=administratie_rij.naam,
            )
            if not afdeling_check.ok:
                raise ChecksNietGroen(CheckRapport((afdeling_check,)))
        route_afdeling_id = afdeling_id if (afdeling is not None and not afdeling.is_terugval) else None
        lagen = _actieve_lagen(session, administratie_id=administratie_id, afdeling_id=route_afdeling_id)
        if not lagen:
            if route_afdeling_id is not None:
                raise GeenLagenIngesteld(
                    f"Geen accorderingsroute ingesteld voor afdeling '{afdeling.naam}' — stel die in op "
                    f"Instellingen › Administraties"
                )
            raise GeenLagenIngesteld("Geen accorderingslagen ingesteld voor deze administratie")

        accordering = DocumentAccordering(
            administratie_id=administratie_id,
            document_id=document_id,
            aangeboden_door=actor_id,
            detail={
                # `soort` op de ronde (04-09): de vervolgpaden (staande regels, afronden) vertakken
                # hierop zonder het document opnieuw te hoeven lezen.
                "soort": document.soort,
                "totaalbedrag": str(totaalbedrag) if totaalbedrag is not None else None,
                "vendor_id": str(vendor_id) if vendor_id else None,
                "afdeling_id": str(afdeling_id) if afdeling_id else None,
                "afdeling_naam": afdeling.naam if afdeling is not None else None,
            },
        )
        session.add(accordering)
        session.flush()
        for laag in lagen:
            # Drempel: laag geldt alleen bóven het bedrag; onbekend totaalbedrag = vereist
            # (fail-closed — bij twijfel wél een mens laten kijken).
            vereist = laag.bedrag_drempel is None or totaalbedrag is None or abs(totaalbedrag) > laag.bedrag_drempel
            session.add(
                AccorderingStap(
                    administratie_id=administratie_id,
                    accordering_id=accordering.id,
                    volgnummer=laag.volgnummer,
                    accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
                    bedrag_drempel=laag.bedrag_drempel,
                    vereist=vereist,
                )
            )
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.TER_ACCORDERING,
            actor_id=actor_id,
            detail={
                "accordering_id": str(accordering.id),
                "lagen": len(lagen),
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document_accordering",
            record_id=accordering.id,
            actie="ter_accordering_aangeboden",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"document_id": str(document_id), "lagen": len(lagen)},
            administratie_id=administratie_id,
        )
        accordering_id = accordering.id

    # Staande goedkeuringen toepassen (autonoom, ná de aanbied-transactie): elke vereiste stap
    # waarvoor een actieve regel (accordeur + vendor + exact bedrag) bestaat krijgt automatisch
    # akkoord — mét audit + tijdlijn. Alles akkoord → direct boeken.
    return _pas_staande_regels_toe_en_rond_af(
        administratie_id=administratie_id, accordering_id=accordering_id, document_id=document_id
    )


def _boek_direct_zonder_ronde(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> AkkoordResultaat:
    """Blok 4 (08-09): de "Ter accordering"-knop op een IC-document = de bestaande boekstap (mét klaargezette
    doorbelasting in één gang, zoals `_boek_na_laatste_akkoord`) door de mens-actor. Check-blokkades reizen als
    ChecksNietGroen (zelfde 409-vorm als aanbieden); elke andere boekfout (toggle uit, volumerem, RLZ) komt als
    zichtbare `boek_fout` terug — nooit stil, nooit een 500 op een akkoord-knop. De IC-tijdlijnregel + audit
    schrijft de boekmotor ín de poort (`registreer_accordering_overgeslagen`)."""
    from app.doorbelasting import orkestratie

    geboekt = False
    boek_fout: str | None = None
    try:
        gecombineerd = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
        )
        geboekt = True
        if gecombineerd.doorbelasting_fout:
            boek_fout = "Inkoopfactuur geboekt; doorbelasting (deels) mislukt: " + gecombineerd.doorbelasting_fout
    except orkestratie.DoorbelastingChecksNietGroen as exc:
        raise ChecksNietGroen(exc.rapport) from exc
    except boeken_service.BoekenGeblokkeerdDoorChecks as exc:
        raise ChecksNietGroen(exc.rapport) from exc
    except boeken_service.OngeldigeBoekpoging:
        raise
    except boeken_service.BoekenFout as exc:
        boek_fout = str(exc)
        logger.warning("Intercompany-document %s: accordering overgeslagen, boeken mislukt: %s", document_id, boek_fout)
    return AkkoordResultaat(
        accordering=None,
        alles_akkoord=True,
        geboekt=geboekt,
        boek_fout=boek_fout,
        staande_regel_id=None,
        overgeslagen_reden=OVERGESLAGEN_REDEN_INTERCOMPANY,
    )


@dataclass(frozen=True)
class BulkAanbiedResultaat:
    """Uitkomst per document van de bulk-actie "Ter accordering aanbieden" (punt 2b):
    `aangeboden` (ronde open), `geboekt` (staande goedkeuringen dekten alles → direct geboekt),
    `overgeslagen` (poort weigerde — reden in leesbare taal, nooit stil)."""

    document_id: uuid.UUID
    bestandsnaam: str | None
    uitkomst: str
    reden: str | None
    boek_fout: str | None = None


def bulk_aanbieden(
    *,
    administratie_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    actor_id: uuid.UUID,
    actor_rol: str,
) -> list[BulkAanbiedResultaat]:
    """Bulk "Ter accordering aanbieden" vanaf de documentenlijst (werkstroom-run 27/28-08, punt 2b —
    herstelroute ná vervallen rondes). Exact dezelfde poorten als de losse knop: per document
    `bied_ter_accordering_aan` in zijn eigen transactie(s); een geweigerd document wordt
    overgeslagen mét de reden en blokkeert de rest niet. Bevestigingsvlaggen (match-/materiaal-
    afwijking) worden hier bewust NIET gezet — zo'n document valt op "overgeslagen" en vraagt de
    expliciete kantoor-bevestiging op het controlescherm. Volgorde = aangeleverde volgorde;
    dubbele id's één keer."""
    _vereis_kantoor(actor_rol)
    from app.materiaal.match import MateriaalAfwijkingBevestigingVereist

    namen: dict[uuid.UUID, str] = {}
    with scoped_session(administratie_id) as session:
        for rij in session.execute(select(Document.id, Document.bestandsnaam).where(Document.id.in_(document_ids))):
            namen[rij.id] = rij.bestandsnaam

    resultaten: list[BulkAanbiedResultaat] = []
    gezien: set[uuid.UUID] = set()
    for document_id in document_ids:
        if document_id in gezien:
            continue
        gezien.add(document_id)
        naam = namen.get(document_id)
        try:
            uitkomst = bied_ter_accordering_aan(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=actor_id,
                actor_rol=actor_rol,
            )
        except DocumentNietGevonden:
            resultaten.append(
                BulkAanbiedResultaat(document_id, naam, "overgeslagen", "Document niet gevonden in deze administratie")
            )
        except ChecksNietGroen as exc:
            rood = [r.melding for r in exc.rapport.resultaten if not r.ok]
            resultaten.append(
                BulkAanbiedResultaat(
                    document_id, naam, "overgeslagen", "Harde checks niet groen: " + ("; ".join(rood) or "geblokkeerd")
                )
            )
        except boeken_service.MatchAfwijkingBevestigingVereist:
            resultaten.append(
                BulkAanbiedResultaat(
                    document_id,
                    naam,
                    "overgeslagen",
                    "Urenmatch wijkt af — bevestig dit expliciet op het controlescherm",
                )
            )
        except MateriaalAfwijkingBevestigingVereist:
            resultaten.append(
                BulkAanbiedResultaat(
                    document_id,
                    naam,
                    "overgeslagen",
                    "Materiaalmatch wijkt af — bevestig dit expliciet op het controlescherm",
                )
            )
        except boeken_service.OngeldigeBoekpoging as exc:
            resultaten.append(BulkAanbiedResultaat(document_id, naam, "overgeslagen", str(exc)))
        except KantoorActieVereist:
            raise
        except AccorderingFout as exc:
            resultaten.append(BulkAanbiedResultaat(document_id, naam, "overgeslagen", str(exc)))
        else:
            if uitkomst.overgeslagen_reden is not None:
                # Blok 4 (08-09): IC-document — geen ronde; geboekt, of zichtbaar overgeslagen mét boekfout als reden.
                resultaten.append(
                    BulkAanbiedResultaat(
                        document_id,
                        naam,
                        "geboekt" if uitkomst.geboekt else "overgeslagen",
                        (
                            "intercompany — klant-accordering overgeslagen (leveranciersregel)"
                            if uitkomst.geboekt
                            else f"intercompany — klant-accordering overgeslagen, boeken mislukt: {uitkomst.boek_fout}"
                        ),
                        boek_fout=uitkomst.boek_fout,
                    )
                )
                continue
            resultaten.append(
                BulkAanbiedResultaat(
                    document_id,
                    naam,
                    "geboekt" if uitkomst.geboekt else "aangeboden",
                    None,
                    boek_fout=uitkomst.boek_fout,
                )
            )
    return resultaten


def _pas_staande_regels_toe_en_rond_af(
    *, administratie_id: uuid.UUID, accordering_id: uuid.UUID, document_id: uuid.UUID
) -> AkkoordResultaat:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        accordering = session.get(DocumentAccordering, accordering_id)
        assert accordering is not None
        detail = accordering.detail or {}
        vendor_id = detail.get("vendor_id")
        totaalbedrag = _als_decimal(detail.get("totaalbedrag"))
        ronde_afdeling_id = _ronde_afdeling_id(accordering)
        stappen = _stappen_van(session, accordering_id)
        # Verplichtingen (⑥, besluit Peter 04-09): staande goedkeuring is UITGESLOTEN — een offerte
        # is per definitie een nieuw aanbod, dus nooit "voortaan automatisch bij dit bedrag".
        if detail.get("soort") == DocumentSoort.VERPLICHTING.value:
            vendor_id = None

        if vendor_id and totaalbedrag is not None:
            document = session.get(Document, document_id)
            for stap in sorted(stappen, key=lambda s: s.volgnummer):
                if not stap.vereist or stap.besluit is not None:
                    continue
                regel = session.scalars(
                    select(StaandeGoedkeuring).where(
                        StaandeGoedkeuring.administratie_id == administratie_id,
                        StaandeGoedkeuring.accordeur_gebruiker_id == stap.accordeur_gebruiker_id,
                        StaandeGoedkeuring.vendor_id == uuid.UUID(vendor_id),
                        StaandeGoedkeuring.bedrag == totaalbedrag,
                        StaandeGoedkeuring.actief.is_(True),
                        # Blok A 28-08: een staande goedkeuring telt alleen binnen de afdeling
                        # waar ze is afgegeven (NULL = zonder afdeling afgegeven).
                        _afdeling_gelijk(StaandeGoedkeuring.afdeling_id, ronde_afdeling_id),
                    )
                ).first()
                if regel is None:
                    break  # sequentieel: zonder automatisch akkoord stopt de keten hier
                stap.besluit = StapBesluit.AKKOORD.value
                stap.besluit_bron = StapBesluitBron.STAANDE_REGEL.value
                stap.staande_regel_id = regel.id
                stap.besloten_op = datetime.now(UTC)
                record_audit_event(
                    session,
                    actor_id=SYSTEEM_ACTOR_ID,
                    module="boekhouding",
                    tabel="accordering_stap",
                    record_id=stap.id,
                    actie="accordering_automatisch_akkoord_staande_regel",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "document_id": str(document_id),
                        "laag": stap.volgnummer,
                        "staande_regel_id": str(regel.id),
                        "accordeur": str(stap.accordeur_gebruiker_id),
                        "bedrag": str(totaalbedrag),
                    },
                    administratie_id=administratie_id,
                )
                # Tijdlijn-vermelding zonder statusovergang (zelfde patroon als afwijs-historie).
                if document is not None:
                    from app.documenten.models import DocumentGebeurtenis

                    session.add(
                        DocumentGebeurtenis(
                            id=uuid.uuid4(),
                            document_id=document_id,
                            van_status=document.status,
                            naar_status=document.status,
                            actor_id=SYSTEEM_ACTOR_ID,
                            detail={
                                "accordering_automatisch_akkoord": {
                                    "laag": stap.volgnummer,
                                    "staande_regel_id": str(regel.id),
                                    "accordeur": str(stap.accordeur_gebruiker_id),
                                }
                            },
                        )
                    )

        alles_akkoord = _eerstvolgende_open_stap(stappen) is None
        data = _naar_data(session, accordering, stappen)

    if not alles_akkoord:
        return AkkoordResultaat(
            accordering=data, alles_akkoord=False, geboekt=False, boek_fout=None, staande_regel_id=None
        )
    return _rond_af_en_boek(administratie_id=administratie_id, accordering_id=accordering_id)


# --- besluiten (accordeur) -----------------------------------------------------------------------


def _laatste_accordering(
    session: Session, document_id: uuid.UUID, *, vergrendel: bool = False
) -> DocumentAccordering | None:
    """`vergrendel=True` (besluit-paden, bugfix-run 28-08 punt 3d): SELECT … FOR UPDATE op de
    laatste ronde — twee gelijktijdige besluiten op hetzelfde document (verzendrij-retry,
    dubbeltik) serialiseren dan op de rij; de tweede ziet het eerste besluit en valt in het
    idempotente `_herhaald_besluit`-pad i.p.v. een tweede boekronde of dubbel audit-spoor."""
    stmt = (
        select(DocumentAccordering)
        .where(DocumentAccordering.document_id == document_id)
        .order_by(DocumentAccordering.aangeboden_op.desc())
        .limit(1)
    )
    if vergrendel:
        stmt = stmt.with_for_update()
    return session.scalars(stmt).first()


def _herhaald_besluit(
    session: Session, *, document_id: uuid.UUID, actor_id: uuid.UUID, besluit: StapBesluit
) -> tuple[DocumentAccordering, list[AccorderingStap]] | None:
    """Idempotentie-anker voor het optimistische PWA-pad (kernprincipe 5, snelheidslaag
    2026-08-17): de PWA verstuurt besluiten op de achtergrond mét retry — een herhaalde POST
    (eerste response verloren, bv. timeout terwijl de boekmotor nog draaide) mag nooit
    stuklopen op NietAanDeBeurt/GeenOpenAccordering en nooit dubbel doorwerken (geen tweede
    staande regel, geen tweede boekronde, geen dubbel audit-event). Alleen de LAATSTE
    accorderingsronde telt: een later opnieuw aangeboden document begint een verse ronde en
    die vraagt gewoon een nieuw besluit."""
    laatste = _laatste_accordering(session, document_id, vergrendel=True)
    if laatste is None:
        return None
    stappen = _stappen_van(session, laatste.id)
    for stap in stappen:
        if (
            stap.accordeur_gebruiker_id == actor_id
            and stap.besluit == besluit.value
            and stap.besluit_bron == StapBesluitBron.HANDMATIG.value
        ):
            return laatste, stappen
    return None


def _stap_aan_de_beurt_voor(
    session: Session, *, document_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[DocumentAccordering, AccorderingStap, list[AccorderingStap]]:
    accordering = _open_accordering(session, document_id)
    if accordering is None:
        raise GeenOpenAccordering("Er loopt geen accorderingsronde voor dit document")
    stappen = _stappen_van(session, accordering.id)
    volgende = _eerstvolgende_open_stap(stappen)
    if volgende is None:
        raise GeenOpenAccordering("Alle lagen zijn al besloten")
    if volgende.accordeur_gebruiker_id != actor_id:
        raise NietAanDeBeurt("Deze factuur wacht op een andere accordeur (sequentiële lagen)")
    return accordering, volgende, stappen


def geef_akkoord(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    staande_regel_aanmaken: bool = False,
    staande_regel_voorstel_antwoord: str | None = None,
) -> AkkoordResultaat:
    """Akkoord van de accordeur die aan de beurt is. `staande_regel_aanmaken` legt het besluit
    2026-08-08 vast: akkoord voor toekomstige facturen van deze leverancier bij exact dit
    bedrag (zichtbaar + intrekbaar; harde checks blijven onverkort).
    `staande_regel_voorstel_antwoord` (blok 7 11-09) = het antwoord op het voorstel in de app, in dezelfde call:
    'ja' (= aanmaken), 'niet_nu' → 90 dagen stil voor deze accordeur + leverancier, 'nooit' → uitzondering per
    leverancier; None = de vraag is niet gesteld. Bestaande aanroepers zonder antwoord gedragen zich ongewijzigd."""
    staande_regel_id: uuid.UUID | None = None
    if staande_regel_voorstel_antwoord is not None and staande_regel_voorstel_antwoord not in VOORSTEL_ANTWOORDEN:
        raise AccorderingFout(
            f"Onbekend antwoord op het staande-goedkeuring-voorstel: {staande_regel_voorstel_antwoord}"
        )
    if staande_regel_voorstel_antwoord == "ja":
        staande_regel_aanmaken = True
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        herhaald = _herhaald_besluit(session, document_id=document_id, actor_id=actor_id, besluit=StapBesluit.AKKOORD)
        if herhaald is not None:
            # Herhaalde POST van een al vastgelegd akkoord: huidige stand teruggeven, niets
            # opnieuw doen. `geboekt` uit de werkelijke documentstatus; een eventueel bij de
            # eerste call aangemaakte staande regel wordt teruggevonden, nooit gedupliceerd.
            laatste, laatste_stappen = herhaald
            bestaande_regel = session.scalars(
                select(StaandeGoedkeuring).where(
                    StaandeGoedkeuring.bron_document_id == document_id,
                    StaandeGoedkeuring.accordeur_gebruiker_id == actor_id,
                )
            ).first()
            document = session.get(Document, document_id)
            return AkkoordResultaat(
                accordering=_naar_data(session, laatste, laatste_stappen),
                alles_akkoord=laatste.status == AccorderingStatus.AFGEROND.value,
                geboekt=document is not None and document.status == DocumentStatus.GEBOEKT.value,
                boek_fout=None,
                staande_regel_id=bestaande_regel.id if bestaande_regel is not None else None,
            )
        accordering, stap, stappen = _stap_aan_de_beurt_voor(session, document_id=document_id, actor_id=actor_id)
        stap.besluit = StapBesluit.AKKOORD.value
        stap.besluit_bron = StapBesluitBron.HANDMATIG.value
        stap.besloten_op = datetime.now(UTC)

        detail = accordering.detail or {}
        if staande_regel_aanmaken:
            if detail.get("soort") == DocumentSoort.VERPLICHTING.value:
                # ⑥ (besluit Peter 04-09): een offerte is altijd een nieuw aanbod — nooit een
                # staande goedkeuring. De app biedt 'm niet aan; deze poort is het vangnet.
                raise StaandeRegelNietMogelijk(
                    "Een staande goedkeuring bestaat niet voor offertes/prijsopgaven — elk aanbod "
                    "wordt afzonderlijk goedgekeurd"
                )
            vendor_id = detail.get("vendor_id")
            totaalbedrag = _als_decimal(detail.get("totaalbedrag"))
            if not vendor_id or totaalbedrag is None:
                raise StaandeRegelNietMogelijk(
                    "Zonder leverancier of totaalbedrag kan er geen staande goedkeuring vastgelegd worden"
                )
            vendor = session.get(VendorCache, (uuid.UUID(vendor_id), administratie_id))
            regel = StaandeGoedkeuring(
                administratie_id=administratie_id,
                accordeur_gebruiker_id=actor_id,
                vendor_id=uuid.UUID(vendor_id),
                leverancier_naam=vendor.naam if vendor else None,
                bedrag=totaalbedrag,
                bron_document_id=document_id,
                afdeling_id=_ronde_afdeling_id(accordering),
            )
            session.add(regel)
            session.flush()
            staande_regel_id = regel.id
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="staande_goedkeuring",
                record_id=regel.id,
                actie="staande_goedkeuring_aangemaakt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "vendor_id": vendor_id,
                    "leverancier": regel.leverancier_naam,
                    "bedrag": str(totaalbedrag),
                    "bron_document_id": str(document_id),
                },
                administratie_id=administratie_id,
            )

        if staande_regel_voorstel_antwoord in ("niet_nu", "nooit") and detail.get("vendor_id"):
            _leg_voorstel_stilte_vast(
                session,
                administratie_id=administratie_id,
                accordeur_gebruiker_id=actor_id,
                vendor_id=uuid.UUID(str(detail["vendor_id"])),
                soort=(
                    VoorstelStilSoort.NOOIT
                    if staande_regel_voorstel_antwoord == "nooit"
                    else VoorstelStilSoort.STIL_TOT
                ),
                reden=f"antwoord '{staande_regel_voorstel_antwoord}' in de accordeur-app bij document {document_id}",
                actor_id=actor_id,
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="accordering_stap",
            record_id=stap.id,
            actie="accordering_akkoord",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "document_id": str(document_id),
                "laag": stap.volgnummer,
                "staande_regel_id": str(staande_regel_id) if staande_regel_id else None,
                "staande_regel_voorstel_antwoord": staande_regel_voorstel_antwoord,
            },
            administratie_id=administratie_id,
        )
        # Tijdlijn-vermelding zonder statusovergang.
        document = session.get(Document, document_id)
        if document is not None:
            from app.documenten.models import DocumentGebeurtenis

            session.add(
                DocumentGebeurtenis(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    van_status=document.status,
                    naar_status=document.status,
                    actor_id=actor_id,
                    detail={"accordering_akkoord": {"laag": stap.volgnummer}},
                )
            )
        alles_akkoord = _eerstvolgende_open_stap(stappen) is None
        accordering_id = accordering.id
        data = _naar_data(session, accordering, stappen)

    if not alles_akkoord:
        return AkkoordResultaat(
            accordering=data, alles_akkoord=False, geboekt=False, boek_fout=None, staande_regel_id=staande_regel_id
        )
    resultaat = _rond_af_en_boek(administratie_id=administratie_id, accordering_id=accordering_id)
    return AkkoordResultaat(
        accordering=resultaat.accordering,
        alles_akkoord=True,
        geboekt=resultaat.geboekt,
        boek_fout=resultaat.boek_fout,
        staande_regel_id=staande_regel_id,
    )


BOEK_NA_AKKOORD_REDEN = "alle lagen akkoord — boeken gestart"


def _rond_af_en_boek(*, administratie_id: uuid.UUID, accordering_id: uuid.UUID) -> AkkoordResultaat:
    """Ná het laatste akkoord: ronde afronden en de bestaande boekmotor draaien — MET alle harde
    checks (CLAUDE.md, hard). Het document BLIJFT op ter_accordering tot de boeking staat
    (bugfix-run 28-08; vóór die fix ging het éérst naar klaar_om_te_boeken en bleef het dáár
    stil hangen zodra de boekpoging faalde — de fout leefde alleen in de HTTP-response aan de
    accordeur). Een geblokkeerde check, toggle, volumerem of RLZ-fout is nu zichtbaar op de
    ronde (`boek_fout`), op de tijdlijn (reden) en in de documentenlijst, nooit stil.

    Race-vangnet (3d): de ronde wordt FOR UPDATE gelezen; is zij al afgerond door een
    gelijktijdige request, dan geeft dit pad de huidige stand terug zonder tweede boekpoging."""
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        accordering = session.scalars(
            select(DocumentAccordering).where(DocumentAccordering.id == accordering_id).with_for_update()
        ).one()
        document_id = accordering.document_id
        if accordering.status != AccorderingStatus.OPEN.value:
            stappen = _stappen_van(session, accordering_id)
            document = session.get(Document, document_id)
            boek_fout, _ = _boek_fout_van(accordering)
            return AkkoordResultaat(
                accordering=_naar_data(session, accordering, stappen),
                alles_akkoord=accordering.status == AccorderingStatus.AFGEROND.value,
                geboekt=document is not None and document.status == DocumentStatus.GEBOEKT.value,
                boek_fout=boek_fout,
                staande_regel_id=None,
            )
        accordering.status = AccorderingStatus.AFGEROND.value
        accordering.afgerond_op = datetime.now(UTC)
        document = session.get(Document, document_id)
        assert document is not None
        # Verplichting (04-09): ná het laatste akkoord volgt géén boeking maar de terminale status
        # `geaccordeerd` (zie `_rond_af_verplichting`) — de soort staat op de ronde én, fail-safe,
        # op het document zelf.
        is_verplichting_ronde = (
            (accordering.detail or {}).get("soort") == DocumentSoort.VERPLICHTING.value
            or document.soort == DocumentSoort.VERPLICHTING.value
        )
        # Tijdlijn-notitie zónder statusovergang: het document blijft bij de klant-status tot de
        # boeking staat; de motor zelf schrijft de echte overgangen (mét reden).
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=document_id,
                van_status=document.status,
                naar_status=document.status,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={
                    "accordering_id": str(accordering_id),
                    "alle_lagen_akkoord": True,
                    "reden": BOEK_NA_AKKOORD_REDEN,
                },
            )
        )
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document_accordering",
            record_id=accordering_id,
            actie="accordering_afgerond",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"document_id": str(document_id)},
            administratie_id=administratie_id,
        )
        # Open-vraag-poort (blok B5 26-08): een open vraag blokkeert het BOEKEN, niet het akkoord.
        # Ligt er nog een open dialoog (bv. aan de accordeur zelf, gesteld terwijl het document bij
        # de klant lag), dan boeken we NIET maar zetten het document zichtbaar op vraag_open met
        # herkomst klaar_om_te_boeken — "Afgehandeld" door de vraagsteller brengt het terug en
        # het kantoor boekt dan via de normale route. Nooit stil (beide overgangen mét reden).
        open_vraag = session.scalars(
            select(Vraag).where(Vraag.document_id == document_id, Vraag.status == VraagStatus.OPEN.value)
        ).first()
        open_vraag_fout: str | None = None
        if open_vraag is not None:
            open_vraag_fout = (
                "Alle lagen akkoord; boeken wacht op het afhandelen van de open vraag "
                f"(vraag {open_vraag.id}) door de vraagsteller"
            )
            open_vraag.status_voor_vraag = DocumentStatus.KLAAR_OM_TE_BOEKEN.value
            _schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"accordering_id": str(accordering_id), "alle_lagen_akkoord": True, "reden": open_vraag_fout},
            )
            _schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.VRAAG_OPEN,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"vraag_id": str(open_vraag.id), "boeken_wacht_op_open_vraag": True, "reden": open_vraag_fout},
            )
            document.toegewezen_aan = open_vraag.aan_de_beurt or open_vraag.toegewezen_aan

    if open_vraag_fout is not None:
        logger.info("Accordering %s afgerond; %s", accordering_id, open_vraag_fout)
        with scoped_session(administratie_id) as session:
            accordering = session.get(DocumentAccordering, accordering_id)
            assert accordering is not None
            stappen = _stappen_van(session, accordering_id)
            data = _naar_data(session, accordering, stappen)
        return AkkoordResultaat(
            accordering=data, alles_akkoord=True, geboekt=False, boek_fout=open_vraag_fout, staande_regel_id=None
        )

    if is_verplichting_ronde:
        # Verplichting (04-09): géén boeking — de terminale status `geaccordeerd` + het vastgelegde
        # goedgekeurde bedrag (wie/wanneer) zijn het resultaat.
        return _rond_af_verplichting(
            administratie_id=administratie_id, accordering_id=accordering_id, document_id=document_id
        )
    return _boek_na_laatste_akkoord(
        administratie_id=administratie_id, accordering_id=accordering_id, document_id=document_id
    )


def _rond_af_verplichting(
    *, administratie_id: uuid.UUID, accordering_id: uuid.UUID, document_id: uuid.UUID
) -> AkkoordResultaat:
    """Afronding van een VERPLICHTING-ronde (wens Peter 04-09, ①/⑥): het document gaat naar de
    terminale status `geaccordeerd` — bewust GEEN boeking in RLZ/Odoo — en de verplichting-rij legt
    het goedgekeurde bedrag + wie/wanneer vast (dát is het discrepantie-doel). Tijdlijn + audit via
    de bestaande `_schrijf_overgang`; daarna worden de open inkoopdocumenten van deze crediteur
    opnieuw getoetst zodat de nieuwe offerte direct meedoet in de cumulatieve match."""
    from app.verplichting import match_pipeline as verplichting_match
    from app.verplichting import service as verplichting_service

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, document_id)
        assert document is not None
        accordering = session.get(DocumentAccordering, accordering_id)
        assert accordering is not None
        if document.status == DocumentStatus.GEACCORDEERD:
            # Race-/retry-vangnet: al afgerond door een gelijktijdige request.
            stappen = _stappen_van(session, accordering_id)
            return AkkoordResultaat(
                accordering=_naar_data(session, accordering, stappen),
                alles_akkoord=True,
                geboekt=False,
                boek_fout=None,
                staande_regel_id=None,
            )
        bedrag = verplichting_service.leg_goedkeuring_vast_in_sessie(
            session, administratie_id=administratie_id, document_id=document_id, actor_id=SYSTEEM_ACTOR_ID
        )
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.GEACCORDEERD,
            actor_id=SYSTEEM_ACTOR_ID,
            detail={
                "accordering_id": str(accordering_id),
                "verplichting_goedgekeurd_bedrag_excl": str(bedrag) if bedrag is not None else None,
                "reden": "alle lagen akkoord — verplichting goedgekeurd (geen boeking)",
            },
        )
        stappen = _stappen_van(session, accordering_id)
        data = _naar_data(session, accordering, stappen)

    verplichting_match.herbereken_na_verplichting_wijziging_stil(
        administratie_id=administratie_id, verplichting_document_id=document_id
    )
    return AkkoordResultaat(
        accordering=data, alles_akkoord=True, geboekt=False, boek_fout=None, staande_regel_id=None
    )


def _boek_na_laatste_akkoord(
    *, administratie_id: uuid.UUID, accordering_id: uuid.UUID, document_id: uuid.UUID
) -> AkkoordResultaat:
    """De boekpoging ná een AFGERONDE ronde (systeem-actor). Orkestratie (besluit 25-08): mét
    klaargezette doorbelasting boekt alles in één gang (inkoop → verkopen → spiegels); zonder =
    exact de bestaande boek_document-aanroep. ELKE mislukking — verwacht (poort/toggle/volumerem/
    checks/RLZ) of onverwacht (credentials, netwerk, bug) — wordt vastgelegd via
    `_registreer_boek_fout`: nooit een 500 richting de accordeur (zijn akkoord staat en is geldig)
    en nooit een stille uitkomst. Herbruikbaar door de herstelroute (`app/accordering/herstel.py`)
    en de kantoor-retry via POST …/boeken (die loopt door dezelfde poort)."""
    from app.doorbelasting import orkestratie

    geboekt = False
    boek_fout: str | None = None
    try:
        gecombineerd = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id, document_id=document_id, actor_id=SYSTEEM_ACTOR_ID
        )
        geboekt = True
        if gecombineerd.doorbelasting_fout:
            # Inkoop staat geboekt; de doorbelasting-stap faalde zichtbaar (run draagt de fout,
            # herstel via de bestaande doorbelasting-routes) — nooit stil.
            boek_fout = "Inkoopfactuur geboekt; doorbelasting (deels) mislukt: " + gecombineerd.doorbelasting_fout
            logger.warning("Accordering %s: %s", accordering_id, boek_fout)
    except orkestratie.DoorbelastingChecksNietGroen as exc:
        boek_fout = "Boeken geblokkeerd door doorbelasting-checks: " + "; ".join(
            r.melding for r in exc.rapport.resultaten if not r.ok
        )
        logger.warning("Accordering %s afgerond maar boeken geblokkeerd: %s", accordering_id, boek_fout)
    except boeken_service.BoekenGeblokkeerdDoorChecks as exc:
        boek_fout = "Boeken geblokkeerd door harde checks: " + "; ".join(
            r.melding for r in exc.rapport.resultaten if not r.ok
        )
        logger.warning("Accordering %s afgerond maar boeken geblokkeerd: %s", accordering_id, boek_fout)
    except boeken_service.BoekenFout as exc:
        boek_fout = str(exc)
        logger.warning("Accordering %s afgerond maar boeken mislukt: %s", accordering_id, boek_fout)
    except Exception as exc:  # noqa: BLE001 — bewust breed: zie docstring (nooit stil, nooit 500 naar de accordeur)
        boek_fout = f"Onverwachte fout bij het boeken ná het laatste akkoord: {exc}"
        logger.exception("Accordering %s afgerond maar boeken onverwacht mislukt", accordering_id)

    _registreer_boek_fout(
        administratie_id=administratie_id,
        accordering_id=accordering_id,
        document_id=document_id,
        fout=boek_fout,
        geboekt=geboekt,
    )
    with scoped_session(administratie_id) as session:
        accordering = session.get(DocumentAccordering, accordering_id)
        assert accordering is not None
        stappen = _stappen_van(session, accordering_id)
        data = _naar_data(session, accordering, stappen)
    return AkkoordResultaat(
        accordering=data, alles_akkoord=True, geboekt=geboekt, boek_fout=boek_fout, staande_regel_id=None
    )


def _registreer_boek_fout(
    *, administratie_id: uuid.UUID, accordering_id: uuid.UUID, document_id: uuid.UUID, fout: str | None, geboekt: bool
) -> None:
    """Persistente uitkomst van de boekpoging ná het laatste akkoord (bugfix-run 28-08):
    `detail["boek_fout"]` op de ronde (None bij een schone boeking), een tijdlijnregel mét reden
    en een audit-event. Statusregel: is het document tijdens de poging op klaar_om_te_boeken
    gezet (checks doorstaan, daarna toggle/volumerem/RLZ-fout), dan gaat het TERUG naar
    ter_accordering — de werkvoorraad toont het bij "Bij klant" mét de fout, niet als stil
    "klaar om te boeken". Staat het op boeken_mislukt (RLZ-fout — eigen zichtbare status mét
    reden + retry) of nog op ter_accordering (poort vóór de checks), dan volstaat de notitie."""
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        accordering = session.get(DocumentAccordering, accordering_id)
        assert accordering is not None
        detail = dict(accordering.detail or {})
        if fout is None:
            if "boek_fout" in detail:
                detail["boek_fout"] = None
                accordering.detail = detail
            return
        detail["boek_fout"] = {"fout": fout[:1000], "tijdstip": datetime.now(UTC).isoformat(), "geboekt": geboekt}
        accordering.detail = detail
        document = session.get(Document, document_id)
        assert document is not None
        reden = (
            f"inkoop geboekt, doorbelasting mislukt ná het laatste klant-akkoord: {fout}"
            if geboekt
            else f"boeken ná het laatste klant-akkoord mislukt: {fout}"
        )
        gebeurtenis_detail = {
            "accordering_id": str(accordering_id),
            "accordering_boek_fout": fout[:1000],
            "reden": reden,
        }
        if not geboekt and document.status == DocumentStatus.KLAAR_OM_TE_BOEKEN:
            _schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.TER_ACCORDERING,
                actor_id=SYSTEEM_ACTOR_ID,
                detail=gebeurtenis_detail,
            )
        else:
            session.add(
                DocumentGebeurtenis(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    van_status=document.status,
                    naar_status=document.status,
                    actor_id=SYSTEEM_ACTOR_ID,
                    detail=gebeurtenis_detail,
                )
            )
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document_accordering",
            record_id=accordering_id,
            actie="accordering_boek_fout",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "document_id": str(document_id),
                "fout": fout[:1000],
                "inkoop_geboekt": geboekt,
                "documentstatus": document.status.value,
            },
            administratie_id=administratie_id,
        )


def boek_na_afgerond_akkoord(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> AkkoordResultaat:
    """Publieke ingang voor de herstelroute (`app/accordering/herstel.py`): de boekpoging voor een
    document waarvan de LAATSTE ronde al AFGEROND is (akkoorden compleet) maar dat nog niet
    geboekt staat — exact het pad dat ná het laatste akkoord loopt, systeem-actor, alle poorten."""
    with scoped_session(administratie_id) as session:
        laatste = _laatste_accordering(session, document_id)
        if laatste is None or laatste.status != AccorderingStatus.AFGEROND.value:
            raise GeenOpenAccordering("Geen afgeronde accorderingsronde voor dit document")
        accordering_id = laatste.id
    return _boek_na_laatste_akkoord(
        administratie_id=administratie_id, accordering_id=accordering_id, document_id=document_id
    )


def boek_fout_per_document(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Bulk (geen N+1) voor de documentenlijst: per document waarvan de LAATSTE ronde afgerond is
    mét een geregistreerde boekfout → de fouttekst (kolom "Toegewezen" toont "boeken ná akkoord
    mislukt"). Sessie van de aanroeper (al gescoopt)."""
    if not document_ids:
        return {}
    rondes = list(
        session.scalars(
            select(DocumentAccordering)
            .where(DocumentAccordering.document_id.in_(document_ids))
            .order_by(DocumentAccordering.aangeboden_op.asc())
        )
    )
    laatste_per_document: dict[uuid.UUID, DocumentAccordering] = {}
    for ronde in rondes:
        laatste_per_document[ronde.document_id] = ronde  # oplopend → de laatste wint
    resultaat: dict[uuid.UUID, str] = {}
    for document_id, ronde in laatste_per_document.items():
        if ronde.status != AccorderingStatus.AFGEROND.value:
            continue
        fout, _ = _boek_fout_van(ronde)
        if fout:
            resultaat[document_id] = fout
    return resultaat


def wijs_af(*, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str) -> AccorderingData:
    """Afwijzen door de accordeur: verplichte reden (popup-principe), hergebruikt het bestaande
    afwijzen-met-reden-patroon — document eerst zichtbaar terug uit de accordering, dan
    afgewezen (status in de werkvoorraad, met reden; heropenen = kantoorbak)."""
    reden_tekst = reden.strip()
    if not reden_tekst:
        raise RedenVerplicht("Afwijzen zonder reden is niet toegestaan")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        herhaald = _herhaald_besluit(session, document_id=document_id, actor_id=actor_id, besluit=StapBesluit.AFGEWEZEN)
        if herhaald is not None:
            # Herhaalde POST van een al vastgelegde afwijzing: de eerste reden staat, niets
            # opnieuw doen (geen tweede afwijs-ronde in de werkvoorraad, geen dubbel audit-event).
            laatste, laatste_stappen = herhaald
            return _naar_data(session, laatste, laatste_stappen)
        accordering, stap, stappen = _stap_aan_de_beurt_voor(session, document_id=document_id, actor_id=actor_id)
        stap.besluit = StapBesluit.AFGEWEZEN.value
        stap.besluit_bron = StapBesluitBron.HANDMATIG.value
        stap.reden = reden_tekst
        stap.besloten_op = datetime.now(UTC)
        accordering.status = AccorderingStatus.AFGEWEZEN.value
        accordering.afgerond_op = datetime.now(UTC)
        aangeboden_door = accordering.aangeboden_door
        document = session.get(Document, document_id)
        assert document is not None
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=actor_id,
            detail={
                "accordering_id": str(accordering.id),
                "accordering_afgewezen": {"laag": stap.volgnummer, "reden": reden_tekst},
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="accordering_stap",
            record_id=stap.id,
            actie="accordering_afgewezen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"document_id": str(document_id), "laag": stap.volgnummer, "reden": reden_tekst},
            administratie_id=administratie_id,
        )
        accordering_id = accordering.id

    # Bestaand patroon: afwijzen-met-verplichte-reden — zichtbaar in de werkvoorraad, heropenen
    # herstelt de (zojuist teruggezette) klaar_om_te_boeken-herkomst. Toegewezen aan wie het
    # document aanbood (die kent de casus) — het afwijzen-default (administratie-eigenaar)
    # blijft de fallback via toegewezen_aan=None-gedrag als de aanbieder ontbreekt.
    afwijzen_service.wijs_af(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        reden=f"Afgewezen door accordeur: {reden_tekst}",
        toegewezen_aan=aangeboden_door,
    )

    with scoped_session(administratie_id) as session:
        accordering = session.get(DocumentAccordering, accordering_id)
        assert accordering is not None
        stappen = _stappen_van(session, accordering_id)
        return _naar_data(session, accordering, stappen)


def trek_accordering_in(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, actor_rol: str
) -> AccorderingData:
    """Kantoor haalt een document terug uit de accordering (bv. verkeerd aangeboden). Sinds de
    bugfix-run 28-08 óók toegestaan op een AFGERONDE ronde zolang het document nog op
    ter_accordering staat (boeken ná het laatste akkoord mislukte): het kantoor kan dan het
    voorstel aanpassen en opnieuw aanbieden — de afgeronde ronde wordt `ingetrokken` (het akkoord
    op het oude voorstel telt niet meer als boekpoort), tijdlijn + audit zoals altijd."""
    _vereis_kantoor(actor_rol)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        accordering = _open_accordering(session, document_id)
        na_boekfout = False
        if accordering is None:
            laatste = _laatste_accordering(session, document_id)
            if (
                laatste is not None
                and laatste.status == AccorderingStatus.AFGEROND.value
                and document.status == DocumentStatus.TER_ACCORDERING
            ):
                accordering, na_boekfout = laatste, True
        if accordering is None:
            raise GeenOpenAccordering("Er loopt geen accorderingsronde voor dit document")
        accordering.status = AccorderingStatus.INGETROKKEN.value
        accordering.afgerond_op = datetime.now(UTC)
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=actor_id,
            detail={
                "accordering_id": str(accordering.id),
                "accordering_ingetrokken": True,
                **({"na_boekfout": True} if na_boekfout else {}),
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document_accordering",
            record_id=accordering.id,
            actie="accordering_ingetrokken",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"document_id": str(document_id)},
            administratie_id=administratie_id,
        )
        stappen = _stappen_van(session, accordering.id)
        return _naar_data(session, accordering, stappen)


# --- lezen ---------------------------------------------------------------------------------------


def accordering_van_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> AccorderingData | None:
    """Meest recente accorderingsronde van een document (accorderingshistorie op het
    controlescherm)."""
    with scoped_session(administratie_id) as session:
        accordering = session.scalars(
            select(DocumentAccordering)
            .where(DocumentAccordering.document_id == document_id)
            .order_by(DocumentAccordering.aangeboden_op.desc())
        ).first()
        if accordering is None:
            # Blok 4 (08-09): geen ronde, maar wél een leverancier met IC-vlag in een administratie mét
            # klant-accordering → zichtbaar in de historie als "overgeslagen — intercompany" (zonder acties), live
            # berekend zodat het controlescherm het al vóór de boeking toont.
            if not is_accordering_ingeschakeld(administratie_id=administratie_id):
                return None
            overgeslagen = accordering_overgeslagen(session, administratie_id=administratie_id, document_id=document_id)
            if overgeslagen is None:
                return None
            document = session.get(Document, document_id)
            tijdstip = _overgeslagen_tijdstip(session, document_id) or (
                document.aangemaakt_op if document is not None else datetime.now(UTC)
            )
            return AccorderingData(
                id=document_id,
                document_id=document_id,
                status="overgeslagen",
                aangeboden_op=tijdstip,
                afgerond_op=None,
                stappen=[],
                overgeslagen_reden=overgeslagen.reden,
                overgeslagen_leverancier_naam=overgeslagen.leverancier_naam,
            )
        stappen = _stappen_van(session, accordering.id)
        return _naar_data(session, accordering, stappen)


@dataclass(frozen=True)
class WachtrijItem:
    document_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None
    leverancier_naam: str | None
    referentie: str | None
    factuurdatum: object
    totaalbedrag: Decimal | None
    aangeboden_op: datetime
    laag_volgnummer: int
    # PWA-review (mockup accordeur.html): compacte weergave van de voorgestelde boeking
    # ("Inkopen Headshop · btw 21%") — géén volledige regelweergave, scope bewust smal.
    boeking_omschrijving: str | None = None
    # Mockup-flow "staande goedkeuring na 2e identieke factuur": déze accordeur gaf eerder
    # handmatig akkoord op zelfde leverancier + exact bedrag, en er is nog geen actieve regel.
    staande_regel_kandidaat: bool = False
    # Blok 7 (11-09): het patroon achter het voorstel ('maand' | 'kwartaal'); None zonder voorstel. Het voorstel
    # komt sinds dit blok alleen bij een PERIODIEK patroon (gedeelde motor app/terugkerend), nooit bij een batch.
    staande_regel_patroon: str | None = None
    # Klaargezette doorbelasting (besluit 25-08, A3): ALLEEN-LEZEN weergave per doelentiteit
    # (naam, aandeel-%, bedrag excl., provisie); None = geen doorbelasting bij dit document.
    # Fout = de bestaande afwijsknop met verplichte reden (geen aparte doorbelasting-afwijzing).
    doorbelasting: tuple[WachtrijDoorbelastingRegel, ...] | None = None
    # Vragen-dialoog aan de accordeur (blok B5 26-08): de open vraag op dít document die aan déze
    # accordeur gericht is — None = geen (intern kantooroverleg komt hier nooit in).
    vraag: object | None = None
    # Afdeling van het document (blok A 28-08): de BV-kaart in de app wordt per afdeling
    # ("Kempen Facilities · Buitendienst"); None = administratie zonder afdelingen.
    afdeling_id: uuid.UUID | None = None
    afdeling_naam: str | None = None
    # Offerte-matching (04-09): documentsoort van dit wachtrij-item ('inkoopfactuur' |
    # 'verplichting') — de app rendert per soort een andere kaart (mockup blok 1).
    soort: str = "inkoopfactuur"
    # Alleen bij soort 'verplichting': de kaart-gegevens van de offerte/prijsopgave
    # (VerplichtingKaart) — bedrag EXCLUSIEF btw, want dát is wat de accordeur goedkeurt.
    verplichting: object | None = None
    # Alleen bij een inkoopfactuur mét een binnen/buiten-match: de conform-offerte-melding
    # (OPTIE A, ④) — het vinkje "Conform offerte ‹nr›" staat vóóringevuld, de mens tikt Akkoord.
    offerte_match: object | None = None


@dataclass(frozen=True)
class WachtrijDoorbelastingRegel:
    doelentiteit_naam: str
    percentage: Decimal
    netto_totaal: Decimal
    provisie_bedrag: Decimal


def _samenvat_doorbelasting(verdeling) -> tuple[WachtrijDoorbelastingRegel, ...] | None:  # noqa: ANN001
    """Puur: de klaargezette verdeling (`doorbelasting_service.VerdelingKort` per doelentiteit) samengevat
    voor de wachtrijkaart. Aandeel-% = netto_totaal van de doelentiteit t.o.v. het totaal van de verdeelde
    bron-regels (de per-regel-percentages kunnen verschillen; de accordeur krijgt één begrijpelijk getal).
    Herstelrun "Basis eerst" 08-09 (blok 1): de bron is niet meer `review_data` per item (17 queries +
    checks-rapport per item; 55× bij Kempen → 5–12 s) maar de bulk-leesroute
    `verdeling_per_doelentiteit_bulk` in dezelfde gescoopte sessie als de rest van de wachtrij — het
    checks-rapport blijft exclusief in het detail-/reviewscherm."""
    if not verdeling:
        return None
    totaal = sum((p.netto_totaal for p in verdeling), Decimal(0))
    regels = []
    for p in verdeling:
        aandeel = (p.netto_totaal / totaal * Decimal(100)).quantize(Decimal("0.01")) if totaal else Decimal(0)
        regels.append(
            WachtrijDoorbelastingRegel(
                doelentiteit_naam=p.doelentiteit_naam,
                percentage=aandeel,
                netto_totaal=p.netto_totaal,
                provisie_bedrag=p.provisie_bedrag,
            )
        )
    return tuple(regels)


def _klaargezette_runs(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """Eén query: document_id → run_id van de klaargezette doorbelasting-run (alleen documenten die er één
    hebben). Alleen díe runs gaan daarna de bulk-verdelingsroute in — de rest kost niets."""
    if not document_ids:
        return {}
    from app.doorbelasting.models import DoorbelastingRun, DoorbelastingRunStatus

    return dict(
        session.execute(
            select(DoorbelastingRun.document_id, DoorbelastingRun.id).where(
                DoorbelastingRun.document_id.in_(document_ids),
                DoorbelastingRun.status == DoorbelastingRunStatus.KLAARGEZET.value,
            )
        ).all()
    )


def _doorbelasting_verdelingen(
    session: Session, *, administratie_id: uuid.UUID, runs: dict[uuid.UUID, uuid.UUID]
) -> dict[uuid.UUID, tuple[WachtrijDoorbelastingRegel, ...] | None]:
    """document_id → kaart-samenvatting, voor álle klaargezette runs van deze administratie samen (3 queries,
    constant). Faalvriendelijk: een leesfout mag de wachtrij nooit blokkeren — dan géén blok op die items."""
    if not runs:
        return {}
    from app.doorbelasting import service as doorbelasting_service

    try:
        per_run = doorbelasting_service.verdeling_per_doelentiteit_bulk(
            session, administratie_id=administratie_id, run_ids=list(runs.values())
        )
    except Exception:  # noqa: BLE001 — verrijking, nooit blokkerend voor de wachtrij
        logger.exception(
            "Doorbelasting-samenvatting voor de wachtrij niet te laden (administratie %s)", administratie_id
        )
        return {}
    return {document_id: _samenvat_doorbelasting(per_run.get(run_id)) for document_id, run_id in runs.items()}


@dataclass(frozen=True)
class VerplichtingKaart:
    """Kaart-gegevens van een verplichting-document in de accordeur-wachtrij (mockup blok 1)."""

    soort_label: str | None
    leverancier_naam: str | None
    project_naam: str | None
    totaal_excl: Decimal | None
    geldig_tot: object | None
    omschrijving: str | None


def _verplichting_kaarten(
    session: Session, *, administratie_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VerplichtingKaart]:
    """Leesroute voor de accordeur (04-09, bulk sinds 08-09): de verplichting-rijen + leveranciers-/
    projectnamen uit de caches in drie queries voor de hele set. Faalvriendelijk: geen rij = geen
    kaart (de app valt dan terug op de kop-gegevens)."""
    if not document_ids:
        return {}
    from app.sync.models import ProjectCache
    from app.verplichting.models import Verplichting

    rijen = list(session.scalars(select(Verplichting).where(Verplichting.document_id.in_(document_ids))))
    if not rijen:
        return {}
    vendor_ids = {r.vendor_id for r in rijen if r.vendor_id is not None}
    project_ids = {r.project_id for r in rijen if r.project_id is not None}
    vendor_namen = (
        dict(
            session.execute(
                select(VendorCache.id, VendorCache.naam).where(
                    VendorCache.id.in_(vendor_ids), VendorCache.administratie_id == administratie_id
                )
            ).all()
        )
        if vendor_ids
        else {}
    )
    project_namen = (
        dict(
            session.execute(
                select(ProjectCache.id, ProjectCache.naam).where(
                    ProjectCache.id.in_(project_ids), ProjectCache.administratie_id == administratie_id
                )
            ).all()
        )
        if project_ids
        else {}
    )
    return {
        r.document_id: VerplichtingKaart(
            soort_label=r.soort_label,
            leverancier_naam=vendor_namen.get(r.vendor_id) if r.vendor_id else None,
            project_naam=project_namen.get(r.project_id) if r.project_id else None,
            totaal_excl=r.totaalbedrag_excl,
            geldig_tot=r.geldig_tot,
            omschrijving=r.omschrijving,
        )
        for r in rijen
    }


def _boeking_omschrijvingen(
    session: Session, *, administratie_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Eerste boekingsregel per document als leesbare samenvatting: grootboeknaam + btw-naam, met
    een "+n regels"-suffix bij meer regels (de accordeur beoordeelt de factuur, niet de codering —
    besluit scope-aanscherping 2026-08-08). Bulk (08-09): regels, grootboeknamen en btw-namen in
    drie queries voor de hele set."""
    if not document_ids:
        return {}
    from app.db.models import Grootboekrekening
    from app.documenten.models import BoekvoorstelRegel
    from app.sync.models import TaxRateCache

    regels_per_document: dict[uuid.UUID, list[BoekvoorstelRegel]] = {}
    for regel in session.scalars(
        select(BoekvoorstelRegel)
        .where(BoekvoorstelRegel.document_id.in_(document_ids))
        .order_by(BoekvoorstelRegel.document_id, BoekvoorstelRegel.volgnummer)
    ):
        regels_per_document.setdefault(regel.document_id, []).append(regel)
    if not regels_per_document:
        return {}
    eerste_regels = {doc_id: regels[0] for doc_id, regels in regels_per_document.items()}
    ledger_ids = {r.ledger_id for r in eerste_regels.values() if r.ledger_id is not None}
    taxrate_ids = {r.taxrate_id for r in eerste_regels.values() if r.taxrate_id is not None}
    grootboek_namen = (
        dict(
            session.execute(
                select(Grootboekrekening.ledger_id, Grootboekrekening.naam).where(
                    Grootboekrekening.ledger_id.in_(ledger_ids), Grootboekrekening.administratie_id == administratie_id
                )
            ).all()
        )
        if ledger_ids
        else {}
    )
    taxrate_namen = (
        dict(
            session.execute(
                select(TaxRateCache.id, TaxRateCache.naam).where(
                    TaxRateCache.id.in_(taxrate_ids), TaxRateCache.administratie_id == administratie_id
                )
            ).all()
        )
        if taxrate_ids
        else {}
    )
    uitkomst: dict[uuid.UUID, str] = {}
    for doc_id, regels in regels_per_document.items():
        eerste = regels[0]
        delen: list[str] = []
        if eerste.ledger_id is not None and grootboek_namen.get(eerste.ledger_id):
            delen.append(grootboek_namen[eerste.ledger_id])
        if eerste.taxrate_id is not None and taxrate_namen.get(eerste.taxrate_id):
            delen.append(taxrate_namen[eerste.taxrate_id])
        if not delen:
            continue
        samenvatting = " · ".join(delen)
        if len(regels) > 1:
            samenvatting += f" · +{len(regels) - 1} regels"
        uitkomst[doc_id] = samenvatting
    return uitkomst


def _boeking_omschrijving(session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> str | None:
    """Enkelvoudige vorm (delegeert naar de bulk-variant)."""
    return _boeking_omschrijvingen(session, administratie_id=administratie_id, document_ids=[document_id]).get(
        document_id
    )


def _staande_regel_kandidaten(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    accordeur_id: uuid.UUID,
    kandidaten: list[tuple[uuid.UUID, uuid.UUID | None, Decimal | None, uuid.UUID | None]],
    vandaag: date | None = None,
) -> dict[uuid.UUID, str]:
    """Voor welke wachtrij-documenten stelt de PWA ná het akkoord de staande goedkeuring voor →
    {document_id: patroon ('maand' | 'kwartaal')}. Voorwaarden (alle): déze accordeur gaf eerder HANDMATIG
    akkoord op een ánder document van dezelfde leverancier met exact hetzelfde bedrag (binnen dezelfde afdeling —
    blok A 28-08); er bestaat nog geen actieve staande regel voor die combinatie; de reeks gelijke facturen van
    die leverancier is PERIODIEK (blok 7 run 11-09 middag — gedeelde motor `app/terugkerend`: maand-/
    kwartaalpatroon, geen twee gelijke facturen < 21 d uit elkaar; een batch zoals Lusso's 12 chalets in één week
    krijgt NOOIT het voorstel); en er staat geen stilte/uitzondering (`staande_goedkeuring_voorstel_stil`: "niet nu"
    = 90 d stil, "nooit" per leverancier — voor deze accordeur of administratiebreed).
    `kandidaten` = (document_id, vendor_id, totaalbedrag, afdeling_id). Bulk (08-09): één query op de actieve
    regels van deze accordeur + één join-query rondes×stappen beperkt tot de leveranciers in de wachtrij, sinds
    blok 7 + één query gelijke facturen + één query stilte — constant per administratie."""
    relevant = [(d, v, t, a) for d, v, t, a in kandidaten if v is not None and t is not None]
    if not relevant:
        return {}
    vendor_ids = {v for _, v, _, _ in relevant}
    vandaag = vandaag or vandaag_nl()
    reeksen = gelijke_facturen_per_vendor_bedrag(session, administratie_id=administratie_id, vendor_ids=vendor_ids)
    stil_vendors = _stille_vendors(
        session, administratie_id=administratie_id, accordeur_id=accordeur_id, vendor_ids=vendor_ids, vandaag=vandaag
    )
    actieve_regels = {
        (r.vendor_id, r.bedrag, r.afdeling_id)
        for r in session.scalars(
            select(StaandeGoedkeuring).where(
                StaandeGoedkeuring.administratie_id == administratie_id,
                StaandeGoedkeuring.accordeur_gebruiker_id == accordeur_id,
                StaandeGoedkeuring.vendor_id.in_(vendor_ids),
                StaandeGoedkeuring.actief.is_(True),
            )
        )
    }
    # Eerdere handmatige akkoorden van déze accordeur bij deze leveranciers: ronde + de detail-JSON
    # (vendor_id/totaalbedrag/afdeling) in één join, gefilterd op vendor_id in SQL.
    eerdere = session.execute(
        select(DocumentAccordering.document_id, DocumentAccordering.detail)
        .join(AccorderingStap, AccorderingStap.accordering_id == DocumentAccordering.id)
        .where(
            DocumentAccordering.administratie_id == administratie_id,
            DocumentAccordering.detail["vendor_id"].astext.in_([str(v) for v in vendor_ids]),
            AccorderingStap.accordeur_gebruiker_id == accordeur_id,
            AccorderingStap.besluit == StapBesluit.AKKOORD.value,
            AccorderingStap.besluit_bron == StapBesluitBron.HANDMATIG.value,
        )
    ).all()
    handmatig_eerder: set[tuple[uuid.UUID, Decimal, uuid.UUID | None, uuid.UUID]] = set()
    for document_id, detail in eerdere:
        detail = detail or {}
        try:
            vendor_id = uuid.UUID(str(detail.get("vendor_id")))
        except ValueError:
            continue
        bedrag = _als_decimal(detail.get("totaalbedrag"))
        if bedrag is None:
            continue
        afdeling_ruw = detail.get("afdeling_id")
        try:
            afdeling_id = uuid.UUID(str(afdeling_ruw)) if afdeling_ruw else None
        except ValueError:
            afdeling_id = None
        handmatig_eerder.add((vendor_id, bedrag, afdeling_id, document_id))
    uitkomst: dict[uuid.UUID, str] = {}
    # De vraag één keer per leverancier + patroon (blok 7): staan er méér gelijke facturen tegelijk in de wachtrij,
    # dan draagt alleen de eerste (lijstvolgorde = aangeboden_op) het voorstel — nooit N× dezelfde vraag.
    al_voorgesteld: set[tuple[uuid.UUID, Decimal, uuid.UUID | None]] = set()
    for document_id, vendor_id, totaalbedrag, afdeling_id in relevant:
        sleutel = (vendor_id, totaalbedrag, afdeling_id)
        if sleutel in actieve_regels or vendor_id in stil_vendors or sleutel in al_voorgesteld:
            continue
        if not any(
            v == vendor_id and b == totaalbedrag and a == afdeling_id and d != document_id
            for v, b, a, d in handmatig_eerder
        ):
            continue
        reeks = classificeer_reeks(reeksen.get((vendor_id, totaalbedrag), []))
        if reeks.classificatie is not ReeksClassificatie.PERIODIEK or reeks.patroon is None:
            continue
        uitkomst[document_id] = reeks.patroon.soort
        al_voorgesteld.add(sleutel)
    return uitkomst


def _stille_vendors(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    accordeur_id: uuid.UUID,
    vendor_ids: set[uuid.UUID],
    vandaag: date,
) -> set[uuid.UUID]:
    """Leveranciers waarvoor het voorstel voor déze accordeur zwijgt: actieve rij voor deze accordeur óf
    administratiebreed (accordeur NULL), soort `nooit` altijd, soort `stil_tot` zolang stil_tot > vandaag."""
    rijen = session.scalars(
        select(StaandeGoedkeuringVoorstelStil).where(
            StaandeGoedkeuringVoorstelStil.administratie_id == administratie_id,
            StaandeGoedkeuringVoorstelStil.vendor_id.in_(vendor_ids),
            StaandeGoedkeuringVoorstelStil.actief.is_(True),
            (StaandeGoedkeuringVoorstelStil.accordeur_gebruiker_id == accordeur_id)
            | StaandeGoedkeuringVoorstelStil.accordeur_gebruiker_id.is_(None),
        )
    )
    stil: set[uuid.UUID] = set()
    for rij in rijen:
        if rij.soort == VoorstelStilSoort.NOOIT.value or (rij.stil_tot is not None and rij.stil_tot > vandaag):
            stil.add(rij.vendor_id)
    return stil


def _is_staande_regel_kandidaat(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    accordeur_id: uuid.UUID,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    totaalbedrag: Decimal | None,
    afdeling_id: uuid.UUID | None = None,
) -> bool:
    """Enkelvoudige vorm (delegeert naar de bulk-variant)."""
    return document_id in _staande_regel_kandidaten(
        session,
        administratie_id=administratie_id,
        accordeur_id=accordeur_id,
        kandidaten=[(document_id, vendor_id, totaalbedrag, afdeling_id)],
    )


def _open_rondes_met_volgende_stap(
    session: Session, *, administratie_id: uuid.UUID, alleen_met_stap_van: uuid.UUID | None = None
) -> list[tuple[DocumentAccordering, AccorderingStap]]:
    """DE gedeelde aan-de-beurt-bron (wachtrij, teller, meldingen — nooit uiteenlopen): alle open
    rondes van de administratie mét hun eerstvolgende open vereiste stap (`_eerstvolgende_open_stap`),
    in twee queries (rondes + álle stappen van die rondes). Met `alleen_met_stap_van` worden alleen
    rondes gelezen waarin die gebruiker überhaupt een stap heeft (EXISTS-filter in SQL) — een
    Beheerder-accordeur met 33 administraties laadt zo nooit álle open rondes."""
    rondes_q = select(DocumentAccordering).where(
        DocumentAccordering.administratie_id == administratie_id,
        DocumentAccordering.status == AccorderingStatus.OPEN.value,
    )
    if alleen_met_stap_van is not None:
        rondes_q = rondes_q.where(
            select(AccorderingStap.id)
            .where(
                AccorderingStap.accordering_id == DocumentAccordering.id,
                AccorderingStap.accordeur_gebruiker_id == alleen_met_stap_van,
            )
            .exists()
        )
    rondes = list(session.scalars(rondes_q))
    if not rondes:
        return []
    stappen_per_ronde: dict[uuid.UUID, list[AccorderingStap]] = {}
    for stap in session.scalars(
        select(AccorderingStap).where(AccorderingStap.accordering_id.in_([r.id for r in rondes]))
    ):
        stappen_per_ronde.setdefault(stap.accordering_id, []).append(stap)
    uitkomst: list[tuple[DocumentAccordering, AccorderingStap]] = []
    for ronde in rondes:
        volgende = _eerstvolgende_open_stap(stappen_per_ronde.get(ronde.id, []))
        if volgende is not None:
            uitkomst.append((ronde, volgende))
    return uitkomst


# Bovengrens (documentatie + test `test_wachtrij_querytelling.py`): aantal SQL-statements per
# administratie in `wachtrij_voor_accordeur`, ONAFHANKELIJK van het aantal rondes. Opbouw:
# 2 set_config + 1 rondes (EXISTS) + 1 stappen + 1 administratie + 1 documenten + 1 voorstellen
# + 1 vendors + 3 boekingsomschrijving + 4 staande-regel (2 + gelijke facturen + stilte, blok 7 11-09)
# + 1 vragen (+3 als er vragen zijn)
# + 3 verplichting-kaarten (alleen bij verplichting-items) + 1 doorbelasting-runs (+3 bulk-verdeling
# als er klaargezette runs zijn: regelsommen, mappingnamen, instelling — herstelrun "Basis eerst"
# 08-09 blok 1; vóór die run kwam hier per doorbelasting-document `review_data` bij met 17 queries
# + checks-rapport, 55× bij Kempen Facilities → 5–12 s voor Peter)
# + 1 offerte-match (+4 als er treffers zijn) = 17 zonder verrijkingstreffers, 30 met álle.
# Zonder rondes voor deze actor: 3 (2 set_config + rondes-query). Sinds 08-09 is er GEEN per-item-
# uitzondering meer: ook doorbelasting schaalt niet met het aantal items (test
# `test_querytelling_doorbelasting_schaalt_niet_met_items`).
WACHTRIJ_MAX_STATEMENTS_PER_ADMINISTRATIE = 30


def _wachtrij_administratie(
    session: Session, *, actor_id: uuid.UUID, administratie_id: uuid.UUID
) -> list[WachtrijItem]:
    """Wachtrij-items van één administratie, set-based (blok 1 spoedrun 08-09 — de oude vorm deed
    per open ronde 8–12 losse lookups plus per item twee eigen sessies; live 9,8–11,5 s voor
    Peter). Aan-de-beurt-definitie = `_open_rondes_met_volgende_stap`."""
    rondes = [
        (ronde, volgende)
        for ronde, volgende in _open_rondes_met_volgende_stap(
            session, administratie_id=administratie_id, alleen_met_stap_van=actor_id
        )
        if volgende.accordeur_gebruiker_id == actor_id
    ]
    if not rondes:
        return []
    administratie = session.get(Administratie, administratie_id)
    document_ids = [ronde.document_id for ronde, _ in rondes]
    documenten = {d.id: d for d in session.scalars(select(Document).where(Document.id.in_(document_ids)))}
    voorstellen = {
        v.document_id: v
        for v in session.scalars(select(Boekvoorstel).where(Boekvoorstel.document_id.in_(document_ids)))
    }
    vendor_ids = {v.vendor_id for v in voorstellen.values() if v.vendor_id is not None}
    vendor_namen = (
        dict(
            session.execute(
                select(VendorCache.id, VendorCache.naam).where(
                    VendorCache.id.in_(vendor_ids), VendorCache.administratie_id == administratie_id
                )
            ).all()
        )
        if vendor_ids
        else {}
    )
    omschrijvingen = _boeking_omschrijvingen(session, administratie_id=administratie_id, document_ids=document_ids)
    kandidaten = _staande_regel_kandidaten(
        session,
        administratie_id=administratie_id,
        accordeur_id=actor_id,
        kandidaten=[
            (
                ronde.document_id,
                voorstellen[ronde.document_id].vendor_id if ronde.document_id in voorstellen else None,
                voorstellen[ronde.document_id].totaalbedrag if ronde.document_id in voorstellen else None,
                _ronde_afdeling_id(ronde),
            )
            for ronde, _ in rondes
        ],
    )
    vragen = open_vragen_aan_accordeur_per_document(session, document_ids=document_ids, actor_id=actor_id)
    verplichting_ids = [
        d
        for d in document_ids
        if (doc := documenten.get(d)) is not None and doc.soort == DocumentSoort.VERPLICHTING.value
    ]
    verplichting_kaarten = _verplichting_kaarten(
        session, administratie_id=administratie_id, document_ids=verplichting_ids
    )
    inkoop_ids = [d for d in document_ids if d not in set(verplichting_ids)]
    from app.verplichting import service as verplichting_service

    try:
        offerte_matches = verplichting_service.offerte_match_kort_per_document(
            session, administratie_id=administratie_id, document_ids=inkoop_ids
        )
    except Exception:  # noqa: BLE001 — verrijking, nooit blokkerend voor de wachtrij
        logger.exception("Offerte-match voor de wachtrij niet te laden (administratie %s)", administratie_id)
        offerte_matches = {}
    doorbelastingen = _doorbelasting_verdelingen(
        session, administratie_id=administratie_id, runs=_klaargezette_runs(session, document_ids)
    )

    items: list[WachtrijItem] = []
    for ronde, volgende in rondes:
        document = documenten.get(ronde.document_id)
        soort = document.soort if document is not None else DocumentSoort.INKOOPFACTUUR.value
        voorstel = voorstellen.get(ronde.document_id)
        leverancier = vendor_namen.get(voorstel.vendor_id) if voorstel is not None and voorstel.vendor_id else None
        is_verplichting = soort == DocumentSoort.VERPLICHTING.value
        verplichting_kaart = verplichting_kaarten.get(ronde.document_id) if is_verplichting else None
        if verplichting_kaart is not None and verplichting_kaart.leverancier_naam:
            leverancier = verplichting_kaart.leverancier_naam
        items.append(
            WachtrijItem(
                document_id=ronde.document_id,
                administratie_id=administratie_id,
                administratie_naam=administratie.naam if administratie else None,
                leverancier_naam=leverancier,
                referentie=voorstel.referentie if voorstel else None,
                factuurdatum=voorstel.factuurdatum if voorstel else None,
                totaalbedrag=voorstel.totaalbedrag if voorstel else None,
                aangeboden_op=ronde.aangeboden_op,
                laag_volgnummer=volgende.volgnummer,
                boeking_omschrijving=omschrijvingen.get(ronde.document_id),
                staande_regel_kandidaat=ronde.document_id in kandidaten,
                staande_regel_patroon=kandidaten.get(ronde.document_id),
                # Bulk gelezen in déze sessie (blok 1 herstelrun 08-09); None = geen klaargezette run.
                doorbelasting=doorbelastingen.get(ronde.document_id),
                vraag=vragen.get(ronde.document_id),
                afdeling_id=_ronde_afdeling_id(ronde),
                afdeling_naam=(ronde.detail or {}).get("afdeling_naam"),
                soort=soort,
                verplichting=verplichting_kaart,
                offerte_match=(
                    offerte_matches.get(ronde.document_id) if soort == DocumentSoort.INKOOPFACTUUR.value else None
                ),
            )
        )
    return items


def wachtrij_voor_accordeur(*, actor_id: uuid.UUID, administratie_ids: list[uuid.UUID]) -> list[WachtrijItem]:
    """De accordeer-wachtrij (PWA-endpoint, scope-aanscherping 2026-08-08: uitsluitend de
    wachtrij): documenten in ter_accordering waar déze accordeur aan de beurt is — per
    administratie binnen de scope (RLS dwingt dat af; de lijst komt uit de scope-bron).
    Set-based sinds blok 1 (08-09): per administratie één gescoopte sessie met een constant aantal
    queries (`WACHTRIJ_MAX_STATEMENTS_PER_ADMINISTRATIE`), nooit per ronde én — sinds de herstelrun
    "Basis eerst" 08-09 — nooit per doorbelasting-item (bulk-verdeling in dezelfde sessie)."""
    items: list[WachtrijItem] = []
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id) as session:
            items.extend(_wachtrij_administratie(session, actor_id=actor_id, administratie_id=administratie_id))
    items.sort(key=lambda i: i.aangeboden_op)
    return items


def documenten_aan_de_beurt(*, administratie_id: uuid.UUID) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Per accordeur de document-id's waar híj/zij nu aan de beurt is, voor één administratie —
    exact dezelfde aan-de-beurt-definitie als de wachtrij (`_open_rondes_met_volgende_stap`),
    zodat teller, wachtrij en meldingen nooit uiteenlopen. Selectiebron van de dagelijkse
    herinnering (via aantallen_aan_de_beurt) én de nieuwe-facturen-bundelmelding."""
    per_accordeur: dict[uuid.UUID, list[uuid.UUID]] = {}
    with scoped_session(administratie_id) as session:
        for ronde, volgende in _open_rondes_met_volgende_stap(session, administratie_id=administratie_id):
            per_accordeur.setdefault(volgende.accordeur_gebruiker_id, []).append(ronde.document_id)
    return per_accordeur


@dataclass(frozen=True)
class AanDeBeurt:
    """Wie nu aan de beurt is op een ter-accordering-document (C2 26-08, documentenlijst-kolom
    "Toegewezen"): accordeur + laag (volgnummer) — zelfde definitie als wachtrij/meldingen."""

    gebruiker_id: uuid.UUID
    naam: str
    laag: int


def aan_de_beurt_per_document(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, AanDeBeurt]:
    """Bulk (geen N+1): per document mét open accorderingsronde de eerstvolgende open vereiste
    stap → (accordeur, laag). Sessie van de aanroeper (documenten-lijst, al gescoopt)."""
    if not document_ids:
        return {}
    from app.db.models import Gebruiker

    rondes = list(
        session.scalars(
            select(DocumentAccordering).where(
                DocumentAccordering.document_id.in_(document_ids),
                DocumentAccordering.status == AccorderingStatus.OPEN.value,
            )
        )
    )
    if not rondes:
        return {}
    stappen = list(
        session.scalars(select(AccorderingStap).where(AccorderingStap.accordering_id.in_([r.id for r in rondes])))
    )
    per_ronde: dict[uuid.UUID, list[AccorderingStap]] = {}
    for stap in stappen:
        per_ronde.setdefault(stap.accordering_id, []).append(stap)
    volgende_per_document: dict[uuid.UUID, AccorderingStap] = {}
    for ronde in rondes:
        volgende = _eerstvolgende_open_stap(per_ronde.get(ronde.id, []))
        if volgende is not None:
            volgende_per_document[ronde.document_id] = volgende
    namen = (
        dict(
            session.execute(
                select(Gebruiker.id, Gebruiker.naam).where(
                    Gebruiker.id.in_({s.accordeur_gebruiker_id for s in volgende_per_document.values()})
                )
            ).all()
        )
        if volgende_per_document
        else {}
    )
    return {
        document_id: AanDeBeurt(
            gebruiker_id=stap.accordeur_gebruiker_id,
            naam=namen.get(stap.accordeur_gebruiker_id, "accordeur"),
            laag=stap.volgnummer,
        )
        for document_id, stap in volgende_per_document.items()
    }


def aantallen_aan_de_beurt(*, administratie_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Aantalvariant van documenten_aan_de_beurt (de herinnering heeft alleen het aantal nodig)."""
    return {
        accordeur_id: len(document_ids)
        for accordeur_id, document_ids in documenten_aan_de_beurt(administratie_id=administratie_id).items()
    }


@dataclass(frozen=True)
class AccordeurKandidaat:
    id: uuid.UUID
    naam: str


def accordeur_kandidaten(*, administratie_id: uuid.UUID) -> list[AccordeurKandidaat]:
    """Actieve gebruikers met rol klant-accordeur en scope op deze administratie — de keuzelijst
    voor het lagen-beheer (Instellingen). Alleen id + naam (dataminimalisatie, zelfde afweging
    als beheer/service.py::lijst_medewerkers)."""
    from app.db.models import GebruikerAdministratie, GebruikerStatus

    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Gebruiker.id, Gebruiker.naam)
            .join(GebruikerAdministratie, GebruikerAdministratie.gebruiker_id == Gebruiker.id)
            .where(
                GebruikerAdministratie.administratie_id == administratie_id,
                Gebruiker.status == GebruikerStatus.ACTIEF,
                Gebruiker.rol == GebruikerRol.KLANT_ACCORDEUR,
            )
        ).all()
    return sorted((AccordeurKandidaat(id=rij.id, naam=rij.naam) for rij in rijen), key=lambda k: k.naam.lower())


def staande_regels(*, administratie_id: uuid.UUID) -> tuple[list[StaandeGoedkeuring], dict[uuid.UUID, str]]:
    with scoped_session(administratie_id) as session:
        regels = list(
            session.scalars(
                select(StaandeGoedkeuring)
                .where(StaandeGoedkeuring.administratie_id == administratie_id)
                .order_by(StaandeGoedkeuring.aangemaakt_op.desc())
            )
        )
        namen = _gebruikersnamen(session, {r.accordeur_gebruiker_id for r in regels})
        session.expunge_all()
    return regels, namen


def trek_staande_regel_in(*, administratie_id: uuid.UUID, regel_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Intrekbaar door kantoor én door de accordeur zelf (besluit 2026-08-08: zichtbaar +
    intrekbaar) — nooit een DELETE."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        regel = session.get(StaandeGoedkeuring, regel_id)
        if regel is None or regel.administratie_id != administratie_id:
            raise DocumentNietGevonden(f"Onbekende staande goedkeuring: {regel_id}")
        if not regel.actief:
            raise AccorderingFout("Deze staande goedkeuring is al ingetrokken")
        regel.actief = False
        regel.ingetrokken_door = actor_id
        regel.ingetrokken_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="staande_goedkeuring",
            record_id=regel.id,
            actie="staande_goedkeuring_ingetrokken",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"actief": True},
            nieuwe_waarde={"actief": False},
            administratie_id=administratie_id,
        )


# --- voorstel-stilte / "nooit voorstellen" (blok 7 run 11-09 middag) ------------------------------------------------


@dataclass(frozen=True)
class VoorstelUitzonderingData:
    id: uuid.UUID
    accordeur_gebruiker_id: uuid.UUID | None
    accordeur_naam: str | None
    vendor_id: uuid.UUID
    leverancier_naam: str | None
    soort: str  # stil_tot | nooit
    stil_tot: date | None
    reden: str | None
    actief: bool
    aangemaakt_op: datetime
    aangemaakt_door: uuid.UUID
    opgeheven_op: datetime | None


def _leg_voorstel_stilte_vast(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    accordeur_gebruiker_id: uuid.UUID | None,
    vendor_id: uuid.UUID,
    soort: VoorstelStilSoort,
    reden: str | None,
    actor_id: uuid.UUID,
) -> StaandeGoedkeuringVoorstelStil:
    """Eén actieve rij per (administratie, accordeur|NULL, leverancier): een bestaande actieve rij wordt
    bijgewerkt (stil_tot verlengd / stil_tot → nooit), nooit gedupliceerd; `nooit` wint altijd van `stil_tot`.
    Audit oud→nieuw op elke zetting."""
    bestaande = session.scalars(
        select(StaandeGoedkeuringVoorstelStil).where(
            StaandeGoedkeuringVoorstelStil.administratie_id == administratie_id,
            StaandeGoedkeuringVoorstelStil.vendor_id == vendor_id,
            StaandeGoedkeuringVoorstelStil.actief.is_(True),
            (
                StaandeGoedkeuringVoorstelStil.accordeur_gebruiker_id == accordeur_gebruiker_id
                if accordeur_gebruiker_id is not None
                else StaandeGoedkeuringVoorstelStil.accordeur_gebruiker_id.is_(None)
            ),
        )
    ).first()
    stil_tot = vandaag_nl() + timedelta(days=VOORSTEL_STIL_DAGEN) if soort is VoorstelStilSoort.STIL_TOT else None
    vendor = session.get(VendorCache, (vendor_id, administratie_id))
    if bestaande is None:
        rij = StaandeGoedkeuringVoorstelStil(
            administratie_id=administratie_id,
            accordeur_gebruiker_id=accordeur_gebruiker_id,
            vendor_id=vendor_id,
            leverancier_naam=vendor.naam if vendor else None,
            soort=soort.value,
            stil_tot=stil_tot,
            reden=reden,
            aangemaakt_door=actor_id,
        )
        session.add(rij)
        session.flush()
        oud: dict | None = None
    else:
        rij = bestaande
        oud = {"soort": rij.soort, "stil_tot": rij.stil_tot.isoformat() if rij.stil_tot else None, "reden": rij.reden}
        if rij.soort == VoorstelStilSoort.NOOIT.value and soort is VoorstelStilSoort.STIL_TOT:
            return rij  # nooit wint — niets te wijzigen
        rij.soort = soort.value
        rij.stil_tot = stil_tot
        rij.reden = reden
        rij.aangemaakt_door = actor_id
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="staande_goedkeuring_voorstel_stil",
        record_id=rij.id,
        actie="staande_goedkeuring_voorstel_stil_gezet",
        correlatie_id=uuid.uuid4(),
        oude_waarde=oud,
        nieuwe_waarde={
            "soort": rij.soort,
            "stil_tot": rij.stil_tot.isoformat() if rij.stil_tot else None,
            "reden": rij.reden,
            "vendor_id": str(vendor_id),
            "leverancier": rij.leverancier_naam,
            "accordeur_gebruiker_id": str(accordeur_gebruiker_id) if accordeur_gebruiker_id else None,
        },
        administratie_id=administratie_id,
    )
    return rij


def zet_voorstel_nooit(
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_rol: str,
    accordeur_gebruiker_id: uuid.UUID | None,
    reden: str | None,
) -> VoorstelUitzonderingData:
    """Instelt "nooit voorstellen" voor een leverancier. De accordeur zelf (app): alleen voor zichzelf
    (`accordeur_gebruiker_id` = eigen id of None → eigen id). Beheerder (kantoor-web): administratiebreed (None)
    of voor één accordeur. Andere kantoorrollen: KantoorActieVereist (Beheerder-instelling, zoals de lagen)."""
    rol = GebruikerRol(actor_rol)
    if rol == GebruikerRol.KLANT_ACCORDEUR:
        if accordeur_gebruiker_id not in (None, actor_id):
            raise VoorstelUitzonderingFout("Een accordeur kan alleen voor zichzelf 'nooit voorstellen' instellen")
        accordeur_gebruiker_id = actor_id
    elif rol != GebruikerRol.BEHEERDER:
        raise KantoorActieVereist("'Nooit voorstellen' instellen is een Beheerder-actie")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = _leg_voorstel_stilte_vast(
            session,
            administratie_id=administratie_id,
            accordeur_gebruiker_id=accordeur_gebruiker_id,
            vendor_id=vendor_id,
            soort=VoorstelStilSoort.NOOIT,
            reden=reden,
            actor_id=actor_id,
        )
        namen = _gebruikersnamen(session, {rij.accordeur_gebruiker_id} if rij.accordeur_gebruiker_id else set())
        data = _voorstel_uitzondering_data(rij, namen)
    return data


def hef_voorstel_uitzondering_op(
    *, administratie_id: uuid.UUID, rij_id: uuid.UUID, actor_id: uuid.UUID, actor_rol: str
) -> None:
    """Opheffen = actief=False mét wie/wanneer (nooit een DELETE). Accordeur: alleen eigen rijen; Beheerder: alle;
    andere kantoorrollen: geen."""
    rol = GebruikerRol(actor_rol)
    if rol not in (GebruikerRol.KLANT_ACCORDEUR, GebruikerRol.BEHEERDER):
        raise KantoorActieVereist("Opheffen van 'nooit voorstellen' is een Beheerder-actie")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(StaandeGoedkeuringVoorstelStil, rij_id)
        if rij is None or rij.administratie_id != administratie_id:
            raise VoorstelUitzonderingFout(f"Onbekende voorstel-uitzondering: {rij_id}")
        if rol == GebruikerRol.KLANT_ACCORDEUR and rij.accordeur_gebruiker_id != actor_id:
            raise VoorstelUitzonderingFout("Alleen je eigen 'nooit voorstellen' kun je opheffen")
        if not rij.actief:
            raise VoorstelUitzonderingFout("Deze voorstel-uitzondering is al opgeheven")
        rij.actief = False
        rij.opgeheven_door = actor_id
        rij.opgeheven_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="staande_goedkeuring_voorstel_stil",
            record_id=rij.id,
            actie="staande_goedkeuring_voorstel_stil_opgeheven",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"actief": True, "soort": rij.soort},
            nieuwe_waarde={"actief": False, "vendor_id": str(rij.vendor_id)},
            administratie_id=administratie_id,
        )


def voorstel_uitzonderingen(
    *, administratie_id: uuid.UUID, alleen_actief: bool = True
) -> list[VoorstelUitzonderingData]:
    """Lijst voor de staande-goedkeuringen-weergave (kantoor-web + app): actieve `nooit`-rijen en lopende
    `stil_tot`-rijen (verstreken stiltes tellen niet meer, tenzij `alleen_actief=False`)."""
    vandaag = vandaag_nl()
    with scoped_session(administratie_id) as session:
        q = select(StaandeGoedkeuringVoorstelStil).where(
            StaandeGoedkeuringVoorstelStil.administratie_id == administratie_id
        )
        if alleen_actief:
            q = q.where(StaandeGoedkeuringVoorstelStil.actief.is_(True))
        rijen = list(session.scalars(q.order_by(StaandeGoedkeuringVoorstelStil.aangemaakt_op.desc())))
        namen = _gebruikersnamen(session, {r.accordeur_gebruiker_id for r in rijen if r.accordeur_gebruiker_id})
        uit = [
            _voorstel_uitzondering_data(r, namen)
            for r in rijen
            if not alleen_actief or r.soort == VoorstelStilSoort.NOOIT.value or (r.stil_tot and r.stil_tot > vandaag)
        ]
    return uit


def _voorstel_uitzondering_data(
    rij: StaandeGoedkeuringVoorstelStil, namen: dict[uuid.UUID, str]
) -> VoorstelUitzonderingData:
    return VoorstelUitzonderingData(
        id=rij.id,
        accordeur_gebruiker_id=rij.accordeur_gebruiker_id,
        accordeur_naam=namen.get(rij.accordeur_gebruiker_id) if rij.accordeur_gebruiker_id else None,
        vendor_id=rij.vendor_id,
        leverancier_naam=rij.leverancier_naam,
        soort=rij.soort,
        stil_tot=rij.stil_tot,
        reden=rij.reden,
        actief=rij.actief,
        aangemaakt_op=rij.aangemaakt_op,
        aangemaakt_door=rij.aangemaakt_door,
        opgeheven_op=rij.opgeheven_op,
    )
