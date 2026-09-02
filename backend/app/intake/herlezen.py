"""Nazorg intake-splitsingsbug (spoedopdracht 02-09, punt 5): verzamelbak-documenten die sinds
25-08 op de paginabereik-bug strandden (`splitsingsdetectie_mislukt: …`, tenaamstelling NULL
hoewel de AI 'm las) opnieuw door de GEFIXTE intake-keten halen — nieuwe intake-AI-lezing mét
pagina-aantal, proportionele validatie, nieuwe tenaamstelling-bepaling.

Poorten (ongewijzigd t.o.v. de gewone intake): alleen documenten die NOG in de verzamelbak
staan (administratie NULL + niet_toegewezen; al toegewezen/afgewezen/gesplitst = overgeslagen),
alleen PDF's zonder open splitsingsvoorstel, intake-AI-gate + API-key + AI-kostenmeter gelden
gewoon (limiet bereikt = run stopt zichtbaar). Idempotent: een document dat al eens herlezen is
draagt `intake_herlezen` in zijn tijdlijn en wordt overgeslagen (`--opnieuw` heft dat op).

Uitkomsten per document — nooit stil:
- één factuur + eenduidige tenaamstelling → toegewezen (⚙-overgang mét reden, audit) + de normale
  extractie ná toewijzing; het toewijzings-geheugen leert hier bewust NIET (geen mens-besluit);
- één factuur, niet eenduidig → tenaamstelling + suggestie op de rij gezet, blijft in de bak
  (tijdlijnregel met reden — de verzamelbak toont 'm);
- meerdere facturen → splitsingsvoorstel ter controle (zoals de gewone intake);
- AI-fout → tijdlijnregel `intake_herlezen_mislukt: …`, rij blijft ongewijzigd staan.

UBL-rijen (blok A3 02-09, parser-gap RLZ-export-UBL's — 97 IC-facturen Universal Nederland →
Universal Steigerbouw zonder tenaamstelling): een verzamelbak-UBL zónder tenaamstelling wordt
opnieuw deterministisch geparst (`documenten/ubl.py`, sinds 02-09 mét PartyName/Name-terugval) —
géén AI, dus óók zonder intake-AI-gate/API-key; de in de UBL ingesloten factuur-PDF wordt daarbij als
beeld in de bron-kolommen gezet (zelfde vorm als de bundeling bij de intake), zodat preview,
controlescherm en RLZ-bijlage de PDF tonen. Daarna dezelfde toewijzingsuitkomsten als hierboven.
`toewijzen=False` (CLI `--zonder-toewijzen`): een eenduidige match wordt NIET toegewezen maar als
suggestie op de rij gezet — voor een stapel die de mens bewust zelf in bulk wil toewijzen."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select

from app.aikosten.service import AiKostenLimietBereikt, AiVerbruikReferentie
from app.beheer import service as beheer_service
from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.pdf import tel_paginas
from app.documenten.service import (
    BronBestand,
    _schrijf_overgang,
    _sla_bronbestand_op,
    _standaard_opslag,
    start_extractie_na_toewijzing,
)
from app.documenten.storage import DocumentOpslag
from app.documenten.ubl import GeenGeldigeUbl, is_vastly_verkoop, lees_ingesloten_pdf, parseer_ubl_factuur
from app.extractie import splitsing as splitsing_extractie
from app.intake.models import IntakeBericht, IntakeSplitsing, IntakeSplitsingStatus
from app.intake.redenen import is_verworpen_intake_reden
from app.intake.toewijzing import bepaal_toewijzing

logger = logging.getLogger(__name__)

HERLEZEN_SLEUTEL = "intake_herlezen"


class IntakeGateDicht(Exception):
    """Intake-AI staat uit of er is geen API-key — herlezen kan dan niets doen (zichtbaar stoppen)."""


@dataclass(frozen=True)
class HerleesKandidaat:
    document_id: uuid.UUID
    bestandsnaam: str
    reden: str | None
    al_herlezen: bool

    @property
    def is_ubl(self) -> bool:
        return self.bestandsnaam.lower().endswith(".xml")


@dataclass
class HerleesTelling:
    kandidaten: int = 0
    herlezen: int = 0
    toegewezen: int = 0
    tenaamstelling_gezet: int = 0
    splitsingsvoorstel: int = 0
    mislukt: int = 0
    overgeslagen_al_herlezen: int = 0
    #: UBL-rijen waarvan de ingesloten factuur-PDF als beeld in de bron-kolommen is gezet (A3 02-09).
    beeld_gezet: int = 0
    gestopt_reden: str | None = None
    details: list[str] = field(default_factory=list)

    def als_dict(self) -> dict:
        return {
            "kandidaten": self.kandidaten,
            "herlezen": self.herlezen,
            "toegewezen": self.toegewezen,
            "tenaamstelling_gezet": self.tenaamstelling_gezet,
            "splitsingsvoorstel": self.splitsingsvoorstel,
            "mislukt": self.mislukt,
            "overgeslagen_al_herlezen": self.overgeslagen_al_herlezen,
            "beeld_gezet": self.beeld_gezet,
            "gestopt_reden": self.gestopt_reden,
        }


def _jongste_reden_en_herlezen(session, document_id: uuid.UUID) -> tuple[str | None, bool]:
    rijen = session.scalars(
        select(DocumentGebeurtenis.detail)
        .where(
            DocumentGebeurtenis.document_id == document_id,
            DocumentGebeurtenis.naar_status == DocumentStatus.NIET_TOEGEWEZEN,
        )
        .order_by(DocumentGebeurtenis.tijdstip.desc())
    ).all()
    al_herlezen = any(isinstance(d, dict) and d.get(HERLEZEN_SLEUTEL) for d in rijen)
    jongste = rijen[0] if rijen else None
    reden = jongste.get("reden") if isinstance(jongste, dict) else None
    return (reden if isinstance(reden, str) else None), al_herlezen


def vind_kandidaten(*, sinds: datetime, alle_redenen: bool = False) -> list[HerleesKandidaat]:
    """Verzamelbak-PDF's zonder open splitsingsvoorstel, aangemaakt sinds `sinds`, waarvan de
    jongste intake-reden een verworpen/mislukt AI-voorstel is (default) — `alle_redenen=True`
    neemt óók 'tenaamstelling_niet_eenduidig'-rijen zonder tenaamstelling mee — én álle
    verzamelbak-UBL's zonder tenaamstelling (parser-gap 02-09; deterministisch, geen AI)."""
    kandidaten: list[HerleesKandidaat] = []
    with scoped_session(None) as session:
        documenten = session.scalars(
            select(Document)
            .where(
                Document.administratie_id.is_(None),
                Document.status == DocumentStatus.NIET_TOEGEWEZEN,
                Document.aangemaakt_op >= sinds,
            )
            .order_by(Document.aangemaakt_op.asc())
        ).all()
        open_splitsingen = set(
            session.scalars(
                select(IntakeSplitsing.bron_document_id).where(
                    IntakeSplitsing.bron_document_id.in_([d.id for d in documenten]),
                    IntakeSplitsing.status == IntakeSplitsingStatus.VOORGESTELD.value,
                )
            )
        )
        for document in documenten:
            naam = document.bestandsnaam.lower()
            if naam.endswith(".xml"):
                # UBL zonder gelezen tenaamstelling (parser-gap 02-09) — of al eens herlezen.
                reden, al_herlezen = _jongste_reden_en_herlezen(session, document.id)
                if document.tenaamstelling is None or al_herlezen:
                    kandidaten.append(
                        HerleesKandidaat(
                            document_id=document.id,
                            bestandsnaam=document.bestandsnaam,
                            reden=reden,
                            al_herlezen=al_herlezen,
                        )
                    )
                continue
            if not naam.endswith(".pdf") or document.id in open_splitsingen:
                continue
            reden, al_herlezen = _jongste_reden_en_herlezen(session, document.id)
            # Al eens herlezen = kandidaat (zichtbaar als "overgeslagen", `--opnieuw` herleest) — óók
            # als de herlezing zelf een geldige uitkomst gaf; een mislukte herlezing wordt dus nooit
            # stil eindeloos herhaald.
            past = (
                is_verworpen_intake_reden(reden)
                or al_herlezen
                or (alle_redenen and document.tenaamstelling is None and (reden or "").startswith("tenaamstelling"))
            )
            if not past:
                continue
            kandidaten.append(
                HerleesKandidaat(
                    document_id=document.id, bestandsnaam=document.bestandsnaam, reden=reden, al_herlezen=al_herlezen
                )
            )
    return kandidaten


