"""Acceptatie "Bewust verwijderd in Reeleezee (dubbel/test)" op de bevinding `ontbreekt_in_rlz` (blok D, opdracht
Peter 16-09; casus Kempen Facilities: drie keer "RLZ-document verdwenen" — twee dubbel geboekt en één TEST-exemplaar
door Peter zelf in RLZ verwijderd).

Vóór dit blok moest de Beheerder een vrije reden typen én bleef ons document in het Archief op 'geboekt' staan met
een dood boekstuknummer. Nu is het één klik, in één logische handeling:

1. dezelfde scope-/soort-validatie als "Opnieuw boeken" (`herboeken.opnieuw_boeken_vanuit_bevinding`): blok
   documenten, soort afwijking/uitgesloten, `afwijking_soort` in `ONTBREEKT_SOORTEN`, `document_id` aanwezig;
   alleen een Beheerder (dezelfde poort als accepteren);
2. acceptatie via de BESTAANDE schrijver `kantoorbreed.accepteer` mét de vaste reden `VASTE_REDEN` (+ optionele
   toelichting) — Beheerder-check en audit `reconciliatie_afwijking_geaccepteerd` ongewijzigd;
3. documentstatus: een GEBOEKT document gaat naar `afgevoerd_duplicaat` via `_schrijf_overgang` (de ENIGE plek die
   document.status muteert: statusmachine-validatie, tijdlijnregel mét leesbare reden "In Reeleezee verwijderd door
   <naam> als dubbel/test (boekstuk …)", audit) + eigen audit `document_bewust_verwijderd_afgevoerd`. Staat het
   document niet (meer) op geboekt, dan blijft de status ongewijzigd en zegt het resultaat dat
   (`document_status_gewijzigd=False`). `boekvoorstel.rlz_boekstuknummer` blijft staan als historie — niets wordt
   gewist.

Waarom NIET via `afwijzen.wijs_af(naar_status=AFGEVOERD_DUPLICAAT)` (het duplicaat-afvoer-patroon): de tabel
`afwijzing` draagt de DB-CHECK `afwijzing_herkomst_herstelbaar` (status_voor_afwijzing ∈ te_controleren /
handmatig_afmaken / klaar_om_te_boeken) — een Afwijzing-rij met herkomst `geboekt` kan zonder migratie niet bestaan,
en migraties zijn voor dit blok niet toegestaan. Daarmee is ook `afwijzen.heropen` (dat de open Afwijzing-rij nodig
heeft) geen terugweg; de terugweg is hier `herstel_bewust_verwijderd`: document AFGEVOERD_DUPLICAAT → GEBOEKT
(statusmachine-overgang die alleen hiervoor bestaat) én de acceptatie ingetrokken, zodat de bevinding bij de
volgende run weer meetelt. Beide richtingen alleen op een document dat het `bewust_verwijderd`-spoor in de tijdlijn
draagt — nooit een willekeurig afgevoerd duplicaat "herstellen" naar geboekt.

Een fout in stap 3 draait stap 2 NIET terug (de acceptatie staat dan al) maar komt wél als `StatusFout` naar de
router (409 mét tekst).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.auth import service as auth_service
from app.db.audit import record_audit_event
from app.db.models import Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.reconciliatie import ONTBREEKT_SOORTEN
from app.documenten.service import _schrijf_overgang
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.reconciliatie import kantoorbreed
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie.models import BevindingSoort, ReconciliatieAcceptatie, ReconciliatieBevinding

VASTE_REDEN = "Bewust verwijderd in Reeleezee (dubbel/test)"
MAX_TOELICHTING = 500
#: Tijdlijn-/audit-marker: alleen een overgang mét deze sleutel is via `herstel_bewust_verwijderd` terug te draaien.
TIJDLIJN_MARKER = "bewust_verwijderd"
AUDIT_AFGEVOERD = "document_bewust_verwijderd_afgevoerd"
AUDIT_HERSTELD = "document_bewust_verwijderd_hersteld"


class BewustVerwijderdFout(Exception):
    """Basisfout — de router vertaalt naar 4xx mét de tekst."""


class BevindingNietGevonden(BewustVerwijderdFout):
    pass


class GeenToegang(BewustVerwijderdFout):
    pass


class VerkeerdeSoort(BewustVerwijderdFout):
    """Geen documenten-afwijking `ontbreekt_in_*` — deze knop hoort daar niet."""


class StatusFout(BewustVerwijderdFout):
    """Stap 3 (documentstatus) faalde ná een geslaagde acceptatie — de acceptatie staat, het document niet."""


class NietTerugdraaibaar(BewustVerwijderdFout):
    """Het document draagt geen bewust-verwijderd-spoor (of staat niet op afgevoerd_duplicaat)."""


@dataclass(frozen=True)
class BewustVerwijderdResultaat:
    acceptatie_id: uuid.UUID
    document_id: uuid.UUID
    document_status_nieuw: str
    boekstuknummer: str | None
    #: False = het document stond niet op geboekt (bv. boeken_mislukt) → alleen geaccepteerd, status ongewijzigd.
    document_status_gewijzigd: bool
    reden: str


@dataclass(frozen=True)
class HerstelResultaat:
    document_id: uuid.UUID
    document_status_nieuw: str
    #: id van de ingetrokken acceptatie (None als die al ingetrokken/onvindbaar was — dan alleen de status hersteld).
    acceptatie_ingetrokken_id: uuid.UUID | None


def _vereis_beheerder_binnen_scope(*, administratie_id: uuid.UUID, actor_id: uuid.UUID, rol: GebruikerRol) -> None:
    if administratie_id not in {a.id for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol)}:
        raise GeenToegang("Geen toegang tot deze administratie")
    if rol != GebruikerRol.BEHEERDER:
        raise GeenToegang("Alleen een Beheerder kan een bevinding als bewust verwijderd accepteren")


def _document_stand(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[DocumentStatus, str | None, str]:
    """Status + boekstuknummer van het document en de naam van de actor (voor de leesbare reden), in één gescoopte
    sessie (RLS-les 25-08: altijd `scoped_session(<administratie>, actor_id=…)`)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        doc = session.get(Document, document_id)
        if doc is None:
            raise BevindingNietGevonden("Document van deze bevinding niet gevonden")
        bv = session.get(Boekvoorstel, document_id)
        g = session.get(Gebruiker, actor_id)
        naam = (g.naam or "").strip() if g is not None else ""
        return doc.status, (bv.rlz_boekstuknummer if bv is not None else None), (naam or "Beheerder")


