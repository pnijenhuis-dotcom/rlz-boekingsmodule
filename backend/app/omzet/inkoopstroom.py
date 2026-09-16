"""Omzet die als INKOOPFACTUUR geboekt is (Peter 16-09, casus Van Boxtel: "omzetrapporten komen in RLZ onder Uitgaven,
wél op de omzet-grootboekrekeningen"). STAP-0 16-09 bewees: die documenten zijn PurchaseInvoices (DocumentType 1,
categorie onder binder Uitgaven, mét crediteur, omschrijving "Samengevoegd (N regels)") — de kassarapporten liepen
via de inkoopstroom. Twee signalen, beide deterministisch: (a) álle boekingsregels landen op een omzetrekening
(naam bevat "omzet"), (b) de PDF is een herkende omzetbron (ProfX; herkenning op de tekstlaag — duurder, alleen op
verzoek). Herstel = storno (actie 19) achter de aangiftepoort + herclassificatie naar kassarapport; de mens boekt
daarna als omzet (Receipt onder Inkomsten). Nooit iets verwijderen in RLZ."""

from __future__ import annotations

import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import GebruikerRol, Grootboekrekening
from app.db.session import scoped_session
from app.documenten import herboeken
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentSoort, DocumentStatus
from app.documenten.rlz_ids import rlz_herboeking_id
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import DocumentOpslag, standaard_opslag
from app.rlz.client import RlzApiError

logger = logging.getLogger(__name__)

SOORT = "omzet_in_inkoopstroom"
#: Blok C 16-09 avond: hetzelfde signaal op ONGEBOEKTE inkoopfactuur-documenten in de werkvoorraad — de handeling is
#: "Type wijzigen → kassarapport" (bestaande soort-wissel), geen storno.
SOORT_WERKVOORRAAD = "kassarapport_in_werkvoorraad"
#: Werkvoorraad-statussen waarin de soort-wissel kan (zelfde set als verplaatsen/soort.py).
WERKVOORRAAD_STATUSSEN = (
    DocumentStatus.TE_CONTROLEREN,
    DocumentStatus.HANDMATIG_AFMAKEN,
    DocumentStatus.KLAAR_OM_TE_BOEKEN,
    DocumentStatus.VRAAG_OPEN,
)
#: Begrenzing per administratie voor de PDF-tekstlaag-lezing in de dagelijkse run (geen "PDF-lezing van alles": alleen
#: de werkvoorraad, en die is klein; de geboekte historie leest alleen de CLI met --met-pdf).
MAX_PDF_LEZINGEN_PER_ADMINISTRATIE = 200


@dataclass(frozen=True)
class Treffer:
    document_id: uuid.UUID
    bestandsnaam: str
    boekstuknummer: str | None
    factuurdatum: date | None
    referentie: str | None
    signaal: str  # 'omzetrekeningen' | bron van de PDF-herkenning
    regels_totaal: int
    regels_op_omzet: int
    boek_cyclus: int


def _is_omzetrekening(naam: str | None) -> bool:
    return "omzet" in (naam or "").casefold()