def _tijdlijn_notitie(session, document: Document, detail: dict) -> None:
    """Tijdlijnregel zonder statuswijziging (niet_toegewezen → niet_toegewezen): document.status
    wordt níét gemuteerd, dus bewust niet via `_schrijf_overgang` (dat is de enige status-muteerder
    en de statusmachine kent geen zelf-overgang). Systeem-actor mét verplichte `reden`."""
    assert isinstance(detail.get("reden"), str) and detail["reden"].strip()
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=SYSTEEM_ACTOR_ID,
            detail={**detail, HERLEZEN_SLEUTEL: True},
        )
    )


def _herlees_een(
    kandidaat: HerleesKandidaat, *, opslag: DocumentOpslag, telling: HerleesTelling, toewijzen: bool = True
) -> None:
    with scoped_session(None) as session:
        document = session.get(Document, kandidaat.document_id)
        if (
            document is None
            or document.administratie_id is not None
            or document.status != DocumentStatus.NIET_TOEGEWEZEN
        ):
            telling.details.append(f"{kandidaat.bestandsnaam}: intussen verwerkt — overgeslagen")
            return
        opslag_pad = document.opslag_pad
        afzender = document.afzender_hint
        intake_bericht_id = document.intake_bericht_id
        body_hint = session.get(IntakeBericht, intake_bericht_id).body_tekst if intake_bericht_id is not None else None

    inhoud = opslag.lezen(pad=opslag_pad)
    paginas = tel_paginas(inhoud) or 1
    try:
        segmenten = splitsing_extractie.detecteer_facturen(
            inhoud,
            paginas=paginas,
            verbruik_referentie=AiVerbruikReferentie(bron="intake_herlezen", intake_bericht_id=intake_bericht_id),
            mail_context=body_hint,
        )
    except AiKostenLimietBereikt:
        raise
    except Exception as exc:  # noqa: BLE001 — élke AI-fout zichtbaar op de tijdlijn, nooit een gok
        logger.warning("Intake-herlezen mislukt voor %s: %s", kandidaat.bestandsnaam, exc)
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, kandidaat.document_id)
            assert document is not None
            _tijdlijn_notitie(session, document, {"reden": f"intake_herlezen_mislukt: {exc}"})
        telling.herlezen += 1
        telling.mislukt += 1
        telling.details.append(f"{kandidaat.bestandsnaam}: mislukt — {exc}")
        return

    telling.herlezen += 1
    if len(segmenten) >= 2:
        ongeldig = [s for s in segmenten if not s.geldig]
        reden = f"intake_herlezen: splitsingsvoorstel ter controle ({len(segmenten)} facturen herkend"
        reden += f", {len(ongeldig)} deel/delen ongeldig)" if ongeldig else ")"
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, kandidaat.document_id)
            assert document is not None
            session.add(
                IntakeSplitsing(
                    bron_document_id=document.id,
                    voorstel={
                        "paginas": paginas,
                        "facturen": [s.als_dict() for s in segmenten],
                        "ongeldig": len(ongeldig),
                    },
                )
            )
            _tijdlijn_notitie(session, document, {"reden": reden})
        telling.splitsingsvoorstel += 1
        telling.details.append(f"{kandidaat.bestandsnaam}: {reden}")
        return

    _rond_toewijzing_af(
        kandidaat,
        tenaamstelling=segmenten[0].tenaamstelling,
        afzender=afzender,
        body_hint=body_hint,
        telling=telling,
        toewijzen=toewijzen,
    )