def accepteer_bewust_verwijderd(
    *,
    bevinding_id: uuid.UUID,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    toelichting: str | None = None,
) -> BewustVerwijderdResultaat:
    """Zie module-docstring."""
    _vereis_beheerder_binnen_scope(administratie_id=administratie_id, actor_id=actor_id, rol=rol)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        b = session.get(ReconciliatieBevinding, bevinding_id)
        if b is None or b.administratie_id != administratie_id:
            raise BevindingNietGevonden("Bevinding niet gevonden")
        d = dict(b.detail or {})
        blok, soort = b.blok, b.soort
    if blok != "documenten" or soort not in (BevindingSoort.AFWIJKING.value, BevindingSoort.UITGESLOTEN.value):
        raise VerkeerdeSoort("Bewust verwijderd geldt alleen voor een documenten-afwijking")
    if d.get("afwijking_soort") not in ONTBREEKT_SOORTEN or not d.get("document_id"):
        raise VerkeerdeSoort(
            "Bewust verwijderd geldt alleen als het externe document verdwenen is (ontbreekt in RLZ/Odoo)"
        )
    document_id = uuid.UUID(str(d["document_id"]))

    toelichting_tekst = (toelichting or "").strip()
    if len(toelichting_tekst) > MAX_TOELICHTING:
        raise BewustVerwijderdFout(f"Toelichting is te lang (maximaal {MAX_TOELICHTING} tekens)")
    reden = VASTE_REDEN if not toelichting_tekst else f"{VASTE_REDEN} — {toelichting_tekst}"

    status_voor, boekstuknummer, actor_naam = _document_stand(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
    )

    # Stap 2: acceptatie via de bestaande schrijver (Beheerder-check + audit `reconciliatie_afwijking_geaccepteerd`).
    try:
        acceptatie_id = kantoorbreed.accepteer(
            bevinding_id=bevinding_id, administratie_id=administratie_id, reden=reden, actor_id=actor_id, rol=rol
        )
    except kantoorbreed.ReconciliatieFout as exc:
        tekst = str(exc)
        if "Geen toegang" in tekst or "Alleen een Beheerder" in tekst:
            raise GeenToegang(tekst) from exc
        raise BewustVerwijderdFout(tekst) from exc

    # Stap 3: documentstatus — alleen een GEBOEKT document gaat naar afgevoerd_duplicaat; anders ongewijzigd melden.
    if status_voor != DocumentStatus.GEBOEKT:
        return BewustVerwijderdResultaat(
            acceptatie_id=acceptatie_id,
            document_id=document_id,
            document_status_nieuw=status_voor.value,
            boekstuknummer=boekstuknummer,
            document_status_gewijzigd=False,
            reden=reden,
        )
    tijdlijn_reden = (
        f"In Reeleezee verwijderd door {actor_naam} als dubbel/test (boekstuk {boekstuknummer or 'onbekend'})"
        + (f" — {toelichting_tekst}" if toelichting_tekst else "")
    )
    try:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            document = session.get(Document, document_id)
            if document is None:
                raise BevindingNietGevonden("Document van deze bevinding niet gevonden")
            detail = {
                TIJDLIJN_MARKER: True,
                "reden": tijdlijn_reden,
                "acceptatie_id": str(acceptatie_id),
                "bevinding_id": str(bevinding_id),
                "rlz_boekstuknummer": boekstuknummer,
                "status_voor": DocumentStatus.GEBOEKT.value,
            }
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.AFGEVOERD_DUPLICAAT, actor_id=actor_id, detail=detail
            )
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="document",
                record_id=document_id,
                actie=AUDIT_AFGEVOERD,
                correlatie_id=uuid.uuid4(),
                oude_waarde={"status": DocumentStatus.GEBOEKT.value, "rlz_boekstuknummer": boekstuknummer},
                nieuwe_waarde={"status": DocumentStatus.AFGEVOERD_DUPLICAAT.value, **detail},
                administratie_id=administratie_id,
            )
    except OngeldigeStatusovergang as exc:
        raise StatusFout(
            f"Bevinding is geaccepteerd, maar het document kon niet naar 'afgevoerd als duplicaat': {exc}"
        ) from exc
    return BewustVerwijderdResultaat(
        acceptatie_id=acceptatie_id,
        document_id=document_id,
        document_status_nieuw=DocumentStatus.AFGEVOERD_DUPLICAAT.value,
        boekstuknummer=boekstuknummer,
        document_status_gewijzigd=True,
        reden=reden,
    )