def geboekte_kassarapporten_in_inkoopstroom(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    dagen: int = 400,
    met_pdf: bool = False,
    opslag: DocumentOpslag | None = None,
) -> list[Treffer]:
    """GEBOEKTE inkoopfactuur-documenten van deze administratie waarvan alle regels op een omzetrekening staan, of —
    mét `met_pdf` — waarvan de PDF een omzetbron is. Alleen documenten mét minstens één regel tellen."""
    sinds = datetime.now(UTC) - timedelta(days=dagen)
    docs = list(
        session.scalars(
            select(Document).where(
                Document.administratie_id == administratie_id,
                Document.soort == DocumentSoort.INKOOPFACTUUR.value,
                Document.status == DocumentStatus.GEBOEKT,
                Document.aangemaakt_op >= sinds,
            )
        )
    )
    if not docs:
        return []
    doc_ids = [d.id for d in docs]
    regels = session.execute(
        select(BoekvoorstelRegel.document_id, func.count(), func.count(Grootboekrekening.ledger_id))
        .select_from(BoekvoorstelRegel)
        .outerjoin(
            Grootboekrekening,
            (Grootboekrekening.ledger_id == BoekvoorstelRegel.ledger_id)
            & (Grootboekrekening.administratie_id == administratie_id)
            & Grootboekrekening.naam.ilike("%omzet%"),
        )
        .where(BoekvoorstelRegel.document_id.in_(doc_ids))
        .group_by(BoekvoorstelRegel.document_id)
    ).all()
    per_doc = {did: (int(totaal), int(omzet)) for did, totaal, omzet in regels}
    voorstellen = {
        v.document_id: v for v in session.scalars(select(Boekvoorstel).where(Boekvoorstel.document_id.in_(doc_ids)))
    }
    uit: list[Treffer] = []
    for doc in docs:
        totaal, omzet = per_doc.get(doc.id, (0, 0))
        v = voorstellen.get(doc.id)
        signaal: str | None = None
        if totaal > 0 and omzet == totaal:
            signaal = "omzetrekeningen"
        elif met_pdf and doc.bestandsnaam.lower().endswith(".pdf"):
            from app.omzet.bronnen import herkenning

            try:
                signaal = herkenning.herken_pdf((opslag or standaard_opslag()).lezen(pad=doc.opslag_pad))
            except Exception:  # noqa: BLE001 — onleesbaar bestand telt niet
                signaal = None
        if signaal is None:
            continue
        uit.append(
            Treffer(
                document_id=doc.id,
                bestandsnaam=doc.bestandsnaam,
                boekstuknummer=v.rlz_boekstuknummer if v else None,
                factuurdatum=v.factuurdatum if v else None,
                referentie=v.referentie if v else None,
                signaal=signaal,
                regels_totaal=totaal,
                regels_op_omzet=omzet,
                boek_cyclus=int(v.boek_cyclus or 0) if v else 0,
            )
        )
    return uit


@dataclass(frozen=True)
class WerkvoorraadTreffer:
    document_id: uuid.UUID
    bestandsnaam: str
    status: str
    signaal: str  # 'omzetrekeningen' | bron van de PDF-herkenning (profx_journaal, …)
    regels_totaal: int
    regels_op_omzet: int


def ongeboekte_kassarapporten_in_inkoopstroom(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    dagen: int = 400,
    opslag: DocumentOpslag | None = None,
    max_pdf_lezingen: int = MAX_PDF_LEZINGEN_PER_ADMINISTRATIE,
) -> list[WerkvoorraadTreffer]:
    """Blok C (Peter 16-09 avond): INKOOPFACTUUR-documenten in de werkvoorraad die op inhoud een kassarapport zijn —
    (a) de PDF is een herkende omzetbron (ProfX/…; herkenning op de tekstlaag, begrensd tot de werkvoorraad) óf (b) alle
    boekingsregels staan op een omzetrekening. Bevinding mét actie "Type wijzigen → kassarapport"; nooit automatisch
    herclassificeren (de mens klikt, of kiest bulk in de documentenlijst)."""
    sinds = datetime.now(UTC) - timedelta(days=dagen)
    docs = list(
        session.scalars(
            select(Document)
            .where(
                Document.administratie_id == administratie_id,
                Document.soort == DocumentSoort.INKOOPFACTUUR.value,
                Document.status.in_(WERKVOORRAAD_STATUSSEN),
                Document.aangemaakt_op >= sinds,
            )
            .order_by(Document.aangemaakt_op)
        )
    )
    if not docs:
        return []
    doc_ids = [d.id for d in docs]
    regels = session.execute(
        select(BoekvoorstelRegel.document_id, func.count(), func.count(Grootboekrekening.ledger_id))
        .select_from(BoekvoorstelRegel)
        .outerjoin(
            Grootboekrekening,
            (Grootboekrekening.ledger_id == BoekvoorstelRegel.ledger_id)
            & (Grootboekrekening.administratie_id == administratie_id)
            & Grootboekrekening.naam.ilike("%omzet%"),
        )
        .where(BoekvoorstelRegel.document_id.in_(doc_ids))
        .group_by(BoekvoorstelRegel.document_id)
    ).all()
    per_doc = {did: (int(totaal), int(omzet)) for did, totaal, omzet in regels}
    from app.omzet.bronnen import herkenning

    lezer = opslag or standaard_opslag()
    gelezen = 0
    uit: list[WerkvoorraadTreffer] = []
    for doc in docs:
        totaal, omzet = per_doc.get(doc.id, (0, 0))
        signaal: str | None = None
        if totaal > 0 and omzet == totaal:
            signaal = "omzetrekeningen"
        elif doc.bestandsnaam.lower().endswith(".pdf") and gelezen < max_pdf_lezingen:
            gelezen += 1
            try:
                signaal = herkenning.herken_pdf(lezer.lezen(pad=doc.opslag_pad))
            except Exception:  # noqa: BLE001 — onleesbaar/ontbrekend bestand telt niet
                signaal = None
        if signaal is None:
            continue
        uit.append(
            WerkvoorraadTreffer(
                document_id=doc.id,
                bestandsnaam=doc.bestandsnaam,
                status=doc.status.value if hasattr(doc.status, "value") else str(doc.status),
                signaal=signaal,
                regels_totaal=totaal,
                regels_op_omzet=omzet,
            )
        )
    return uit