def _herlees_ubl(
    kandidaat: HerleesKandidaat, *, opslag: DocumentOpslag, telling: HerleesTelling, toewijzen: bool
) -> None:
    """UBL-rij (A3 02-09): deterministisch herparsen, ingesloten PDF als beeld persisteren, dan
    dezelfde toewijzingsafronding als een PDF. Geen AI, geen gate."""
    with scoped_session(None) as session:
        document = session.get(Document, kandidaat.document_id)
        if (
            document is None
            or document.administratie_id is not None
            or document.status != DocumentStatus.NIET_TOEGEWEZEN
        ):
            telling.details.append(f"{kandidaat.bestandsnaam}: intussen verwerkt — overgeslagen")
            return
        opslag_pad = document.opslag_pad
        heeft_bron = document.bron_opslag_pad is not None
        afzender = document.afzender_hint
        intake_bericht_id = document.intake_bericht_id
        body_hint = session.get(IntakeBericht, intake_bericht_id).body_tekst if intake_bericht_id is not None else None

    inhoud = opslag.lezen(pad=opslag_pad)
    try:
        voorstel = parseer_ubl_factuur(inhoud)
    except GeenGeldigeUbl as exc:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, kandidaat.document_id)
            assert document is not None
            _tijdlijn_notitie(session, document, {"reden": f"intake_herlezen_mislukt: ubl_invalide: {exc}"})
        telling.herlezen += 1
        telling.mislukt += 1
        telling.details.append(f"{kandidaat.bestandsnaam}: mislukt — geen geldige UBL: {exc}")
        return
    telling.herlezen += 1

    if not heeft_bron:
        ingesloten = lees_ingesloten_pdf(inhoud)
        if ingesloten is not None:
            # Zelfde vorm als de intake-bundeling (bron_* = het beeld): preview, controlescherm en de
            # RLZ-bijlage tonen vanaf nu de factuur-PDF; de UBL blijft het hoofdbestand (vorm=data).
            bron = BronBestand(
                bestandsnaam=ingesloten.bestandsnaam, inhoud=ingesloten.inhoud, content_type="application/pdf"
            )
            bron_pad = _sla_bronbestand_op(opslag, opslag_pad=opslag_pad, bron=bron)
            with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
                document = session.get(Document, kandidaat.document_id)
                assert document is not None
                document.bron_opslag_pad = bron_pad
                document.bron_bestandsnaam = bron.bestandsnaam
                document.bron_content_type = bron.content_type
                _tijdlijn_notitie(
                    session,
                    document,
                    {"reden": f"intake_herlezen: ingesloten factuur-PDF '{bron.bestandsnaam}' als beeld gezet"},
                )
            telling.beeld_gezet += 1

    # Vastly-verkoop-UBL's wijzen op de LEVERANCIER toe (onze entiteit); die route heeft een eigen
    # intake-pad en komt hier in de praktijk niet — nooit stil de verkeerde partij als tenaamstelling.
    tenaamstelling = voorstel.leverancier_naam if is_vastly_verkoop(voorstel) else voorstel.klant_naam
    _rond_toewijzing_af(
        kandidaat,
        tenaamstelling=tenaamstelling,
        afzender=afzender,
        body_hint=body_hint,
        telling=telling,
        toewijzen=toewijzen,
    )


