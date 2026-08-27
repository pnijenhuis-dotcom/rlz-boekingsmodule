"""Document verplaatsen naar een andere administratie — herstel van een foute toewijzing
(addendum kantoor-run 27-08 punt 5, besluit Peter 27-08).

Wat er gebeurt, in één transactie op de BRON-scope die halverwege naar de DOEL-scope wisselt:
1. poorten: soort inkoopfactuur, status in VERPLAATSBARE_STATUSSEN (geboekt = storno-/tegenboekpad,
   ter_accordering = eerst intrekken — server-side afgedwongen), actor heeft scope op bron én doel;
2. administratie-specifiek werk weg: boekvoorstel + regels (grootboek/crediteur/project/btw zijn
   per administratie betekenisloos in het doel), klaargezette doorbelasting-run → vervallen, open
   afwijzing → heropend (het document krijgt in het doel een verse controle), open vraag blijft
   open en verhuist mee (terugweg-status wordt te_controleren);
3. bestand + brondocument gekopieerd naar het doel-prefix van de opslag (oude objecten blijven
   staan — de documentenbucket draagt 7 jaar retentie, verwijderen kan daar niet en hoeft niet);
4. tijdlijnregel + statusovergang → ONTVANGEN (statusmachine; "verplaatst van X naar Y door Z"),
   het veldvoorstel vervalt expliciet (`veldvoorstel_vervallen`) — de extractie draait opnieuw;
5. toewijzings-geheugen leert mee terug (intake.toewijzing.corrigeer_toewijzing_na_verplaatsing);
6. DB-functie `boekhouding.verplaats_document` (migratie 0080, SECURITY DEFINER — de enige plek
   die het RLS-beleid voor deze verhuizing passeert, gepoort op bron-scope + status ontvangen)
   verhuist document + kindrijen met eigen administratie_id;
7. in de doel-scope: duplicaatvlag opnieuw bepaald, vraag-toegewezenen zonder doel-scope naar de
   doel-eigenaar, platform-breed audit_event `document_verplaatst`;
8. ná de commit: `start_extractie_na_toewijzing` in het doel — exact het ene extractiepad achter de
   gates van de dóél-administratie (26-08 punt 4); de post-extractie-hook herberekent
   duplicaatsignaal/factuurmatch/materiaalmatch dáár, en een open vraag zet het document weer op
   vraag_open (service._herstel_open_vraag_na_extractie).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerAdministratie, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.documenten.models import (
    Afwijzing,
    AfwijzingStatus,
    Boekvoorstel,
    BoekvoorstelRegel,
    Document,
    DocumentSoort,
    DocumentStatus,
    Vraag,
    VraagStatus,
)
from app.documenten.service import (
    DocumentNietGevonden,
    _schrijf_overgang,
    _standaard_opslag,
    start_extractie_na_toewijzing,
)
from app.documenten.storage import DocumentOpslag
from app.documenten.wachtrij import ExtractieWachtrij
from app.intake.toewijzing import corrigeer_toewijzing_na_verplaatsing, leer_toewijzing


class VerplaatsenNietToegestaan(Exception):
    """Status/soort/doel laten verplaatsen niet toe — de melding legt uit waarom (router: 409)."""


class GeenScopeOpDoel(Exception):
    """De actor heeft geen toegang tot de doeladministratie (router: 403)."""


class OnbekendeDoelAdministratie(Exception):
    """Doeladministratie bestaat niet (router: 404)."""


# Alleen de niet-geboekte kantoorbak-statussen. Geboekt en ter_accordering zijn bewust uitgesloten
# (besluit Peter 27-08); de overige statussen zijn tussenstanden waarin verplaatsen geen zin heeft
# of een lopende flow zou doorkruisen — zie reden_niet_verplaatsbaar.
VERPLAATSBARE_STATUSSEN = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
        DocumentStatus.VRAAG_OPEN,
        DocumentStatus.AFGEWEZEN,
    }
)

_REDEN_PER_STATUS: dict[DocumentStatus, str] = {
    DocumentStatus.GEBOEKT: (
        "Een geboekt document verplaats je niet — draai de boeking eerst terug (storno in RLZ of "
        '"Tegenboeken…"); daarna kan het document verplaatst worden.'
    ),
    DocumentStatus.TER_ACCORDERING: (
        "Het document ligt bij de klant ter accordering — trek de accordering eerst in, dan kan het verplaatst worden."
    ),
    DocumentStatus.WACHT_OP_IBAN_ACCORDERING: (
        "Er loopt een IBAN-accordering op dit document — rond die eerst af (accorderen of afwijzen)."
    ),
    DocumentStatus.BOEKEN_MISLUKT: (
        "De laatste boekpoging is mislukt — herstel eerst (terug naar te controleren), dan kan het "
        "document verplaatst worden."
    ),
    DocumentStatus.ONTVANGEN: "De extractie is nog niet gestart — wacht tot het document te controleren is.",
    DocumentStatus.EXTRACTIE_WACHTRIJ: "De extractie staat in de wachtrij — wacht tot het document te controleren is.",
    DocumentStatus.EXTRACTIE_BEZIG: "De extractie loopt nog — wacht tot het document te controleren is.",
    DocumentStatus.NIET_TOEGEWEZEN: (
        "Dit document staat in de verzamelbak — wijs het dáár toe aan de juiste administratie."
    ),
    DocumentStatus.VERWIJDERD: "Een verwijderd document verplaats je niet — herstel het eerst.",
    DocumentStatus.GESPLITST: "Een gesplitst brondocument verplaats je niet — verplaats de losse delen.",
}


def reden_niet_verplaatsbaar(status: DocumentStatus) -> str | None:
    """None = verplaatsen mag; anders de uitleg voor UI/409 (frontend spiegelt de statuslijst, de
    backend blijft de waarheid)."""
    if status in VERPLAATSBARE_STATUSSEN:
        return None
    return _REDEN_PER_STATUS.get(status, f"Verplaatsen is niet mogelijk vanuit status {status.value}.")


@dataclass(frozen=True)
class VerplaatsResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    van_administratie_id: uuid.UUID
    van_administratie_naam: str
    naar_administratie_id: uuid.UUID
    naar_administratie_naam: str
    leerregels_gecorrigeerd: tuple[str, ...]
    vragen_verhuisd: int
    vragen_hertoegewezen: int
    tenaamstelling_geleerd: bool = False


def _heeft_scope(session: Session, *, gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> bool:
    """Zelfde regel als deps.vereis_administratie_scope / vragen._controleer_toegewezene_scope:
    actieve Beheerder = platform-breed, anders een gebruiker_administratie-rij op déze administratie.
    De sessie MOET op `administratie_id` gescoped zijn (RLS-les 25-08)."""
    gebruiker = session.get(Gebruiker, gebruiker_id)
    if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
        return False
    if gebruiker.rol == GebruikerRol.BEHEERDER:
        return True
    return session.get(GebruikerAdministratie, (gebruiker_id, administratie_id)) is not None


def _kopieer_bestanden(opslag: DocumentOpslag, *, document: Document, doel_administratie_id: uuid.UUID) -> None:
    """Document + brondocument naar het doel-prefix (`{administratie}/{document}…`, service.upload_document).
    Eerst álle bytes lezen, dan schrijven — een leesfout laat niets half achter; de oude objecten
    blijven staan (retentie-bucket). Paden op het Document worden bijgewerkt, nog in de bron-scope
    (administratie_id ongewijzigd → WITH CHECK slaagt)."""
    nieuw_pad = f"{doel_administratie_id}/{document.id}{Path(document.opslag_pad).suffix.lower()}"
    inhoud = opslag.lezen(pad=document.opslag_pad)
    bron_inhoud: bytes | None = None
    nieuw_bron_pad: str | None = None
    if document.bron_opslag_pad is not None:
        bron_inhoud = opslag.lezen(pad=document.bron_opslag_pad)
        nieuw_bron_pad = f"{nieuw_pad}.bron{Path(document.bron_opslag_pad).suffix.lower()}"
    opslag.opslaan(pad=nieuw_pad, inhoud=inhoud)
    if nieuw_bron_pad is not None and bron_inhoud is not None:
        opslag.opslaan(pad=nieuw_bron_pad, inhoud=bron_inhoud)
    document.opslag_pad = nieuw_pad
    if nieuw_bron_pad is not None:
        document.bron_opslag_pad = nieuw_bron_pad


def _laat_klaargezette_doorbelasting_vervallen(session: Session, *, document: Document, actor_id: uuid.UUID) -> int:
    """Een klaargezette verdeling (besluit 25-08) hoort bij de bron-whitelist en is in het doel
    betekenisloos → VERVALLEN, nooit een delete (zelfde spoor + audit als doorbelasting.service.
    laat_run_vervallen; hier ín de verhuis-transactie). Runs mét boekingen bestaan op een
    niet-geboekt document niet (poort: status ≠ geboekt)."""
    from app.doorbelasting.models import DoorbelastingRun, DoorbelastingRunStatus  # lokaal: importgraaf klein houden

    runs = list(
        session.scalars(
            select(DoorbelastingRun).where(
                DoorbelastingRun.document_id == document.id,
                DoorbelastingRun.status == DoorbelastingRunStatus.KLAARGEZET.value,
            )
        )
    )
    for run in runs:
        run.status = DoorbelastingRunStatus.VERVALLEN.value
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="doorbelasting_run",
            record_id=run.id,
            actie="doorbelasting_run_vervallen",
            correlatie_id=document.id,
            oude_waarde={"status": DoorbelastingRunStatus.KLAARGEZET.value},
            nieuwe_waarde={"status": run.status, "reden": "document_verplaatst"},
            administratie_id=document.administratie_id,
        )
    return len(runs)


def verplaats_document(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    doel_administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_rol: GebruikerRol,
    opslag: DocumentOpslag | None = None,
    wachtrij: ExtractieWachtrij | None = None,
    onthoud_tenaamstelling: bool = False,
) -> VerplaatsResultaat:
    if doel_administratie_id == administratie_id:
        raise VerplaatsenNietToegestaan(
            "Het document staat al in deze administratie — kies een andere doeladministratie."
        )
    opslag = opslag or _standaard_opslag()

    # Scope-toets op het DOEL (de bron toetst de router-dependency). RLS-les 25-08: de lookup op
    # gebruiker_administratie leest in scoped_session(<doel>, actor_id=actor).
    with scoped_session(doel_administratie_id, actor_id=actor_id) as session:
        doel = session.get(Administratie, doel_administratie_id)
        if doel is None:
            raise OnbekendeDoelAdministratie(f"Onbekende doeladministratie: {doel_administratie_id}")
        doel_naam = doel.naam
        doel_eigenaar_id = doel.eigenaar_gebruiker_id
        if actor_rol != GebruikerRol.BEHEERDER and not _heeft_scope(
            session, gebruiker_id=actor_id, administratie_id=doel_administratie_id
        ):
            raise GeenScopeOpDoel(f"Geen toegang tot de doeladministratie {doel_naam}")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.soort != DocumentSoort.INKOOPFACTUUR.value:
            raise VerplaatsenNietToegestaan(
                "Verplaatsen is beschikbaar voor inkoopfacturen; kassarapporten, verkoopfacturen en "
                "waarborgberichten zijn aan hun administratie gebonden."
            )
        reden = reden_niet_verplaatsbaar(document.status)
        if reden is not None:
            raise VerplaatsenNietToegestaan(reden)
        bron = session.get(Administratie, administratie_id)
        bron_naam = bron.naam if bron is not None else str(administratie_id)
        van_status = document.status

        # --- 2. administratie-specifiek werk weg / afsluiten (bron-scope) -------------------------
        session.execute(delete(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == document_id))
        session.execute(delete(Boekvoorstel).where(Boekvoorstel.document_id == document_id))
        runs_vervallen = _laat_klaargezette_doorbelasting_vervallen(session, document=document, actor_id=actor_id)

        afwijzing_gesloten: uuid.UUID | None = None
        open_afwijzing = session.scalars(
            select(Afwijzing).where(
                Afwijzing.document_id == document_id, Afwijzing.status == AfwijzingStatus.OPEN.value
            )
        ).first()
        if open_afwijzing is not None:
            open_afwijzing.status = AfwijzingStatus.HEROPEND.value
            open_afwijzing.heropend_door = actor_id
            open_afwijzing.heropend_op = datetime.now(UTC)
            afwijzing_gesloten = open_afwijzing.id

        open_vragen = list(
            session.scalars(
                select(Vraag).where(Vraag.document_id == document_id, Vraag.status == VraagStatus.OPEN.value)
            )
        )
        for vraag in open_vragen:
            # De her-extractie in het doel bepaalt de nieuwe herkomst; tot die tijd is te_controleren
            # de veilige terugweg (CHECK vraag_herkomst_herstelbaar laat 'm toe).
            vraag.status_voor_vraag = DocumentStatus.TE_CONTROLEREN.value
        document.toegewezen_aan = None
        document.mogelijk_duplicaat_van_id = None  # herbepaald in het doel

        # --- 3. bestanden naar het doel-prefix ---------------------------------------------------
        _kopieer_bestanden(opslag, document=document, doel_administratie_id=doel_administratie_id)

        # --- 5 (vóór 4, zodat het in de tijdlijnregel landt): toewijzings-geheugen leert mee terug —
        # platform-brede tabel, onafhankelijk van de scope. NB het tijdlijn-detail is een gewone dict
        # die bij de flush als JSONB wordt weggeschreven; alles wat erin moet, moet er vóór
        # _schrijf_overgang in staan.
        gecorrigeerd = corrigeer_toewijzing_na_verplaatsing(
            session,
            van_administratie_id=administratie_id,
            naar_administratie_id=doel_administratie_id,
            actor_id=actor_id,
            tenaamstelling=document.tenaamstelling,
            afzender=document.afzender_hint,
        )
        # Punt 6a (werkstroom-run 27/28-08): op expliciet verzoek ("onthoud: deze tenaamstelling
        # hoort bij <doel>", default UIT) leert het geheugen een tenaamstelling-regel naar het doel —
        # de vulling voor het register-match-gat (toewijzing zonder leer-regel). Alleen de
        # tenaamstelling, nooit de afzender (die is een hint, geen bewijs); is de regel net al door
        # de correctie hierboven gezet, dan is leer_toewijzing een no-op.
        tenaamstelling_geleerd = False
        if onthoud_tenaamstelling and document.tenaamstelling:
            leer_toewijzing(
                session,
                administratie_id=doel_administratie_id,
                actor_id=actor_id,
                tenaamstelling=document.tenaamstelling,
                afzender=None,
            )
            tenaamstelling_geleerd = True

        # --- 4. tijdlijn + status → ontvangen (statusmachine) -------------------------------------
        detail: dict = {
            "verplaatst": {
                "van_administratie_id": str(administratie_id),
                "van_administratie_naam": bron_naam,
                "naar_administratie_id": str(doel_administratie_id),
                "naar_administratie_naam": doel_naam,
                "van_status": van_status.value,
            },
            "veldvoorstel_vervallen": True,
        }
        if afwijzing_gesloten is not None:
            detail["afwijzing_gesloten_door_verplaatsing"] = str(afwijzing_gesloten)
        if open_vragen:
            detail["vragen_verhuisd"] = [str(v.id) for v in open_vragen]
        if runs_vervallen:
            detail["doorbelasting_runs_vervallen"] = runs_vervallen
        if gecorrigeerd:
            detail["leerregels_gecorrigeerd"] = list(gecorrigeerd)
        if tenaamstelling_geleerd:
            detail["tenaamstelling_geleerd"] = document.tenaamstelling
        _schrijf_overgang(session, document=document, naar=DocumentStatus.ONTVANGEN, actor_id=actor_id, detail=detail)
        session.flush()

        # --- 6. de verhuizing zelf (SECURITY DEFINER, migratie 0080) -----------------------------
        session.execute(
            text("SELECT boekhouding.verplaats_document(:document_id, :van, :naar)"),
            {"document_id": document_id, "van": administratie_id, "naar": doel_administratie_id},
        )

        # --- 7. verder in de DOEL-scope, zelfde transactie ---------------------------------------
        session.expire_all()
        session.execute(
            text("SELECT set_config('app.current_administratie_id', :value, true)"),
            {"value": str(doel_administratie_id)},
        )
        document = session.get(Document, document_id)
        if document is None:  # pragma: no cover — kan alleen als de DB-functie stil niets deed
            raise RuntimeError("Verplaatsing niet zichtbaar in de doeladministratie")

        duplicaat = session.scalars(
            select(Document)
            .where(
                Document.administratie_id == doel_administratie_id,
                Document.sha256_hash == document.sha256_hash,
                Document.id != document_id,
                Document.status != DocumentStatus.VERWIJDERD,
            )
            .order_by(Document.aangemaakt_op)
        ).first()
        document.mogelijk_duplicaat_van_id = duplicaat.id if duplicaat is not None else None

        hertoegewezen = 0
        vragen_in_doel = list(
            session.scalars(
                select(Vraag).where(Vraag.document_id == document_id, Vraag.status == VraagStatus.OPEN.value)
            )
        )
        if vragen_in_doel:
            vervanger: uuid.UUID | None = None
            if doel_eigenaar_id is not None and _heeft_scope(
                session, gebruiker_id=doel_eigenaar_id, administratie_id=doel_administratie_id
            ):
                vervanger = doel_eigenaar_id
            else:
                vervanger = actor_id
            for vraag in vragen_in_doel:
                gewijzigd = False
                if not _heeft_scope(session, gebruiker_id=vraag.toegewezen_aan, administratie_id=doel_administratie_id):
                    vraag.toegewezen_aan = vervanger
                    gewijzigd = True
                beurt = vraag.aan_de_beurt or vraag.toegewezen_aan
                if not _heeft_scope(session, gebruiker_id=beurt, administratie_id=doel_administratie_id):
                    vraag.aan_de_beurt = vervanger
                    vraag.aan_de_beurt_sinds = datetime.now(UTC)
                    gewijzigd = True
                if gewijzigd:
                    hertoegewezen += 1
            # Werkvoorraad-kolom "Toegewezen" volgt de beurt van de open vraag (vragen.py-conventie).
            eerste = vragen_in_doel[0]
            document.toegewezen_aan = eerste.aan_de_beurt or eerste.toegewezen_aan

        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="document_verplaatst",
            correlatie_id=uuid.uuid4(),
            oude_waarde={
                "administratie_id": str(administratie_id),
                "administratie_naam": bron_naam,
                "status": van_status.value,
            },
            nieuwe_waarde={
                "administratie_id": str(doel_administratie_id),
                "administratie_naam": doel_naam,
                "leerregels_gecorrigeerd": list(gecorrigeerd),
                "vragen_verhuisd": len(vragen_in_doel),
                "vragen_hertoegewezen": hertoegewezen,
            },
            # Platform-breed feit (administratie_id=None): de verhuizing raakt twee administraties
            # en moet vanuit beide zichtbaar zijn — zelfde keuze als toewijzing_regel_geleerd.
            administratie_id=None,
        )
        vragen_verhuisd = len(vragen_in_doel)

    # --- 8. ná de commit: het ene extractiepad, achter de gates van de doeladministratie ---------
    eind_status = start_extractie_na_toewijzing(
        administratie_id=doel_administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        opslag=opslag,
        wachtrij=wachtrij,
    )
    # Een open vraag zet het document ná de extractie weer op vraag_open (service-hook) — de
    # eindstatus van start_extractie_na_toewijzing is dan al die status.
    return VerplaatsResultaat(
        document_id=document_id,
        status=eind_status,
        van_administratie_id=administratie_id,
        van_administratie_naam=bron_naam,
        naar_administratie_id=doel_administratie_id,
        naar_administratie_naam=doel_naam,
        leerregels_gecorrigeerd=gecorrigeerd,
        vragen_verhuisd=vragen_verhuisd,
        vragen_hertoegewezen=hertoegewezen,
        tenaamstelling_geleerd=tenaamstelling_geleerd,
    )