@dataclass(frozen=True)
class TypeWijzigResultaat:
    document_id: uuid.UUID
    status: str
    van_soort: str
    naar_soort: str
    doel_pad: str


def type_wijzigen_kassarapport_vanuit_bevinding(
    *, bevinding_id: uuid.UUID, administratie_id: uuid.UUID, actor_id: uuid.UUID, rol: GebruikerRol
) -> TypeWijzigResultaat:
    """"Type wijzigen → kassarapport" vanuit Inzicht › Reconciliatie op `kassarapport_in_werkvoorraad`: exact de
    bestaande
    soort-wissel (documenten/soort.py — terug naar ONTVANGEN, extractie opnieuw via het omzetpad, tijdlijn + audit).
    Alleen binnen de scope van de actor; 422 op een andere bevindingssoort; de poorten van de soort-wissel (geboekt,
    ter accordering) blijven die van de enkelvoudige route (409)."""
    from app.auth import service as auth_service
    from app.documenten import soort as soort_service
    from app.reconciliatie.models import BevindingSoort, ReconciliatieBevinding

    if administratie_id not in {a.id for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol)}:
        raise herboeken.GeenToegang("Geen toegang tot deze administratie")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        b = session.get(ReconciliatieBevinding, bevinding_id)
        if b is None or b.administratie_id != administratie_id:
            raise herboeken.BevindingNietGevonden("Bevinding niet gevonden")
        d = dict(b.detail or {})
        blok, soort = b.blok, b.soort
    if blok != "omzet" or soort not in (BevindingSoort.AFWIJKING.value, BevindingSoort.UITGESLOTEN.value):
        raise herboeken.HerboekenFout("Type wijzigen geldt alleen voor een omzet-afwijking")
    if d.get("afwijking_soort") != SOORT_WERKVOORRAAD or not d.get("document_id"):
        raise herboeken.HerboekenFout(
            "Type wijzigen geldt alleen voor een kassarapport dat als inkoopfactuur in de werkvoorraad staat"
        )
    document_id = uuid.UUID(str(d["document_id"]))
    try:
        r = soort_service.wijzig_documentsoort(
            administratie_id=administratie_id,
            document_id=document_id,
            soort=DocumentSoort.KASSARAPPORT,
            actor_id=actor_id,
        )
    except soort_service.SoortWisselNietToegestaan as exc:
        raise herboeken.HerboekenFout(str(exc)) from exc
    status = r.status.value if hasattr(r.status, "value") else str(r.status)
    return TypeWijzigResultaat(
        document_id=document_id,
        status=status,
        van_soort=r.van_soort,
        naar_soort=r.naar_soort,
        doel_pad=f"/?administratie={administratie_id}&document={document_id}",
    )


@dataclass(frozen=True)
class HerboekResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    doel_pad: str
    gestorneerd: bool