def _rond_toewijzing_af(
    kandidaat: HerleesKandidaat,
    *,
    tenaamstelling: str | None,
    afzender: str | None,
    body_hint: str | None,
    telling: HerleesTelling,
    toewijzen: bool,
) -> None:
    """Gedeelde staart van een herlezing (PDF én UBL): toewijzen bij een eenduidige match — of, met
    `toewijzen=False`, die match als SUGGESTIE op de rij zetten — anders tenaamstelling + suggestie."""
    with scoped_session(None) as session:
        besluit = bepaal_toewijzing(session, tenaamstelling=tenaamstelling, afzender=afzender, body_hint=body_hint)

    if besluit.administratie_id is not None and not toewijzen:
        # Bewust niet toewijzen (CLI --zonder-toewijzen): de eenduidige match wordt de suggestie zodat
        # de bulk-toewijzing in de verzamelbak vooringevuld staat; de mens drukt op de knop.
        reden = (
            f"intake_herlezen: eenduidig op {besluit.bron} (tenaamstelling {tenaamstelling!r}) — "
            "als suggestie gezet, niet toegewezen"
        )
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, kandidaat.document_id)
            assert document is not None
            document.tenaamstelling = tenaamstelling
            document.toewijzing_suggestie_administratie_id = besluit.administratie_id
            document.toewijzing_suggestie_bron = besluit.bron
            _tijdlijn_notitie(
                session,
                document,
                {
                    "reden": reden,
                    "tenaamstelling": tenaamstelling,
                    "suggestie_administratie_id": str(besluit.administratie_id),
                },
            )
        telling.tenaamstelling_gezet += 1
        telling.details.append(f"{kandidaat.bestandsnaam}: {reden}")
        return

    if besluit.administratie_id is not None:
        reden = f"intake_herlezen: toegewezen op {besluit.bron} (tenaamstelling {tenaamstelling!r})"
        with scoped_session(besluit.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, kandidaat.document_id)
            assert document is not None
            document.tenaamstelling = tenaamstelling
            document.toewijzing_suggestie_administratie_id = None
            document.toewijzing_suggestie_bron = None
            document.administratie_id = besluit.administratie_id
            _schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.ONTVANGEN,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={
                    "reden": reden,
                    "toegewezen_aan_administratie": str(besluit.administratie_id),
                    "vanuit": "verzamelbak",
                    HERLEZEN_SLEUTEL: True,
                },
            )
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="document",
                record_id=document.id,
                actie="intake_herlezen_toegewezen",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"administratie_id": None, "tenaamstelling": None},
                nieuwe_waarde={"administratie_id": str(besluit.administratie_id), "tenaamstelling": tenaamstelling},
                administratie_id=besluit.administratie_id,
            )
        start_extractie_na_toewijzing(
            administratie_id=besluit.administratie_id, document_id=kandidaat.document_id, actor_id=SYSTEEM_ACTOR_ID
        )
        telling.toegewezen += 1
        telling.details.append(f"{kandidaat.bestandsnaam}: {reden}")
        return

    reden = (
        f"intake_herlezen: tenaamstelling {tenaamstelling!r} gelezen, niet eenduidig"
        if tenaamstelling
        else "intake_herlezen: geen tenaamstelling gelezen"
    )
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, kandidaat.document_id)
        assert document is not None
        document.tenaamstelling = tenaamstelling
        document.toewijzing_suggestie_administratie_id = besluit.suggestie_administratie_id
        document.toewijzing_suggestie_bron = besluit.suggestie_bron
        _tijdlijn_notitie(
            session,
            document,
            {
                "reden": reden,
                "tenaamstelling": tenaamstelling,
                "suggestie_administratie_id": (
                    str(besluit.suggestie_administratie_id) if besluit.suggestie_administratie_id else None
                ),
            },
        )
    if tenaamstelling:
        telling.tenaamstelling_gezet += 1
    telling.details.append(f"{kandidaat.bestandsnaam}: {reden}")