def _laatste_bewust_verwijderd_spoor(session, document_id: uuid.UUID) -> DocumentGebeurtenis | None:  # noqa: ANN001
    """De jongste tijdlijnregel naar afgevoerd_duplicaat mét de marker — alleen die maakt herstel toegestaan."""
    jongste = session.scalars(
        select(DocumentGebeurtenis)
        .where(
            DocumentGebeurtenis.document_id == document_id,
            DocumentGebeurtenis.naar_status == DocumentStatus.AFGEVOERD_DUPLICAAT,
        )
        .order_by(DocumentGebeurtenis.tijdstip.desc(), DocumentGebeurtenis.id.desc())
    ).first()
    if jongste is None or (jongste.detail or {}).get(TIJDLIJN_MARKER) is not True:
        return None  # geen afvoer, of de jongste afvoer was een gewone duplicaat-afvoer → geen herstel naar geboekt
    return jongste


def herstel_bewust_verwijderd(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, rol: GebruikerRol, reden: str
) -> HerstelResultaat:
    """Terugweg: document terug naar geboekt (statusmachine AFGEVOERD_DUPLICAAT → GEBOEKT, alleen hiervoor) en de
    bijbehorende acceptatie ingetrokken (de bevinding telt bij de volgende run weer mee). Reden verplicht en
    inhoudelijk (≥ 5 tekens, dezelfde maat als intrekken)."""
    _vereis_beheerder_binnen_scope(administratie_id=administratie_id, actor_id=actor_id, rol=rol)
    reden_tekst = (reden or "").strip()
    if len(reden_tekst) < 5:
        raise BewustVerwijderdFout("Terugdraaien vereist een inhoudelijke reden")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise BevindingNietGevonden("Document niet gevonden")
        if document.status != DocumentStatus.AFGEVOERD_DUPLICAAT:
            raise NietTerugdraaibaar("Alleen een als bewust verwijderd afgevoerd document kan terug naar geboekt")
        spoor = _laatste_bewust_verwijderd_spoor(session, document_id)
        if spoor is None:
            raise NietTerugdraaibaar("Dit document is niet via 'Bewust verwijderd in RLZ' afgevoerd")
        spoor_detail = dict(spoor.detail or {})
        acceptatie_id = spoor_detail.get("acceptatie_id")
        acceptatie: ReconciliatieAcceptatie | None = None
        if acceptatie_id:
            acceptatie = session.get(ReconciliatieAcceptatie, uuid.UUID(str(acceptatie_id)))
            if acceptatie is not None:
                session.expunge(acceptatie)
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.GEBOEKT,
            actor_id=actor_id,
            detail={
                f"{TIJDLIJN_MARKER}_hersteld": True,
                "reden": f"bewust-verwijderd teruggedraaid: {reden_tekst}",
                "acceptatie_id": acceptatie_id,
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie=AUDIT_HERSTELD,
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": DocumentStatus.AFGEVOERD_DUPLICAAT.value},
            nieuwe_waarde={
                "status": DocumentStatus.GEBOEKT.value,
                "reden": reden_tekst,
                "acceptatie_id": acceptatie_id,
            },
            administratie_id=administratie_id,
        )

    ingetrokken: uuid.UUID | None = None
    if acceptatie is not None and acceptatie.ingetrokken_op is None:
        try:
            ingetrokken = acceptatie_service.trek_in(
                administratie_id=administratie_id,
                bron=acceptatie.bron,
                vingerafdruk_waarde=acceptatie.vingerafdruk,
                reden=f"bewust-verwijderd teruggedraaid: {reden_tekst}",
                beheerder_id=actor_id,
            )
        except acceptatie_service.AcceptatieFout:
            ingetrokken = None  # status is hersteld; de acceptatie stond al niet meer open — niets te doen
    return HerstelResultaat(
        document_id=document_id,
        document_status_nieuw=DocumentStatus.GEBOEKT.value,
        acceptatie_ingetrokken_id=ingetrokken,
    )
