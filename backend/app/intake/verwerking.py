"""Intake-verwerking: één binnengekomen mail → routing per bijlage (koppelcontract §2d +
CLAUDE.md e-mail-intake/verzamelbak).

Routingregels per bijlage, in deze volgorde — en élk niet-eenduidig geval eindigt zichtbaar
in de verzamelbak, nooit stil ergens anders:

XML (UBL):
1. On-parsebaar/geen UBL → verzamelbak (reden ubl_invalide) — §2d-failsafe.
2. VGB-prefix (Reference/betalingskenmerk/factuurnummer) → al door vastgoed geboekt: GEEN
   werkvoorraad-document (koppelcontract §2 punt 2), wél zichtbaar geregistreerd in het
   intake-bericht + audit_event.
3. VASTLY-VERKOOP-markering (§2d): NLCIUS-kernvelden compleet → soort 'verkoopfactuur',
   toewijzing op de LEVERANCIER-naam (dat is bij een verkoopfactuur ónze entiteit); kernvelden
   incompleet → verzamelbak (nooit stil naar inkoop).
4. Normale inkoop-UBL: toewijzing op de tenaamstelling (AccountingCustomerParty, leidend).

PDF:
5. Intake-AI-gate aan → tenaamstelling + factuurgrensdetectie (app/extractie/splitsing.py):
   één factuur → toewijzing; meerdere → bron-document in de verzamelbak MET een
   splitsingsvoorstel dat ALTIJD eerst ter controle gaat (app/intake/splitsing.py).
6. Gate uit of AI-fout → verzamelbak (mens beoordeelt; na toewijzing draait de normale
   extractie onder de AVG-gate van de gekozen administratie).

Overige bijlage-typen worden zichtbaar als 'niet_verwerkbaar' in het intake-bericht
geregistreerd (mail-handtekeningen/logo's horen niet als document in de verzamelbak).

Toewijzing zelf: app/intake/toewijzing.py — tenaamstelling leidend, afzender hint, nooit
auto-toewijzen bij twijfel."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select

from app.aikosten.service import AiKostenLimietBereikt, AiVerbruikReferentie
from app.beheer import service as beheer_service
from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import DocumentBron, DocumentSoort
from app.documenten.pdf import tel_paginas
from app.documenten.storage import DocumentOpslag
from app.documenten.ubl import (
    GeenGeldigeUbl,
    is_vastly_verkoop,
    is_vgb_document,
    nlcius_kernvelden_ontbrekend,
    parseer_ubl_factuur,
)
from app.extractie import splitsing as splitsing_extractie
from app.intake.eml import GeenGeldigeEml, IntakeBijlage, IntakeMail, parse_eml
from app.intake.models import IntakeBericht, IntakeSplitsing
from app.intake.toewijzing import bepaal_toewijzing

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BijlageResultaat:
    bestandsnaam: str
    uitkomst: str
    document_id: uuid.UUID | None = None
    detail: str | None = None

    def als_dict(self) -> dict:
        return {
            "bestandsnaam": self.bestandsnaam,
            "uitkomst": self.uitkomst,
            "document_id": str(self.document_id) if self.document_id else None,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class IntakeResultaat:
    bericht_id: uuid.UUID | None
    al_eerder_verwerkt: bool
    bijlagen: list[BijlageResultaat] = field(default_factory=list)


class GeenGeldigIntakeBericht(Exception):
    pass


def _wijs_toe_of_verzamelbak(
    *,
    bijlage_naam: str,
    inhoud: bytes,
    soort: DocumentSoort,
    tenaamstelling: str | None,
    afzender: str | None,
    actor_id: uuid.UUID,
    intake_bericht_id: uuid.UUID,
    opslag: DocumentOpslag | None,
    verzamelbak_reden: str,
    gesplitst_uit_id: uuid.UUID | None = None,
) -> BijlageResultaat:
    with scoped_session(None) as session:
        besluit = bepaal_toewijzing(session, tenaamstelling=tenaamstelling, afzender=afzender)

    if besluit.administratie_id is not None:
        resultaat = documenten_service.upload_document(
            administratie_id=besluit.administratie_id,
            bestandsnaam=bijlage_naam,
            inhoud=inhoud,
            actor_id=actor_id,
            opslag=opslag,
            bron=DocumentBron.EMAIL,
            soort=soort,
            intake_bericht_id=intake_bericht_id,
            afzender_hint=afzender,
            tenaamstelling=tenaamstelling,
            gesplitst_uit_id=gesplitst_uit_id,
        )
        return BijlageResultaat(
            bestandsnaam=bijlage_naam,
            uitkomst="toegewezen",
            document_id=resultaat.document_id,
            detail=f"{besluit.bron} → {besluit.administratie_id}",
        )

    document_id = documenten_service.registreer_niet_toegewezen_document(
        bestandsnaam=bijlage_naam,
        inhoud=inhoud,
        actor_id=actor_id,
        reden=verzamelbak_reden,
        soort=soort,
        opslag=opslag,
        intake_bericht_id=intake_bericht_id,
        afzender_hint=afzender,
        tenaamstelling=tenaamstelling,
        gesplitst_uit_id=gesplitst_uit_id,
        suggestie_administratie_id=besluit.suggestie_administratie_id,
        suggestie_bron=besluit.suggestie_bron,
    )
    return BijlageResultaat(
        bestandsnaam=bijlage_naam, uitkomst="verzamelbak", document_id=document_id, detail=verzamelbak_reden
    )


def _verwerk_waarborg(
    bijlage: IntakeBijlage,
    *,
    afzender: str | None,
    actor_id: uuid.UUID,
    intake_bericht_id: uuid.UUID,
    opslag: DocumentOpslag | None,
) -> BijlageResultaat:
    """VASTLY-WAARBORG-bericht (§2d-waarborgroute DEFINITIEF v1.11, blok E 2026-08-10): geen
    factuurstuk maar een klein deterministisch XML-bericht — herkenning op het root-element,
    toewijzing op de verhuurder-tenaamstelling (adminId = hint), idempotent op `bericht_id`.
    Failsafe: onherkenbaar/incompleet of niet-toewijsbaar → verzamelbak, nooit stil."""
    from app.documenten.waarborg_xml import (
        OngeldigWaarborgBericht,
        parseer_waarborg_bericht,
        waarborg_velden_ontbrekend,
    )
    from app.intake.toewijzing import bepaal_toewijzing
    from app.waarborg.models import WaarborgBericht

    def _verzamelbak(reden: str) -> BijlageResultaat:
        document_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam=bijlage.bestandsnaam,
            inhoud=bijlage.inhoud,
            actor_id=actor_id,
            reden=reden,
            soort=DocumentSoort.WAARBORG,
            opslag=opslag,
            intake_bericht_id=intake_bericht_id,
            afzender_hint=afzender,
        )
        return BijlageResultaat(
            bestandsnaam=bijlage.bestandsnaam, uitkomst="verzamelbak", document_id=document_id, detail=reden
        )

    try:
        bericht = parseer_waarborg_bericht(bijlage.inhoud)
    except OngeldigWaarborgBericht as exc:
        return _verzamelbak(f"waarborg_invalide: {exc}")
    ontbrekend = waarborg_velden_ontbrekend(bericht)
    if ontbrekend:
        return _verzamelbak(f"waarborg_invalide: ontbrekend {', '.join(ontbrekend)}")

    with scoped_session(None) as session:
        besluit = bepaal_toewijzing(session, tenaamstelling=bericht.verhuurder_entiteit, afzender=afzender)
    if besluit.administratie_id is None:
        return _verzamelbak(
            f"waarborg_niet_toewijsbaar: verhuurder-entiteit '{bericht.verhuurder_entiteit}' "
            "is geen eenduidige administratie"
        )
    administratie_id = besluit.administratie_id

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        bestaand = session.scalar(select(WaarborgBericht).where(WaarborgBericht.bericht_id == bericht.bericht_id))
        if bestaand is not None:
            # Idempotentiesleutel (v1.11): zelfde bericht_id = zelfde bericht — nooit een
            # tweede document of boeking; zichtbaar in het intake-resultaat + audit.
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="waarborg_bericht",
                record_id=bestaand.document_id,
                actie="waarborg_duplicaat_genegeerd",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={"bericht_id": str(bericht.bericht_id), "bestandsnaam": bijlage.bestandsnaam},
                administratie_id=administratie_id,
            )
            return BijlageResultaat(
                bestandsnaam=bijlage.bestandsnaam,
                uitkomst="waarborg_duplicaat",
                document_id=bestaand.document_id,
                detail=f"bericht_id {bericht.bericht_id} al verwerkt (idempotent, v1.11)",
            )
        # Plausibiliteits-signaal (v1.11): identieke kernvelden onder een ánder bericht_id =
        # waarschuwing, geen stille dedup — het nieuwe bericht wordt gewoon verwerkt.
        zelfde_kern = session.scalar(
            select(WaarborgBericht).where(
                WaarborgBericht.administratie_id == administratie_id,
                WaarborgBericht.contract_referentie == bericht.contract_referentie,
                WaarborgBericht.richting == bericht.richting,
                WaarborgBericht.datum == bericht.datum,
                WaarborgBericht.bedrag == bericht.bedrag,
            )
        )
        if zelfde_kern is not None:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="waarborg_bericht",
                record_id=zelfde_kern.document_id,
                actie="waarborg_zelfde_kernvelden_signaal",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "nieuw_bericht_id": str(bericht.bericht_id),
                    "bestaand_bericht_id": str(zelfde_kern.bericht_id),
                    "contract_referentie": bericht.contract_referentie,
                },
                administratie_id=administratie_id,
            )

    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=bijlage.bestandsnaam,
        inhoud=bijlage.inhoud,
        actor_id=actor_id,
        opslag=opslag,
        bron=DocumentBron.EMAIL,
        soort=DocumentSoort.WAARBORG,
        intake_bericht_id=intake_bericht_id,
        afzender_hint=afzender,
        tenaamstelling=bericht.verhuurder_entiteit,
    )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        session.add(
            WaarborgBericht(
                document_id=resultaat.document_id,
                administratie_id=administratie_id,
                bericht_id=bericht.bericht_id,
                schema_versie=bericht.schema_versie,
                verhuurder_entiteit=bericht.verhuurder_entiteit,
                rlz_admin_id_hint=bericht.rlz_admin_id_hint,
                contract_referentie=bericht.contract_referentie,
                huurder=bericht.huurder,
                bedrag=bericht.bedrag,
                richting=bericht.richting,
                datum=bericht.datum,
                balans_gb_code=bericht.balans_gb_code,
            )
        )
    return BijlageResultaat(
        bestandsnaam=bijlage.bestandsnaam,
        uitkomst="toegewezen",
        document_id=resultaat.document_id,
        detail=f"{besluit.bron} → {administratie_id} (waarborg)",
    )


def _verwerk_xml(
    bijlage: IntakeBijlage,
    *,
    afzender: str | None,
    actor_id: uuid.UUID,
    intake_bericht_id: uuid.UUID,
    opslag: DocumentOpslag | None,
) -> BijlageResultaat:
    from app.documenten.waarborg_xml import is_waarborg_xml

    if is_waarborg_xml(bijlage.inhoud):
        # §2d-waarborgroute (v1.11): eigen root-element, geen UBL — vóór de UBL-parse.
        return _verwerk_waarborg(
            bijlage,
            afzender=afzender,
            actor_id=actor_id,
            intake_bericht_id=intake_bericht_id,
            opslag=opslag,
        )
    try:
        voorstel = parseer_ubl_factuur(bijlage.inhoud)
    except GeenGeldigeUbl as exc:
        # §2d-failsafe: on-parsebare/ongeldige UBL → verzamelbak, nooit stil naar inkoop.
        document_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam=bijlage.bestandsnaam,
            inhoud=bijlage.inhoud,
            actor_id=actor_id,
            reden=f"ubl_invalide: {exc}",
            opslag=opslag,
            intake_bericht_id=intake_bericht_id,
            afzender_hint=afzender,
        )
        return BijlageResultaat(
            bestandsnaam=bijlage.bestandsnaam,
            uitkomst="verzamelbak",
            document_id=document_id,
            detail=f"ubl_invalide: {exc}",
        )

    if is_vgb_document(voorstel):
        # Koppelcontract §2 punt 2: al door vastgoed geboekt — nooit als werkvoorraad, wél
        # zichtbaar geregistreerd (intake-bericht + audit).
        with scoped_session(None, actor_id=actor_id) as session:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="intake_bericht",
                record_id=intake_bericht_id,
                actie="intake_vgb_genegeerd",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={"bestandsnaam": bijlage.bestandsnaam, "factuurnummer": voorstel.factuurnummer},
                administratie_id=None,
            )
        return BijlageResultaat(
            bestandsnaam=bijlage.bestandsnaam,
            uitkomst="vgb_genegeerd",
            detail="VGB-prefix: al door de vastgoedmodule geboekt (koppelcontract §2 punt 2)",
        )

    if is_vastly_verkoop(voorstel):
        if voorstel.is_creditnota and not settings.creditnota_381_ingeschakeld:
            # §2d-creditnota's (v1.11): de herkenning zit achter een eigen config-gate
            # (default UIT — volgorde-afspraak met vastgoeds CREDITNOTA_381_ACTIEF). Zolang de
            # gate dicht is valt een binnenkomende 381 zichtbaar in de verzamelbak, nooit stil.
            document_id = documenten_service.registreer_niet_toegewezen_document(
                bestandsnaam=bijlage.bestandsnaam,
                inhoud=bijlage.inhoud,
                actor_id=actor_id,
                reden="creditnote_381_gate_uit: CreditNote-herkenning nog niet geactiveerd "
                "(config creditnota_381_ingeschakeld)",
                soort=DocumentSoort.VERKOOPFACTUUR,
                opslag=opslag,
                intake_bericht_id=intake_bericht_id,
                afzender_hint=afzender,
                tenaamstelling=voorstel.leverancier_naam,
            )
            return BijlageResultaat(
                bestandsnaam=bijlage.bestandsnaam,
                uitkomst="verzamelbak",
                document_id=document_id,
                detail="creditnote_381_gate_uit",
            )
        ontbrekend = nlcius_kernvelden_ontbrekend(voorstel)
        if ontbrekend:
            document_id = documenten_service.registreer_niet_toegewezen_document(
                bestandsnaam=bijlage.bestandsnaam,
                inhoud=bijlage.inhoud,
                actor_id=actor_id,
                reden=f"vastly_nlcius_invalide: ontbrekend {', '.join(ontbrekend)}",
                soort=DocumentSoort.VERKOOPFACTUUR,
                opslag=opslag,
                intake_bericht_id=intake_bericht_id,
                afzender_hint=afzender,
                tenaamstelling=voorstel.leverancier_naam,
            )
            return BijlageResultaat(
                bestandsnaam=bijlage.bestandsnaam,
                uitkomst="verzamelbak",
                document_id=document_id,
                detail=f"vastly_nlcius_invalide: {', '.join(ontbrekend)}",
            )
        # Verkoopfactuur: ónze entiteit is de LEVERANCIER op de factuur — dáárop toewijzen.
        return _wijs_toe_of_verzamelbak(
            bijlage_naam=bijlage.bestandsnaam,
            inhoud=bijlage.inhoud,
            soort=DocumentSoort.VERKOOPFACTUUR,
            tenaamstelling=voorstel.leverancier_naam,
            afzender=afzender,
            actor_id=actor_id,
            intake_bericht_id=intake_bericht_id,
            opslag=opslag,
            verzamelbak_reden="vastly_verkoop_zonder_eenduidige_entiteit",
        )

    # Normale inkoop-UBL: tenaamstelling = de afnemer (AccountingCustomerParty), leidend.
    return _wijs_toe_of_verzamelbak(
        bijlage_naam=bijlage.bestandsnaam,
        inhoud=bijlage.inhoud,
        soort=DocumentSoort.INKOOPFACTUUR,
        tenaamstelling=voorstel.klant_naam,
        afzender=afzender,
        actor_id=actor_id,
        intake_bericht_id=intake_bericht_id,
        opslag=opslag,
        verzamelbak_reden="tenaamstelling_niet_eenduidig",
    )


def _verwerk_pdf(
    bijlage: IntakeBijlage,
    *,
    afzender: str | None,
    actor_id: uuid.UUID,
    intake_bericht_id: uuid.UUID,
    opslag: DocumentOpslag | None,
) -> BijlageResultaat:
    if not beheer_service.intake_ai_effectief_ingeschakeld() or not settings.anthropic_api_key:
        # AVG-gate intake (platform-breed, default UIT): zonder opt-in geen intake-byte naar de
        # Claude API — het document valt zichtbaar in de verzamelbak, een mens wijst toe.
        # Sinds migratie 0029 is dit een Beheerder-instelling (platform.intake_instelling);
        # de env-setting is alleen nog fallback zolang die rij ontbreekt.
        document_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam=bijlage.bestandsnaam,
            inhoud=bijlage.inhoud,
            actor_id=actor_id,
            reden="intake_ai_uitgeschakeld",
            opslag=opslag,
            intake_bericht_id=intake_bericht_id,
            afzender_hint=afzender,
        )
        return BijlageResultaat(
            bestandsnaam=bijlage.bestandsnaam,
            uitkomst="verzamelbak",
            document_id=document_id,
            detail="intake_ai_uitgeschakeld",
        )

    paginas = tel_paginas(bijlage.inhoud)
    try:
        segmenten = splitsing_extractie.detecteer_facturen(
            bijlage.inhoud,
            paginas=paginas or 1,
            verbruik_referentie=AiVerbruikReferentie(bron="intake_splitsing", intake_bericht_id=intake_bericht_id),
        )
    except AiKostenLimietBereikt:
        # AI-kostengrens (besluit 2026-08-14): zelfde zichtbare pad als intake_ai_uitgeschakeld —
        # het document valt in de verzamelbak met eigen reden, een mens wijst toe.
        logger.warning("AI-maandlimiet bereikt — splitsingsdetectie overgeslagen voor %s", bijlage.bestandsnaam)
        document_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam=bijlage.bestandsnaam,
            inhoud=bijlage.inhoud,
            actor_id=actor_id,
            reden="ai_limiet_bereikt",
            opslag=opslag,
            intake_bericht_id=intake_bericht_id,
            afzender_hint=afzender,
        )
        return BijlageResultaat(
            bestandsnaam=bijlage.bestandsnaam,
            uitkomst="verzamelbak",
            document_id=document_id,
            detail="ai_limiet_bereikt",
        )
    except Exception as exc:  # noqa: BLE001 — élke AI-fout → verzamelbak, nooit een gok of crash
        logger.warning("Intake-splitsingsdetectie mislukt voor %s: %s", bijlage.bestandsnaam, exc)
        document_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam=bijlage.bestandsnaam,
            inhoud=bijlage.inhoud,
            actor_id=actor_id,
            reden=f"splitsingsdetectie_mislukt: {exc}",
            opslag=opslag,
            intake_bericht_id=intake_bericht_id,
            afzender_hint=afzender,
        )
        return BijlageResultaat(
            bestandsnaam=bijlage.bestandsnaam,
            uitkomst="verzamelbak",
            document_id=document_id,
            detail=f"splitsingsdetectie_mislukt: {exc}",
        )

    if len(segmenten) == 1:
        return _wijs_toe_of_verzamelbak(
            bijlage_naam=bijlage.bestandsnaam,
            inhoud=bijlage.inhoud,
            soort=DocumentSoort.INKOOPFACTUUR,
            tenaamstelling=segmenten[0].tenaamstelling,
            afzender=afzender,
            actor_id=actor_id,
            intake_bericht_id=intake_bericht_id,
            opslag=opslag,
            verzamelbak_reden="tenaamstelling_niet_eenduidig",
        )

    # Meerdere facturen: bron-document naar de verzamelbak MET splitsingsvoorstel — de
    # voorgestelde splitsing gaat ALTIJD eerst ter controle (mockup), nooit stil auto-splitsen.
    document_id = documenten_service.registreer_niet_toegewezen_document(
        bestandsnaam=bijlage.bestandsnaam,
        inhoud=bijlage.inhoud,
        actor_id=actor_id,
        reden=f"splitsingsvoorstel_ter_controle: {len(segmenten)} facturen herkend",
        opslag=opslag,
        intake_bericht_id=intake_bericht_id,
        afzender_hint=afzender,
    )
    with scoped_session(None, actor_id=actor_id) as session:
        # Herverwerking van een afgebroken run: het bron-document (idempotent op sha256) kan al
        # een splitsingsvoorstel dragen — dan geen tweede rij toevoegen.
        bestaande_splitsing = session.scalars(
            select(IntakeSplitsing).where(IntakeSplitsing.bron_document_id == document_id)
        ).first()
        if bestaande_splitsing is None:
            session.add(
                IntakeSplitsing(
                    bron_document_id=document_id,
                    voorstel={"paginas": paginas, "facturen": [s.als_dict() for s in segmenten]},
                )
            )
    return BijlageResultaat(
        bestandsnaam=bijlage.bestandsnaam,
        uitkomst="splitsingsvoorstel",
        document_id=document_id,
        detail=f"{len(segmenten)} facturen herkend — splitsing ter controle",
    )


def verwerk_eml(
    inhoud: bytes,
    *,
    actor_id: uuid.UUID,
    bron: str = "eml_upload",
    opslag: DocumentOpslag | None = None,
) -> IntakeResultaat:
    """Verwerkt één .eml-bericht (upload of — later, via dezelfde route — de live IMAP-fetch).
    Idempotent op Message-ID: hetzelfde bericht wordt nooit twee keer verwerkt."""
    try:
        mail: IntakeMail = parse_eml(inhoud)
    except GeenGeldigeEml as exc:
        raise GeenGeldigIntakeBericht(str(exc)) from exc

    herverwerking = False
    if mail.message_id:
        with scoped_session(None) as session:
            bestaand = session.scalars(select(IntakeBericht).where(IntakeBericht.message_id == mail.message_id)).first()
            if bestaand is not None:
                if (bestaand.detail or {}).get("verwerking") != "bezig":
                    return IntakeResultaat(bericht_id=bestaand.id, al_eerder_verwerkt=True)
                # Blijven hangen op "bezig" = een eerder afgebroken run (crash/kill vóór het
                # eindresultaat op de rij stond) — dat is geen "al verwerkt": her-upload moet
                # HERVERWERKEN, niet vroeg terugkeren. Bijlagen die de vorige poging al wél
                # als document registreerde, worden niet gedupliceerd: de documentenservice is
                # idempotent op (intake_bericht_id, sha256) — zie documenten/service.py.
                herverwerking = True

    # Het bericht-record ontstaat vóór de bijlage-verwerking: de document-rijen dragen een FK
    # naar dit bericht (herkomst) en elke bijlage committert in zijn eigen transactie. Het
    # verwerkingsresultaat wordt ná afloop op de rij gezet.
    bericht_id = bestaand.id if herverwerking else uuid.uuid4()
    with scoped_session(None, actor_id=actor_id) as session:
        if herverwerking:
            bericht = session.get(IntakeBericht, bericht_id)
            assert bericht is not None
            bericht.verwerkt_door = actor_id
            bericht.detail = {"bijlagen": [], "verwerking": "bezig", "herverwerking": True}
        else:
            session.add(
                IntakeBericht(
                    id=bericht_id,
                    message_id=mail.message_id,
                    afzender=mail.afzender,
                    onderwerp=mail.onderwerp,
                    bron=bron,
                    ontvangen_op=mail.ontvangen_op,
                    verwerkt_door=actor_id,
                    detail={"bijlagen": [], "verwerking": "bezig"},
                )
            )

    resultaten: list[BijlageResultaat] = []
    for bijlage in mail.bijlagen:
        if bijlage.is_xml:
            resultaten.append(
                _verwerk_xml(
                    bijlage,
                    afzender=mail.afzender,
                    actor_id=actor_id,
                    intake_bericht_id=bericht_id,
                    opslag=opslag,
                )
            )
        elif bijlage.is_pdf:
            resultaten.append(
                _verwerk_pdf(
                    bijlage,
                    afzender=mail.afzender,
                    actor_id=actor_id,
                    intake_bericht_id=bericht_id,
                    opslag=opslag,
                )
            )
        else:
            resultaten.append(
                BijlageResultaat(
                    bestandsnaam=bijlage.bestandsnaam,
                    uitkomst="niet_verwerkbaar",
                    detail=f"bijlagetype {bijlage.content_type} wordt niet verwerkt "
                    "(zichtbaar geregistreerd, geen document)",
                )
            )

    with scoped_session(None, actor_id=actor_id) as session:
        bericht = session.get(IntakeBericht, bericht_id)
        assert bericht is not None
        bericht.detail = {"bijlagen": [r.als_dict() for r in resultaten]}
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="intake_bericht",
            record_id=bericht_id,
            actie="intake_bericht_verwerkt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "afzender": mail.afzender,
                "bijlagen": len(mail.bijlagen),
                "uitkomsten": [r.uitkomst for r in resultaten],
                "herverwerking": herverwerking,
            },
            administratie_id=None,
        )

    return IntakeResultaat(bericht_id=bericht_id, al_eerder_verwerkt=False, bijlagen=resultaten)