def herlees_verzamelbak(
    *,
    sinds: datetime,
    dry_run: bool = False,
    opnieuw: bool = False,
    alle_redenen: bool = False,
    opslag: DocumentOpslag | None = None,
    toewijzen: bool = True,
    alleen_ubl: bool = False,
) -> HerleesTelling:
    """Zie module-docstring. `dry_run` telt alleen; `opnieuw` herleest óók al-herlezen rijen;
    `toewijzen=False` zet een eenduidige match als suggestie i.p.v. toe te wijzen; `alleen_ubl`
    beperkt de run tot UBL-rijen (deterministisch, geen AI-call en geen AI-kosten — de nazorg van
    de RLZ-export-stapel zonder de PDF-kandidaten mee te nemen)."""
    telling = HerleesTelling()
    kandidaten = vind_kandidaten(sinds=sinds, alle_redenen=alle_redenen)
    if alleen_ubl:
        kandidaten = [k for k in kandidaten if k.is_ubl]
    telling.kandidaten = len(kandidaten)
    te_doen: list[HerleesKandidaat] = []
    for kandidaat in kandidaten:
        if kandidaat.al_herlezen and not opnieuw:
            telling.overgeslagen_al_herlezen += 1
            continue
        te_doen.append(kandidaat)
    if dry_run:
        telling.details = [f"{k.bestandsnaam}: {k.reden}" for k in te_doen]
        return telling
    if not te_doen:
        return telling
    # De AI-gate geldt alleen voor PDF's; UBL-herlezing is lokale code (geen data naar buiten).
    if any(not k.is_ubl for k in te_doen) and (
        not beheer_service.intake_ai_effectief_ingeschakeld() or not settings.anthropic_api_key
    ):
        raise IntakeGateDicht("Intake-AI staat uit of er is geen API-key — herlezen kan niets doen.")

    opslag = opslag or _standaard_opslag()
    for kandidaat in te_doen:
        try:
            if kandidaat.is_ubl:
                _herlees_ubl(kandidaat, opslag=opslag, telling=telling, toewijzen=toewijzen)
            else:
                _herlees_een(kandidaat, opslag=opslag, telling=telling, toewijzen=toewijzen)
        except AiKostenLimietBereikt as exc:
            telling.gestopt_reden = f"AI-maandlimiet bereikt — gestopt bij {kandidaat.bestandsnaam}: {exc}"
            logger.warning(telling.gestopt_reden)
            break
    return telling