def herboek_als_omzet(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    rol: GebruikerRol | None,
    reden: str,
    btw_niet_in_aangifte_bevestigd: bool = False,
    bevestiging_reden: str | None = None,
    client=None,  # noqa: ANN001 — test-seam
    port=None,  # noqa: ANN001 — test-seam
) -> HerboekResultaat:
    """Herstelroute (blok C): (1) aangiftepoort op de factuurdatum van de inkoopboeking — ingediende periode of niet
    leesbaar = 409 `btw_mogelijk_aangegeven`, alleen een Beheerder zet door mét reden (zelfde regels als opnieuw
    boeken); (2) storno actie 19 van de PurchaseInvoice (404 = al weg, verder); (3) document geboekt → te_controleren
    mét boek_cyclus +1, neveneffecten teruggedraaid, audit `herboekt_als_omzet`; (4) documentsoort → kassarapport
    (bestaande type-wissel: extractie opnieuw via het omzetpad, deterministisch voor ProfX). De mens boekt daarna in
    het omzet-controlescherm als Receipt onder Inkomsten. Nooit een delete."""
    if len((reden or "").strip()) < herboeken.MIN_REDEN_LENGTE:
        raise herboeken.HerboekenFout(f"Reden is verplicht (minimaal {herboeken.MIN_REDEN_LENGTE} tekens)")
    reden = reden.strip()
    if btw_niet_in_aangifte_bevestigd:
        if rol != GebruikerRol.BEHEERDER:
            raise herboeken.GeenToegang(
                "Alleen een Beheerder kan bevestigen dat de btw van dit document niet in de ingediende aangifte zat"
            )
        if len((bevestiging_reden or "").strip()) < herboeken.MIN_REDEN_LENGTE:
            raise herboeken.HerboekenFout(
                "Reden van de bevestiging 'btw niet in aangifte' is verplicht (minimaal 5 tekens)"
            )
        bevestiging_reden = (bevestiging_reden or "").strip()
    else:
        bevestiging_reden = None

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            raise herboeken.HerboekenFout("Document niet gevonden")
        if document.status != DocumentStatus.GEBOEKT or document.soort != DocumentSoort.INKOOPFACTUUR.value:
            raise herboeken.HerboekenFout("Herboeken als omzet geldt alleen voor een GEBOEKTE inkoopfactuur")
        voorstel = session.get(Boekvoorstel, document_id)
        if voorstel is None:
            raise herboeken.HerboekenFout("Het document heeft geen boekvoorstel — herboeken kan niet")
        boek_cyclus = int(voorstel.boek_cyclus or 0)
        boekdatum = voorstel.factuurdatum
        oud_boekstuknummer = voorstel.rlz_boekstuknummer
    rlz_id = rlz_herboeking_id(document_id, boek_cyclus)

    eigen_port = port is None
    port = port or herboeken._port_voor(administratie_id)  # noqa: SLF001 — bewust dezelfde poort als opnieuw boeken
    try:
        btw_toets = herboeken._toets_btw_periode(port, boekdatum)  # noqa: SLF001
    finally:
        if eigen_port:
            port.__exit__(None, None, None)
    if not btw_toets.toegestaan and not btw_niet_in_aangifte_bevestigd:
        raise herboeken.BtwMogelijkAangegeven(toets=btw_toets, boekdatum=boekdatum, backend=port.backend.value)
    doorgezet = bool(btw_niet_in_aangifte_bevestigd and not btw_toets.toegestaan)

    # Storno in RLZ (actie 19) — vóór de lokale statuswissel, zodat er nooit lokaal 'te_controleren' staat terwijl
    # RLZ nog een geboekte inkoopfactuur kent. 404 = het stuk bestaat al niet meer: verder.
    from app.documenten.boeken import _rlz_client_voor

    eigen_client = client is None
    client = client or _rlz_client_voor(administratie_id)
    gestorneerd = False
    try:
        try:
            client.correct_purchase_invoice(rlz_id)
            gestorneerd = True
        except RlzApiError as exc:
            if exc.status_code != 404:
                raise herboeken.HerboekenFout(f"Storno van de inkoopfactuur in RLZ mislukte: {exc}") from exc
    finally:
        if eigen_client:
            with contextlib.suppress(Exception):
                client.close()

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        voorstel = session.get(Boekvoorstel, document_id)
        assert document is not None and voorstel is not None
        if int(voorstel.boek_cyclus or 0) != boek_cyclus:
            raise herboeken.HerboekenFout("Het document is intussen gewijzigd — laad het scherm opnieuw")
        voorstel.boek_cyclus = boek_cyclus + 1
        voorstel.rlz_boekstuknummer = None
        detail = {
            "herboekt_als_omzet": {
                "reden": reden,
                "oud_rlz_document_id": str(rlz_id),
                "oud_boekstuknummer": oud_boekstuknummer,
                "gestorneerd": gestorneerd,
                "oude_cyclus": boek_cyclus,
                "nieuwe_cyclus": boek_cyclus + 1,
                "btw_poort": {
                    "boekdatum": boekdatum.isoformat() if boekdatum else None,
                    "toegestaan": btw_toets.toegestaan,
                    "reden": btw_toets.reden,
                    "doorgezet_met_bevestiging": doorgezet,
                },
                "btw_niet_in_aangifte_bevestigd": (
                    {"door": str(actor_id), "rol": rol.value if rol else None, "reden": bevestiging_reden}
                    if btw_niet_in_aangifte_bevestigd
                    else None
                ),
            },
            "reden": (
                f"omzet was als inkoopfactuur geboekt ({oud_boekstuknummer or str(rlz_id)[:8]}) — gestorneerd en "
                f"herclassificeerd naar kassarapport: {reden}"
                + (
                    f" — ná Beheerder-bevestiging 'btw niet in de ingediende aangifte': {bevestiging_reden}"
                    if doorgezet
                    else ""
                )
            ),
        }
        _schrijf_overgang(
            session, document=document, naar=DocumentStatus.TE_CONTROLEREN, actor_id=actor_id, detail=detail
        )
        from app.documenten import autoboeken as autoboeken_service
        from app.mini_voorraad import instroom as mini_voorraad_instroom
        from app.verplichting import match_pipeline as verplichting_match

        verplichting_match.draai_verbruik_terug_in_sessie(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor_id,
            reden=f"omzet als inkoop geboekt — herboekt als omzet: {reden}",
        )
        mini_voorraad_instroom.registreer_storno(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            boek_cyclus=boek_cyclus,
            actor_id=actor_id,
            reden=f"omzet als inkoop geboekt — herboekt als omzet: {reden}",
        )
        autoboeken_service.reset_na_correctie_in_sessie(
            session, administratie_id=administratie_id, document_id=document_id, reden="correctie", actor_id=actor_id
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="boekvoorstel",
            record_id=document_id,
            actie="herboekt_als_omzet",
            correlatie_id=uuid.uuid4(),
            oude_waarde={
                "boek_cyclus": boek_cyclus,
                "rlz_boekstuknummer": oud_boekstuknummer,
                "status": "geboekt",
                "soort": DocumentSoort.INKOOPFACTUUR.value,
            },
            nieuwe_waarde={
                **detail["herboekt_als_omzet"],
                "status": DocumentStatus.TE_CONTROLEREN.value,
                "soort": DocumentSoort.KASSARAPPORT.value,
            },
            administratie_id=administratie_id,
        )

    from app.documenten import soort as soort_service

    uitkomst = soort_service.wijzig_documentsoort(
        administratie_id=administratie_id, document_id=document_id, soort=DocumentSoort.KASSARAPPORT, actor_id=actor_id
    )
    eind = uitkomst.status
    if not isinstance(eind, DocumentStatus):
        eind = DocumentStatus(eind) if eind else DocumentStatus.ONTVANGEN
    return HerboekResultaat(
        document_id=document_id,
        status=eind,
        doel_pad=f"/?administratie={administratie_id}&document={document_id}",
        gestorneerd=gestorneerd,
    )


