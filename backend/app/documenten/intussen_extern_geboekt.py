"""Intussen buiten de module geboekt (Peter 22-09, casus Bouwadvies Oost Nederland / Beter Assemblage F/2026/01235):
een document dat bij ons op `ter_accordering` (of `wacht_op_iban_accordering` / `klaar_om_te_boeken` ouder dan een dag)
staat, terwijl dezelfde factuur intussen rechtstreeks in Reeleezee/Odoo is geboekt. Tot 22-09 zag de module dat pas ná
het laatste klant-akkoord (harde check Duplicaatcheck blokkeerde het boeken) — drie accordeurs klikten voor niets en het
signaal kwam vijf dagen te laat.

Dit bestand draagt de drie bouwstenen rond de dagelijkse hercontrole (`app/documenten/reconciliatie.py::
hercontroleer_open_documenten`, bevindingssoort `intussen_extern_geboekt` in blok `documenten`):

1. `open_treffers(session, administratie_id)` — de documenten van een administratie mét een OPEN bevinding
   `intussen_extern_geboekt` in de laatste afgeronde run (niet geaccepteerd), voor de accordeur-app (banner, uit "Te
   accorderen", "Wachten op kantoor") en de herinneringen (onderdrukt). Eén sessie, twee statements, geen eigen
   `scoped_session` (de wachtrij telt statements per administratie).
2. `wijs_af_al_geboekt(...)` — "Afwijzen — al geboekt als ‹RLZ-04-…›": lopende accorderingsronde vervalt mét de
   tijdlijnregel "niet meer nodig: al geboekt in Reeleezee (RLZ-04-…)" (accordeurs zien de factuur niet meer), daarna de
   BESTAANDE afwijs-route `afwijzen.wijs_af` mét voorgevulde reden + kruisverwijzing naar het externe boekstuk. Geen
   tweede schrijver: ronde-vervallen = `accordering.service.laat_ronde_vervallen_wegens_extern_geboekt`, afwijzing =
   `afwijzen.wijs_af`.
3. `toch_verschillend(...)` — "Toch verschillend — doorgaan": de mens verklaart mét reden dat het externe stuk een
   ándere factuur is. Tijdlijnregel zonder statusovergang (`extern_duplicaat_toch_verschillend` + de externe id's),
   audit, checks-cache van de crediteur ongeldig. Daarna telt precies dit externe stuk niet meer mee: niet in de
   hercontrole (geen nieuwe bevinding) en niet in de harde check Duplicaatcheck op het boekmoment
   (`afgemelde_extern_ids` reist mee
   als uitgezonderde id). Een Beheerder accepteert in dezelfde handeling ook de open bevinding (bestaande schrijver);
   een andere kantoorrol niet — de bevinding verdwijnt dan bij de volgende run (auto-gesloten mét audit), zichtbaar
   gemeld.

Nooit stil: élke poort geeft een leesbare fout mét de route (409/422), élke handeling tijdlijn + audit. Geen migratie:
de afmelding leeft in de append-only tijdlijn (`document_gebeurtenis.detail`), zoals `duplicaat_afgemeld`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import service as auth_service
from app.db.audit import record_audit_event
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentStatus
from app.reconciliatie.models import BevindingSoort, ReconciliatieBevinding, ReconciliatieRun, ReconciliatieRunStatus

#: Bevindingssoort in blok `documenten` (registry `app/reconciliatie/soort_stand.py`, tekst `teksten.py`).
SOORT = "intussen_extern_geboekt"
#: Tijdlijn-sleutel van "Toch verschillend — doorgaan" (zonder statusovergang), zoals `duplicaat_afgemeld`.
TOCH_VERSCHILLEND_SLEUTEL = "extern_duplicaat_toch_verschillend"
TOCH_VERSCHILLEND_EXTERN_IDS = "extern_ids"
AUDIT_TOCH_VERSCHILLEND = "extern_duplicaat_toch_verschillend"
#: Tijdlijn-marker op de vervallen ronde (accordeur-kant: "niet meer nodig: al geboekt in Reeleezee").
VERVALLEN_MARKER = "accordering_vervallen_extern_geboekt"
MIN_REDEN_LENGTE = 5
#: Statussen waarop de kantoor-handelingen mogen: ter_accordering (ronde vervalt eerst) en klaar_om_te_boeken.
AFWIJSBARE_STATUSSEN = frozenset({DocumentStatus.TER_ACCORDERING, DocumentStatus.KLAAR_OM_TE_BOEKEN})


class ExternGeboektFout(Exception):
    """Basis; de router vertaalt subklassen naar 403/404/409/422."""


class DocumentNietGevonden(ExternGeboektFout):
    pass


class GeenToegang(ExternGeboektFout):
    pass


class StatusNietToegestaan(ExternGeboektFout):
    """Document staat op een status waarop deze handeling niet kan (bv. wacht_op_iban_accordering → eerst die route)."""


class RedenVerplicht(ExternGeboektFout):
    pass


class AlVastgelegd(ExternGeboektFout):
    """Dezelfde externe id is al als "toch verschillend" afgemeld op dit document."""


@dataclass(frozen=True)
class OpenTreffer:
    """Open bevinding `intussen_extern_geboekt` op één document (voor app-banner en herinneringsfilter)."""

    document_id: uuid.UUID
    bevinding_id: uuid.UUID
    extern_boekstuk: str | None
    extern_id: str | None
    systeem: str  # "Reeleezee" | "Odoo"
    #: "geboekt" | "concept" — RLZ-status 1 = concept (banner zegt dan "staat al als concept in …").
    extern_stand: str


@dataclass(frozen=True)
class AfwijsResultaat:
    document_id: uuid.UUID
    status: str
    reden: str
    accordering_vervallen: bool
    afwijzing_id: uuid.UUID


@dataclass(frozen=True)
class TochVerschillendResultaat:
    document_id: uuid.UUID
    extern_ids: tuple[str, ...]
    reden: str
    #: True als de actor Beheerder is en de open bevinding in dezelfde handeling geaccepteerd is.
    bevinding_geaccepteerd: bool
    checks_cache_ongeldig: int


def systeem_label(backend: str | None) -> str:
    return "Odoo" if (backend or "").lower() == "odoo" else "Reeleezee"


# ---- lezen ----------------------------------------------------------------------------------------------------------


def afgemelde_extern_ids(session: Session, document_id: uuid.UUID) -> frozenset[str]:
    """Externe id's die een mens op dít document als "toch verschillend" heeft afgemeld (tijdlijn, append-only) — telt
    nooit meer als treffer in de hercontrole én reist als uitgezonderde id mee in de harde check Duplicaatcheck."""
    rijen = session.scalars(
        select(DocumentGebeurtenis.detail).where(
            DocumentGebeurtenis.document_id == document_id,
            DocumentGebeurtenis.detail.has_key(TOCH_VERSCHILLEND_SLEUTEL),
        )
    ).all()
    uit: set[str] = set()
    for detail in rijen:
        for extern_id in (detail or {}).get(TOCH_VERSCHILLEND_EXTERN_IDS) or []:
            if extern_id:
                uit.add(str(extern_id))
    return frozenset(uit)


def open_treffers(session: Session, *, administratie_id: uuid.UUID) -> dict[uuid.UUID, OpenTreffer]:
    """Per document de OPEN bevinding `intussen_extern_geboekt` uit de laatste afgeronde run van deze administratie
    (soort afwijking, niet geaccepteerd in de run zelf én geen actieve acceptatie erop). Twee statements in de
    meegegeven (gescoopte) sessie; geen open run = leeg. Wordt door de accordeur-wachtrij, de aan-de-beurt-bron van de
    herinneringen en de handmatige herinnerknop gelezen — één definitie."""
    from app.reconciliatie.models import ReconciliatieAcceptatie

    laatste_run = (
        select(ReconciliatieRun.id)
        .where(ReconciliatieRun.afgerond_op.is_not(None), ReconciliatieRun.status == ReconciliatieRunStatus.KLAAR.value)
        .order_by(ReconciliatieRun.afgerond_op.desc())
        .limit(1)
        .scalar_subquery()
    )
    bevindingen = session.scalars(
        select(ReconciliatieBevinding).where(
            ReconciliatieBevinding.run_id == laatste_run,
            ReconciliatieBevinding.administratie_id == administratie_id,
            ReconciliatieBevinding.blok == "documenten",
            ReconciliatieBevinding.soort == BevindingSoort.AFWIJKING.value,
            ReconciliatieBevinding.detail["afwijking_soort"].astext == SOORT,
        )
    ).all()
    if not bevindingen:
        return {}
    geaccepteerd = set(
        session.scalars(
            select(ReconciliatieAcceptatie.vingerafdruk).where(
                ReconciliatieAcceptatie.administratie_id == administratie_id,
                ReconciliatieAcceptatie.bron == "documenten",
                ReconciliatieAcceptatie.ingetrokken_op.is_(None),
                ReconciliatieAcceptatie.vingerafdruk.in_([b.vingerafdruk for b in bevindingen]),
            )
        ).all()
    )
    uit: dict[uuid.UUID, OpenTreffer] = {}
    for b in bevindingen:
        d = b.detail or {}
        if d.get("geaccepteerd") or b.vingerafdruk in geaccepteerd or not d.get("document_id"):
            continue
        try:
            document_id = uuid.UUID(str(d["document_id"]))
        except ValueError:
            continue
        uit.setdefault(
            document_id,
            OpenTreffer(
                document_id=document_id,
                bevinding_id=b.id,
                extern_boekstuk=(str(d["extern_boekstuk"]) if d.get("extern_boekstuk") else None),
                extern_id=(str(d["extern_id"]) if d.get("extern_id") else None),
                systeem=systeem_label(d.get("backend") if isinstance(d.get("backend"), str) else None),
                extern_stand=str(d.get("extern_stand") or "geboekt"),
            ),
        )
    return uit


def open_treffers_voor_administratie(*, administratie_id: uuid.UUID) -> dict[uuid.UUID, OpenTreffer]:
    """Eigen sessie-variant (herinneringsjobs)."""
    with scoped_session(administratie_id) as session:
        return open_treffers(session, administratie_id=administratie_id)


def banner_tekst(treffer: OpenTreffer) -> str:
    """De ene zin voor de accordeur-app (opdracht 22-09, letterlijk): 'Al geboekt in Reeleezee (RLZ-04-…) — kantoor
    beoordeelt; akkoord niet nodig'. Een RLZ-concept zegt 'Staat al als concept in …'."""
    boekstuk = f" ({treffer.extern_boekstuk})" if treffer.extern_boekstuk else ""
    if treffer.extern_stand == "concept":
        return f"Staat al als concept in {treffer.systeem}{boekstuk} — kantoor beoordeelt; akkoord niet nodig"
    return f"Al geboekt in {treffer.systeem}{boekstuk} — kantoor beoordeelt; akkoord niet nodig"


