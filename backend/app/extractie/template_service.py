"""DB-kant van de deterministische extractie-terugval (best-practice-besluit 2, 31-08): templates
leren ná een menselijke boeking, toepassen vóór het AI-pad, ongeldig markeren mét reden + audit, en de
maandtelling voor Instellingen. De pure logica (ankers, parsen, validaties, crediteur-herkenning)
staat in template_terugval.py; hier alleen sessies, modellen en audit.

Volgorde per binnenkomend PDF (documenten/service.py::_pdf_extractie_detail):
  a. geldig template + tekstlaag → template-parse (alle validaties groen, anders VOLLEDIG verwerpen
     + template ongeldig) — NIET achter de AI-AVG-gate: lokale code, er gaat niets naar buiten, werkt
     dus ook voor administraties met AI-extractie uit;
  b. AI-pad exact zoals het was; c. AI niet beschikbaar + geen template → handmatig-pad, ongewijzigd.

Leren (`leer_na_boeking`, post-commit ná élke boeking): uitsluitend uit documenten die een mens
bevestigde — automatisch geboekte documenten (`automatisch_geboekt`) tellen niet als leerbron. Het
bestaande template moet het zojuist geboekte document exact reproduceren; doet het dat niet (de
controleur corrigeerde een template-waarde, of de layout wijzigde), dan wordt het ongeldig en leert
het systeem direct opnieuw uit de laatste N bevestigde documenten. Geen handmatig templatebeheer.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.aikosten.service import TIJDZONE, huidige_maand
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import (
    Boekvoorstel,
    BoekvoorstelRegel,
    Document,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
    LeverancierIban,
)
from app.documenten.storage import DocumentOpslag
from app.extractie import controle as extractie_controle
from app.extractie import template_terugval as tt
from app.extractie.models import ExtractieTemplate
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld

logger = logging.getLogger(__name__)

_PDF_SUFFIX = ".pdf"


# --- Sleutels ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sleutel:
    sleutel: str
    soort: str  # 'btw_nummer' | 'kvk_nummer' | 'administratie_vendor'


def sleutels_voor(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, btw_nummer: str | None, kvk_nummer: str | None
) -> list[Sleutel]:
    """Sleutels in voorkeursvolgorde: kenmerk (werkt over administraties heen) vóór administratie+crediteur."""
    sleutels: list[Sleutel] = []
    if btw_nummer:
        sleutels.append(Sleutel(f"btw:{btw_nummer}", "btw_nummer"))
    if kvk_nummer:
        sleutels.append(Sleutel(f"kvk:{kvk_nummer}", "kvk_nummer"))
    sleutels.append(Sleutel(f"adm:{administratie_id}:{vendor_id}", "administratie_vendor"))
    return sleutels


def _zoek_template(session: Session, sleutels: list[Sleutel], *, alleen_geldig: bool) -> ExtractieTemplate | None:
    for s in sleutels:
        rij = session.scalar(select(ExtractieTemplate).where(ExtractieTemplate.sleutel == s.sleutel))
        if rij is not None and (rij.geldig or not alleen_geldig):
            return rij
    return None


def _markeer_ongeldig(
    session: Session,
    template: ExtractieTemplate,
    *,
    reden: str,
    document_id: uuid.UUID,
    administratie_id: uuid.UUID | None,
) -> None:
    oud = {"geldig": template.geldig, "versie": template.versie}
    template.geldig = False
    template.ongeldig_op = datetime.now(UTC)
    template.ongeldig_reden = reden
    record_audit_event(
        session,
        actor_id=SYSTEEM_ACTOR_ID,
        module="boekhouding",
        tabel="extractie_template",
        record_id=template.id,
        actie="extractie_template_ongeldig",
        correlatie_id=document_id,
        oude_waarde=oud,
        nieuwe_waarde={"geldig": False, "reden": reden, "document_id": str(document_id), "sleutel": template.sleutel},
        administratie_id=administratie_id,
    )
    logger.info("Extractie-template %s ongeldig: %s", template.sleutel, reden)


# --- Toepassen (runtime) ---------------------------------------------------------------------------


def _ibans_per_vendor(session: Session, administratie_id: uuid.UUID) -> dict[str, uuid.UUID]:
    return {
        rij.iban: rij.vendor_id
        for rij in session.scalars(select(LeverancierIban).where(LeverancierIban.administratie_id == administratie_id))
    }


def _als_extractie(
    uitkomst: tt.TemplateUitkomst,
    *,
    leverancier_naam: str,
    herkenning: tt.Herkenning,
    btw_nummer: str | None,
    kvk_nummer: str | None,
) -> AiFactuurExtractie:
    """Template-uitkomst in de vorm van de controlelaag (zekerheid 1.0: deterministisch gelezen) — zo
    lopen vendor-match, btw-afleiding per regel, regelsom-toets en het veldvoorstel-contract onveranderd."""

    def veld(waarde: str | None) -> AiVeld:
        return AiVeld(waarde=waarde, zekerheid=1.0)

    kop = {
        "leverancier_naam": veld(leverancier_naam),
        "factuurnummer": veld(uitkomst.factuurnummer),
        "factuurdatum": veld(uitkomst.factuurdatum.isoformat()),
        "vervaldatum": veld(uitkomst.vervaldatum.isoformat() if uitkomst.vervaldatum else None),
        "valuta": veld(None),
        "totaal_excl": veld(str(uitkomst.totaal_excl)),
        "totaal_incl": veld(str(uitkomst.totaal_incl)),
        "btw_bedrag": veld(str(uitkomst.btw_bedrag)),
        "iban": veld(herkenning.waarde if herkenning.soort == "iban" else None),
        "btw_verlegd_vermelding": veld(None),
        "btw_nummer": veld(btw_nummer),
        "kvk_nummer": veld(kvk_nummer),
    }
    regels = [
        AiRegel(
            omschrijving=r.omschrijving,
            netto_bedrag=str(r.netto),
            btw_bedrag=str(r.btw),
            hoeveelheid=None,
            zekerheid=1.0,
        )
        for r in uitkomst.regels
    ]
    return AiFactuurExtractie(kop=kop, regels=regels, bsn_verwijderd=0, volledig=True)


def template_extractie_detail(
    session: Session,
    *,
    document: Document,
    inhoud: bytes,
    vendors: list[extractie_controle.VendorKandidaat],
    taxrates: list[extractie_controle.TaxRateKandidaat],
) -> tuple[dict | None, str | None]:
    """Stap a van de extractievolgorde. Retourneert (tijdlijn-detail, notitie): een detail mét
    veldvoorstel (bron "template") bij succes; anders None + een korte notitie voor de tijdlijn van
    het AI-pad ("template verworpen: …") of None als er simpelweg geen template van toepassing was."""
    if document.administratie_id is None or document.soort != DocumentSoort.INKOOPFACTUUR.value:
        return None, None
    if not session.scalar(
        select(func.count()).select_from(ExtractieTemplate).where(ExtractieTemplate.geldig.is_(True))
    ):
        return None, None  # geen enkel geldig template: tekstlaag lezen is dan verspilde moeite
    tekst = tt.lees_tekstlaag(inhoud)
    if tekst is None:
        return None, None
    herkenning = tt.herken_crediteur(tekst, vendors, ibans=_ibans_per_vendor(session, document.administratie_id))
    if herkenning is None:
        return None, None
    kandidaat = next((k for k in vendors if k.id == herkenning.vendor_id), None)
    if kandidaat is None:
        return None, None
    sleutels = sleutels_voor(
        administratie_id=document.administratie_id,
        vendor_id=herkenning.vendor_id,
        btw_nummer=kandidaat.btw_nummer,
        kvk_nummer=kandidaat.kvk_nummer,
    )
    template = _zoek_template(session, sleutels, alleen_geldig=True)
    if template is None:
        return None, None
    modus = str(template.definitie.get("tekst_modus") or "layout")
    if tekst.modus != modus:
        tekst = tt.lees_tekstlaag(inhoud, modus=modus)
        if tekst is None:
            return None, None
    try:
        uitkomst = tt.pas_template_toe(template.definitie, tekst)
    except tt.TemplateVerworpen as exc:
        _markeer_ongeldig(
            session,
            template,
            reden=f"verworpen op nieuw document: {exc}",
            document_id=document.id,
            administratie_id=document.administratie_id,
        )
        return None, f"template verworpen ({exc}) — template ongeldig gemarkeerd, AI-pad gevolgd"

    extractie = _als_extractie(
        uitkomst,
        leverancier_naam=kandidaat.naam,
        herkenning=herkenning,
        btw_nummer=kandidaat.btw_nummer if herkenning.soort == "btw_nummer" else None,
        kvk_nummer=kandidaat.kvk_nummer if herkenning.soort == "kvk_nummer" else None,
    )
    voorstel = extractie_controle.bouw_veldvoorstel(
        extractie, vendors=vendors, taxrates=taxrates, zekerheid_drempel=settings.ai_extractie_zekerheid_drempel
    )
    voorstel["bron"] = "template"
    # De crediteur is deterministisch herkend — dat wint van de naam-match in de controlelaag.
    voorstel["vendor_suggestie"] = {
        "vendor_id": str(herkenning.vendor_id),
        "match": "exact" if herkenning.soort == "naam" else herkenning.soort,
    }
    voorstel["template"] = {
        "id": str(template.id),
        "sleutel_soort": template.sleutel_soort,
        "versie": template.versie,
        "herkend_op": herkenning.soort,
        "velden": uitkomst.velden_bron,
        "btw_percentage": uitkomst.btw_percentage,
    }
    template.gebruikt_aantal = (template.gebruikt_aantal or 0) + 1
    template.laatst_gebruikt_op = datetime.now(UTC)
    return {"veldvoorstel": voorstel, "extractie_bron": "template"}, None


# --- Leren (ná een menselijke boeking) -----------------------------------------------------------


def _is_automatisch_geboekt(session: Session, document_id: uuid.UUID) -> bool:
    detail = session.scalar(
        select(DocumentGebeurtenis.detail)
        .where(
            DocumentGebeurtenis.document_id == document_id, DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT
        )
        .order_by(DocumentGebeurtenis.tijdstip.desc())
        .limit(1)
    )
    return bool(detail and detail.get("automatisch_geboekt"))


def _leerdocument_van(
    session: Session, *, document: Document, voorstel: Boekvoorstel, opslag: DocumentOpslag
) -> tt.Leerdocument | None:
    """Bevestigde waarden uit het geboekte boekvoorstel (referentie, datums, totaal incl.; excl/btw = de
    sommen van de bevestigde regels) + de tekstlaag. None als het document niet als leerbron kan
    dienen (geen tekstlaag, onvolledige kop, totalen die niet sluiten) — nooit gokken."""
    if not voorstel.referentie or voorstel.factuurdatum is None or voorstel.totaalbedrag is None:
        return None
    regels = list(
        session.scalars(
            select(BoekvoorstelRegel)
            .where(BoekvoorstelRegel.document_id == document.id)
            .order_by(BoekvoorstelRegel.volgnummer)
        )
    )
    if not regels or any(r.netto_bedrag is None or r.btw_bedrag is None for r in regels):
        return None
    excl = sum((r.netto_bedrag for r in regels), Decimal(0))
    btw = sum((r.btw_bedrag for r in regels), Decimal(0))
    if excl + btw != voorstel.totaalbedrag:
        return None
    try:
        inhoud = opslag.lezen(pad=document.opslag_pad)
    except Exception:  # noqa: BLE001 — een onleesbaar bestand is geen leerbron, geen fout
        logger.warning("Template-leren: bestand van document %s niet leesbaar", document.id, exc_info=True)
        return None
    tekst = tt.lees_tekstlaag(inhoud)
    if tekst is None:
        return None
    return tt.Leerdocument(
        document_id=str(document.id),
        tekst=tekst,
        factuurnummer=voorstel.referentie.strip(),
        factuurdatum=voorstel.factuurdatum,
        vervaldatum=voorstel.vervaldatum,
        totaal_excl=excl,
        btw_bedrag=btw,
        totaal_incl=voorstel.totaalbedrag,
        regels=tuple(
            tt.BevestigdeRegel(netto=r.netto_bedrag, btw=r.btw_bedrag, omschrijving=r.omschrijving) for r in regels
        ),
    )


def _laatste_bevestigde_documenten(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, aantal: int
) -> list[tuple[Document, Boekvoorstel]]:
    """De laatste `aantal` door een MENS geboekte PDF-inkoopfacturen van deze crediteur (nieuwste
    eerst; automatisch geboekte documenten overgeslagen)."""
    rijen = session.execute(
        select(Document, Boekvoorstel, DocumentGebeurtenis.detail, DocumentGebeurtenis.tijdstip)
        .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
        .join(DocumentGebeurtenis, DocumentGebeurtenis.document_id == Document.id)
        .where(
            Document.administratie_id == administratie_id,
            Document.status == DocumentStatus.GEBOEKT,
            Document.soort == DocumentSoort.INKOOPFACTUUR.value,
            Boekvoorstel.vendor_id == vendor_id,
            DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
            func.lower(Document.bestandsnaam).like(f"%{_PDF_SUFFIX}"),
        )
        .order_by(DocumentGebeurtenis.tijdstip.desc())
    ).all()
    gezien: set[uuid.UUID] = set()
    uit: list[tuple[Document, Boekvoorstel]] = []
    for document, voorstel, detail, _tijdstip in rijen:
        if document.id in gezien:
            continue
        gezien.add(document.id)
        if detail and detail.get("automatisch_geboekt"):
            continue
        uit.append((document, voorstel))
        if len(uit) >= aantal:
            break
    return uit


def leer_na_boeking(*, administratie_id: uuid.UUID, document_id: uuid.UUID, opslag: DocumentOpslag) -> None:
    """Post-commit ná een boeking (documenten/boeken.py). Toetst het bestaande template tegen het
    zojuist bevestigde document (afwijking = ongeldig mét reden + audit) en leert (opnieuw) uit de
    laatste N bevestigde documenten van deze crediteur. Fouten worden gelogd, nooit een blokkade
    van de boeking zelf."""
    from app.documenten.crediteur_kenmerk import kenmerken_per_vendor  # lokaal: importgraaf klein houden

    aantal = settings.extractie_template_leer_aantal
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, document_id)
        voorstel = session.get(Boekvoorstel, document_id)
        if (
            document is None
            or voorstel is None
            or voorstel.vendor_id is None
            or document.soort != DocumentSoort.INKOOPFACTUUR.value
            or not document.bestandsnaam.lower().endswith(_PDF_SUFFIX)
            or _is_automatisch_geboekt(session, document_id)
        ):
            return
        vendor_id = voorstel.vendor_id
        kenmerk = kenmerken_per_vendor(session, administratie_id=administratie_id).get(vendor_id)
        sleutels = sleutels_voor(
            administratie_id=administratie_id,
            vendor_id=vendor_id,
            btw_nummer=kenmerk.btw_nummer if kenmerk else None,
            kvk_nummer=kenmerk.kvk_nummer if kenmerk else None,
        )
        bestaand = _zoek_template(session, sleutels, alleen_geldig=False)
        if bestaand is not None and bestaand.geldig:
            leerdoc = _leerdocument_van(session, document=document, voorstel=voorstel, opslag=opslag)
            if leerdoc is None or tt.reproduceert(bestaand.definitie, leerdoc):
                return  # geen tekstlaag = geen uitspraak; reproduceert = template blijft
            _markeer_ongeldig(
                session,
                bestaand,
                reden="reproduceert de door de controleur bevestigde waarden niet (correctie of layoutwijziging)",
                document_id=document_id,
                administratie_id=administratie_id,
            )

        leerdocumenten: list[tt.Leerdocument] = []
        for doc, vs in _laatste_bevestigde_documenten(
            session, administratie_id=administratie_id, vendor_id=vendor_id, aantal=aantal
        ):
            leerdoc = _leerdocument_van(session, document=doc, voorstel=vs, opslag=opslag)
            if leerdoc is not None:
                leerdocumenten.append(leerdoc)
        resultaat = tt.leer_template(leerdocumenten, minimum=aantal)
        if resultaat.definitie is None:
            logger.info("Geen extractie-template voor %s: %s", sleutels[0].sleutel, resultaat.reden)
            return

        doel = sleutels[0]
        rij = session.scalar(select(ExtractieTemplate).where(ExtractieTemplate.sleutel == doel.sleutel))
        nu = datetime.now(UTC)
        geleerd_uit = [d.document_id for d in leerdocumenten]
        if rij is None:
            rij = ExtractieTemplate(
                sleutel=doel.sleutel,
                sleutel_soort=doel.soort,
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                definitie=resultaat.definitie,
                geleerd_uit=geleerd_uit,
                geleerd_op=nu,
                versie=1,
                geldig=True,
            )
            session.add(rij)
            session.flush()
            oud = None
        else:
            oud = {"versie": rij.versie, "geldig": rij.geldig, "ongeldig_reden": rij.ongeldig_reden}
            rij.definitie = resultaat.definitie
            rij.geleerd_uit = geleerd_uit
            rij.geleerd_op = nu
            rij.versie = (rij.versie or 0) + 1
            rij.geldig = True
            rij.ongeldig_op = None
            rij.ongeldig_reden = None
            rij.administratie_id = administratie_id
            rij.vendor_id = vendor_id
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="extractie_template",
            record_id=rij.id,
            actie="extractie_template_geleerd",
            correlatie_id=document_id,
            oude_waarde=oud,
            nieuwe_waarde={
                "sleutel": rij.sleutel,
                "sleutel_soort": rij.sleutel_soort,
                "versie": rij.versie,
                "geleerd_uit": geleerd_uit,
                "velden": {veld: regel.get("soort") for veld, regel in resultaat.definitie["velden"].items()},
                "regels_modus": resultaat.definitie["regels_modus"],
                "btw_percentages": resultaat.definitie["btw_percentages"],
            },
            administratie_id=administratie_id,
        )
        logger.info(
            "Extractie-template geleerd: %s (versie %s, uit %s documenten)", rij.sleutel, rij.versie, len(geleerd_uit)
        )


def leer_na_boeking_stil(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, opslag: DocumentOpslag | None = None
) -> None:
    """Post-commit-hook-variant: nooit een exception richting de boekflow."""
    from app.documenten.storage import standaard_opslag

    try:
        leer_na_boeking(administratie_id=administratie_id, document_id=document_id, opslag=opslag or standaard_opslag())
    except Exception:  # noqa: BLE001 — leren is een optimalisatie, nooit een blokkade van de boeking
        logger.exception("Template-leren mislukt ná boeking van document %s", document_id)


# --- Zichtbaarheid (Instellingen) ------------------------------------------------------------------


@dataclass(frozen=True)
class MaandStatistiek:
    maand: str
    via_template: int
    via_ai: int
    templates_actief: int


def maand_statistiek(nu: datetime | None = None) -> MaandStatistiek:
    """Teller naast het AI-verbruiksblok: veldvoorstellen deze kalendermaand (Europe/Amsterdam) per
    extractiebron + het aantal geldige templates. Per administratie RLS-gescoped gelezen (systeem-actor)."""
    maand = huidige_maand(nu)
    start = datetime.combine(maand, time.min, tzinfo=TIJDZONE)
    via_template = via_ai = 0
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        administratie_ids = list(session.scalars(select(Administratie.id)))
        templates_actief = int(
            session.scalar(
                select(func.count()).select_from(ExtractieTemplate).where(ExtractieTemplate.geldig.is_(True))
            )
            or 0
        )
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            bronnen = session.scalars(
                select(DocumentGebeurtenis.detail["veldvoorstel"]["bron"].astext).where(
                    DocumentGebeurtenis.tijdstip >= start,
                    DocumentGebeurtenis.detail.has_key("veldvoorstel"),  # noqa: W601
                )
            ).all()
        via_template += sum(1 for b in bronnen if b == "template")
        via_ai += sum(1 for b in bronnen if b == "ai")
    return MaandStatistiek(
        maand=maand.strftime("%Y-%m"), via_template=via_template, via_ai=via_ai, templates_actief=templates_actief
    )