def herboek_als_omzet_vanuit_bevinding(
    *,
    bevinding_id: uuid.UUID,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    reden: str,
    btw_niet_in_aangifte_bevestigd: bool = False,
    bevestiging_reden: str | None = None,
) -> HerboekResultaat:
    """Ingang vanuit Inzicht › Reconciliatie: alleen op een omzet-afwijking `omzet_in_inkoopstroom` binnen de scope."""
    from app.auth import service as auth_service
    from app.reconciliatie.models import BevindingSoort, ReconciliatieBevinding

    if administratie_id not in {a.id for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol)}:
        raise herboeken.GeenToegang("Geen toegang tot deze administratie")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        b = session.get(ReconciliatieBevinding, bevinding_id)
        if b is None or b.administratie_id != administratie_id:
            raise herboeken.BevindingNietGevonden("Bevinding niet gevonden")
        d = dict(b.detail or {})
        blok, soort = b.blok, b.soort
    if blok != "omzet" or soort not in (BevindingSoort.AFWIJKING.value, BevindingSoort.UITGESLOTEN.value):
        raise herboeken.HerboekenFout("Herboeken als omzet geldt alleen voor een omzet-afwijking")
    if d.get("afwijking_soort") != SOORT or not d.get("document_id"):
        raise herboeken.HerboekenFout("Herboeken als omzet geldt alleen als omzet als inkoopfactuur geboekt is")
    return herboek_als_omzet(
        administratie_id=administratie_id,
        document_id=uuid.UUID(str(d["document_id"])),
        actor_id=actor_id,
        rol=rol,
        reden=reden,
        btw_niet_in_aangifte_bevestigd=btw_niet_in_aangifte_bevestigd,
        bevestiging_reden=bevestiging_reden,
    )