# ---- handelingen -----------------------------------------------------------------------------------------------------


def _vereis_scope(*, administratie_id: uuid.UUID, actor_id: uuid.UUID, rol: GebruikerRol) -> None:
    if rol == GebruikerRol.KLANT_ACCORDEUR:
        raise GeenToegang("Deze handeling is voor het kantoor — de accordeur hoeft niets te doen")
    if administratie_id not in {a.id for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol)}:
        raise GeenToegang("Geen toegang tot deze administratie")


def afwijs_reden(*, systeem: str, extern_boekstuk: str | None) -> str:
    return f"Al geboekt in {systeem} als {extern_boekstuk or 'boekstuk onbekend'} (buiten de module)"


def vervallen_reden(*, systeem: str, extern_boekstuk: str | None) -> str:
    """De tijdlijnregel naar de accordeurs (opdracht 22-09, letterlijk)."""
    return f"niet meer nodig: al geboekt in {systeem}" + (f" ({extern_boekstuk})" if extern_boekstuk else "")


def wijs_af_al_geboekt(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    extern_boekstuk: str | None,
    extern_id: str | None,
    systeem: str,
    toelichting: str | None = None,
) -> AfwijsResultaat:
    """ "Afwijzen — al geboekt als ‹boekstuk›". Volgorde (elke stap eigen transactie, tijdlijn + audit, nooit stil):
    (1) poorten: scope/rol, document bestaat, status ∈ {ter_accordering, klaar_om_te_boeken} —
    `wacht_op_iban_accordering` = 409 mét route ("laat de tweede persoon de IBAN-accordering eerst afwijzen"), andere
    statussen 409;
    (2) bij ter_accordering: de ronde vervalt mét reden "niet meer nodig: al geboekt in …" (gemarkeerd
    `accordering_vervallen_extern_geboekt` — géén herstelwerk in de werkvoorraad-banner; open vragen aan de accordeur
    sluiten mét dezelfde reden als slotbericht); (3) de bestaande afwijs-route mét voorgevulde reden +
    kruisverwijzing."""
    from app.accordering import service as accordering_service
    from app.documenten import afwijzen, vragen

    _vereis_scope(administratie_id=administratie_id, actor_id=actor_id, rol=rol)
    systeem_tekst = "Odoo" if systeem.lower() == "odoo" else "Reeleezee"
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        status = document.status
        voorstel = session.get(Boekvoorstel, document_id)
        referentie = voorstel.referentie if voorstel is not None else None
    if status == DocumentStatus.WACHT_OP_IBAN_ACCORDERING:
        raise StatusNietToegestaan(
            "Dit document wacht op de IBAN-accordering (vier ogen). Laat de tweede persoon die aanvraag eerst afwijzen "
            "of accorderen; daarna kan het document hier als 'al geboekt' worden afgewezen."
        )
    if status not in AFWIJSBARE_STATUSSEN:
        raise StatusNietToegestaan(
            f"Vanuit status {status.value} kan dit document niet als 'al geboekt' worden afgewezen — alleen vanuit "
            "ter accordering of klaar om te boeken."
        )
    reden_ronde = vervallen_reden(systeem=systeem_tekst, extern_boekstuk=extern_boekstuk)
    accordering_vervallen = False
    if status == DocumentStatus.TER_ACCORDERING:
        for vraag_id in vragen.open_vraag_ids_van_document(administratie_id=administratie_id, document_id=document_id):
            vragen.sluit_vraag_wegens_duplicaat(
                administratie_id=administratie_id, vraag_id=vraag_id, actor_id=actor_id, reden=reden_ronde
            )
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            accordering_vervallen = (
                accordering_service.laat_ronde_vervallen_wegens_extern_geboekt(
                    session,
                    administratie_id=administratie_id,
                    document_id=document_id,
                    actor_id=actor_id,
                    reden=reden_ronde,
                    extern_boekstuk=extern_boekstuk,
                )
                > 0
            )
    reden = afwijs_reden(systeem=systeem_tekst, extern_boekstuk=extern_boekstuk)
    toelichting_tekst = (toelichting or "").strip()
    if toelichting_tekst:
        reden = f"{reden} — {toelichting_tekst}"
    extern_uuid: uuid.UUID | None = None
    if extern_id:
        try:
            extern_uuid = uuid.UUID(str(extern_id))
        except ValueError:
            extern_uuid = None
    afwijzing = afwijzen.wijs_af(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        reden=reden,
        duplicaat_van_rlz_document_id=extern_uuid,
        duplicaat_van_referentie=referentie,
    )
    return AfwijsResultaat(
        document_id=document_id,
        status=DocumentStatus.AFGEWEZEN.value,
        reden=reden,
        accordering_vervallen=accordering_vervallen,
        afwijzing_id=afwijzing.id,
    )


def toch_verschillend(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    extern_id: str | None,
    extern_boekstuk: str | None,
    reden: str,
    bevinding_id: uuid.UUID | None = None,
) -> TochVerschillendResultaat:
    """ "Toch verschillend — doorgaan": zie module-docstring. `extern_id` verplicht (zonder id valt er niets uit te
    zonderen — dan is 'accepteren mét reden' op de bevinding de route, 422)."""
    from app.documenten import checks_extern
    from app.reconciliatie import kantoorbreed

    _vereis_scope(administratie_id=administratie_id, actor_id=actor_id, rol=rol)
    reden_tekst = (reden or "").strip()
    if len(reden_tekst) < MIN_REDEN_LENGTE:
        raise RedenVerplicht(f"Geef een inhoudelijke reden (minimaal {MIN_REDEN_LENGTE} tekens)")
    extern = (extern_id or "").strip()
    if not extern:
        raise RedenVerplicht(
            "Zonder id van het externe stuk valt er niets uit te zonderen — accepteer de bevinding mét reden"
        )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if extern in afgemelde_extern_ids(session, document_id):
            raise AlVastgelegd(f"{extern_boekstuk or extern} is op dit document al als 'toch verschillend' vastgelegd")
        detail = {
            TOCH_VERSCHILLEND_SLEUTEL: True,
            TOCH_VERSCHILLEND_EXTERN_IDS: [extern],
            "extern_boekstuk": extern_boekstuk,
            "reden": reden_tekst,
        }
        gebeurtenis = DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail=detail,
        )
        session.add(gebeurtenis)
        voorstel = session.get(Boekvoorstel, document_id)
        cache_ongeldig = 0
        if voorstel is not None and voorstel.vendor_id is not None:
            # Het gecachte externe rapport (0165) draagt nog de blokkerende treffer — ongeldig maken op de bron
            # (les 21-09).
            cache_ongeldig = checks_extern.maak_ongeldig_voor_vendor(
                session, administratie_id=administratie_id, vendor_id=voorstel.vendor_id
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document.id,
            actie=AUDIT_TOCH_VERSCHILLEND,
            correlatie_id=gebeurtenis.id,
            nieuwe_waarde={**detail, "checks_cache_ongeldig": cache_ongeldig},
            administratie_id=administratie_id,
        )
        session.flush()
    geaccepteerd = False
    if bevinding_id is not None and rol == GebruikerRol.BEHEERDER:
        try:
            kantoorbreed.accepteer(
                bevinding_id=bevinding_id,
                administratie_id=administratie_id,
                reden=f"Toch verschillend — {reden_tekst}",
                actor_id=actor_id,
                rol=rol,
            )
            geaccepteerd = True
        except kantoorbreed.ReconciliatieFout:
            # Al geaccepteerd / verkeerde soort: de afmelding zelf staat; de bevinding verdwijnt bij de volgende run.
            geaccepteerd = False
    return TochVerschillendResultaat(
        document_id=document_id,
        extern_ids=(extern,),
        reden=reden_tekst,
        bevinding_geaccepteerd=geaccepteerd,
        checks_cache_ongeldig=cache_ongeldig,
    )

