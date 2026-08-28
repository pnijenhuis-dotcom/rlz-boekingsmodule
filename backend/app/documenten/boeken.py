from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, BoekenInstelling, Grootboekrekening
from app.db.session import scoped_session
from app.documenten.boekstand import volgend_volgnummer
from app.documenten.boekvoorstel import BoekvoorstelData, haal_boekvoorstel_op, voer_checks_uit
from app.documenten.checks import CheckRapport
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentStatus, WebhookUitgaand
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_herboeking_upload_id
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang, _standaard_opslag
from app.documenten.webhook import WebhookRegel, bouw_factuur_geboekt_payload
from app.geheugen.leerlus import leg_boeking_vast
from app.rlz.bijlage import zorg_voor_bijlage
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import VendorCache

_KAN_BOEKPOGING_STARTEN_VANUIT = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
        DocumentStatus.BOEKEN_MISLUKT,
        # Handmatig afmaken (migratie 0015): de controleur heeft alles zelf ingevuld — de harde
        # checks (project verplicht per regel, regelsom) blijven onverkort de poort.
        DocumentStatus.HANDMATIG_AFMAKEN,
        # Klant-accordering (bugfix-run 28-08): ná het laatste akkoord blijft het document op
        # ter_accordering tot de boeking écht staat — de motor start dus óók vanaf hier, maar
        # uitsluitend door de accorderingspoort hieronder (laatste ronde AFGEROND, bedrag
        # ongewijzigd). Een open ronde = AccorderingVereist, nooit een bypass.
        DocumentStatus.TER_ACCORDERING,
    }
)


class BoekenFout(Exception):
    """Basis voor alle domeinfouten in de boek-actie."""


class OngeldigeBoekpoging(BoekenFout):
    """Het document staat niet in een status waaruit geboekt kan worden."""


class BoekenGeblokkeerdDoorChecks(BoekenFout):
    def __init__(self, rapport: CheckRapport) -> None:
        self.rapport = rapport
        super().__init__("Boeken geblokkeerd door harde checks")


class BoekenUitgeschakeld(BoekenFout):
    """Failsafe (a): boeken staat uit voor deze administratie, of de globale kill switch staat
    uit — CLAUDE.md: 'boeken-toggle per administratie + globale kill switch'."""


class AccorderingVereist(BoekenFout):
    """Klant-accordering staat aan voor deze administratie (migratie 0033): direct boeken is
    server-side geblokkeerd tot alle vereiste accorderingslagen akkoord zijn — de boekknop
    hoort "Ter accordering" te zijn; na het laatste akkoord boekt de flow zelf."""


class VolumeremBereikt(BoekenFout):
    """Failsafe (c): de dagelijkse boekingslimiet voor deze administratie is bereikt."""


class MatchAfwijkingBevestigingVereist(BoekenFout):
    """Factuurmatch fase 2 (besluit 2, Peter 2026-08-21): de urenmatch van dit document staat
    op `afwijking` en er is (nog) geen expliciete bevestiging — boeken mág, maar alleen mét
    de bewuste "boeken ondanks match-afwijking"-klik (409 + match-cijfers in de router; de
    client toont de pop-up en herhaalt de actie mét bevestigingsvlag)."""

    def __init__(self, match_info: dict) -> None:
        self.match_info = match_info
        super().__init__(
            "De urenmatch wijkt af van de goedgekeurde weekstaten — boeken vereist een expliciete bevestiging"
        )


class RlzBoekingMislukt(BoekenFout):
    """RLZ gaf een fout terug tijdens de boekpoging — het document staat op boeken_mislukt met de
    échte foutmelding; een volgende poging is idempotent (zelfde client-GUID's)."""


@dataclass(frozen=True)
class BoekResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    rlz_document_id: uuid.UUID
    rlz_boekstuknummer: str | None


def _is_boeken_toegestaan(session: Session, *, administratie_id: uuid.UUID) -> bool:
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.boeken_ingeschakeld:
        return False
    instelling = session.get(BoekenInstelling, True)
    return instelling is not None and instelling.globaal_ingeschakeld


def _boekingen_vandaag(session: Session, *, administratie_id: uuid.UUID) -> int:
    vandaag_begin = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return (
        session.scalar(
            select(func.count())
            .select_from(DocumentGebeurtenis)
            .join(Document, DocumentGebeurtenis.document_id == Document.id)
            .where(
                Document.administratie_id == administratie_id,
                DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
                DocumentGebeurtenis.tijdstip >= vandaag_begin,
            )
        )
        or 0
    )


def _zorg_voor_klaar_om_te_boeken(session: Session, *, document: Document, actor_id: uuid.UUID) -> None:
    if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=actor_id,
            detail={"harde_checks": "doorstaan", "reden": "harde checks doorstaan — boekpoging gestart"},
        )


def _rlz_client_voor(administratie_id: uuid.UUID) -> RlzClient:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)


def _als_str(waarde: object) -> str | None:
    return str(waarde) if waarde is not None else None


def toets_match_afwijking_poort(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, bevestigd: bool
) -> None:
    """Factuurmatch-poort (fase 2, besluit 2) — vóór élke boekpoging én bij het ter accordering
    aanbieden (app/accordering/service.py). Drie toetsen, fail-closed:

    1. Staten-versheid: is een betrokken weekstaat intussen met een ÁNDER document verrekend,
       dan is de match verouderd — eerst herberekenen (zichtbare 409, nooit stil dubbel
       tellen). Bewust vóór de RLZ-call getoetst: de verrekening in de slot-transactie zou
       anders pas ná het boeken in RLZ falen.
    2. Uitkomst `afwijking` zonder bevestiging → MatchAfwijkingBevestigingVereist (409 mét de
       match-cijfers; de client toont de pop-up).
    3. `bevestigd=True` van een mens → bevestiging persistent op de match-rij (migratie 0058)
       + audit, in een eigen transactie vóór het boeken. Zo kan óók het accorderingspad —
       waar de systeem-actor pas ná het laatste klant-akkoord boekt — de poort passeren op
       de eerder vastgelegde mens-bevestiging; de systeem-actor bevestigt nooit zelf
       (`bevestigd` is daar altijd False). Een herberekening wist de bevestiging weer
       (app/uren/factuurmatch.py) — nieuwe cijfers = nieuwe beslissing.

    Lazy imports: app.uren gebruikt de documenten-modellen — geen kringimport op moduleniveau."""
    from app.uren.models import Factuurmatch, FactuurmatchStaat, FactuurmatchUitkomst, Weekstaat

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        match = session.get(Factuurmatch, document_id)
        if match is None:
            return

        elders_verrekend = session.scalar(
            select(func.count())
            .select_from(FactuurmatchStaat)
            .join(Weekstaat, Weekstaat.id == FactuurmatchStaat.weekstaat_id)
            .where(
                FactuurmatchStaat.document_id == document_id,
                Weekstaat.verrekend_met_document_id.is_not(None),
                Weekstaat.verrekend_met_document_id != document_id,
            )
        )
        if elders_verrekend:
            raise OngeldigeBoekpoging(
                "Een weekstaat uit deze urenmatch is intussen met een andere factuur verrekend — "
                "herbereken de match voordat u boekt"
            )

        if match.uitkomst != FactuurmatchUitkomst.AFWIJKING.value:
            return
        if match.afwijking_bevestigd_op is not None:
            return

        match_info = {
            "uitkomst": match.uitkomst,
            "veldwerker_gebruiker_id": str(match.veldwerker_gebruiker_id),
            "staten_som_uren": _als_str(match.staten_som_uren),
            "staten_som_bedrag": _als_str(match.staten_som_bedrag),
            "factuur_bedrag": _als_str(match.factuur_bedrag),
            "factuur_uren": _als_str(match.factuur_uren),
            "verschil_bedrag": _als_str(match.verschil_bedrag),
            "verschil_uren": _als_str(match.verschil_uren),
            "tarief_ontbreekt": match.tarief_ontbreekt,
        }
        if not bevestigd:
            raise MatchAfwijkingBevestigingVereist(match_info)

        match.afwijking_bevestigd_door = actor_id
        match.afwijking_bevestigd_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="factuurmatch",
            record_id=document_id,
            actie="match_afwijking_bevestigd",
            correlatie_id=document_id,
            nieuwe_waarde=match_info,
            administratie_id=administratie_id,
        )


def _regels_naar_rlz_lines(voorstel: BoekvoorstelData) -> list[dict]:
    lines: list[dict] = []
    for regel in voorstel.regels:
        # btw_bedrag mag None zijn (de harde checks eisen 'm niet af, zie
        # checks.py::check_verplichte_velden) — een geldige case bij bv. verlegde btw of een
        # vrijgestelde regel, niet alleen een ontbrekend-veld-bug. netto_bedrag ís altijd gevuld
        # op dit punt (dat check wél af, en boek_document() draait de checks eerst).
        line: dict = {
            "Account": {"id": str(regel.ledger_id)},
            "TaxRate": {"id": str(regel.taxrate_id)},
            "NetAmount": float(regel.netto_bedrag),
            "TaxAmount": float(regel.btw_bedrag or 0),
        }
        if regel.project_id is not None:
            line["Project"] = {"id": str(regel.project_id)}
        if regel.omschrijving:
            line["Description"] = regel.omschrijving
        lines.append(line)
    return lines


def _boek_bij_rlz(
    *, client: RlzClient, document_id: uuid.UUID, voorstel: BoekvoorstelData, bestand: bytes, bestandsnaam: str
) -> tuple[uuid.UUID, str | None]:
    """PUT + /Uploads + actie 17, in die volgorde (RLZ berekent zelf totalen uit de regels — geen
    eigen bedragberekening hier). Retourneert (rlz_document_id, rlz_boekstuknummer). Het GUID
    volgt de boek_cyclus (tegenboek-pad): een herboeking ná "tegenboeken én opnieuw boeken" is
    een NIEUW RLZ-document — nooit een her-PUT op het geboekt blijvende origineel."""
    rlz_document_id = rlz_herboeking_id(document_id, voorstel.boek_cyclus)
    assert voorstel.vendor_id is not None and voorstel.factuurdatum is not None  # afgedwongen door de harde checks

    client.put_purchase_invoice(
        rlz_document_id,
        vendor_id=voorstel.vendor_id,
        lines=_regels_naar_rlz_lines(voorstel),
        reference=voorstel.referentie,
        # Volledige ISO-datetime, niet alleen de datum — exact de vorm die geverifieerd is tegen
        # de RLZ-test-administratie (verkenning/api-verkenning.md, "Boekstuknummer, factuurdatum
        # en /Uploads"); een kale datumstring is nooit tegen de live API getest.
        Date=f"{voorstel.factuurdatum.isoformat()}T00:00:00",
        # Vervaldatum (C1 26-08): `DueDate` — STAP-0 26-08 live bewezen (PUT 204, readback
        # identiek); zonder DueDate leidt RLZ 'm zelf af uit Date + PaymentDueDays crediteur.
        **({"DueDate": f"{voorstel.vervaldatum.isoformat()}T00:00:00"} if voorstel.vervaldatum else {}),
    )
    zorg_voor_bijlage(
        client,
        "PurchaseInvoices",
        rlz_document_id,
        upload_id=rlz_herboeking_upload_id(document_id, voorstel.boek_cyclus),
        filename=bestandsnaam,
        content_base64=base64.b64encode(bestand).decode(),
    )
    client.book_purchase_invoice(rlz_document_id)
    geboekt = client.get(f"PurchaseInvoices/{rlz_document_id}")
    return rlz_document_id, geboekt.get("ReceiptNumber")


def _zet_boeken_mislukt(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.BOEKEN_MISLUKT,
            actor_id=actor_id,
            detail={"fout": reden, "reden": f"boeken in RLZ mislukt: {reden}"},
        )


def _sla_webhook_op(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    rlz_admin_id: str,
    document_id: uuid.UUID,
    voorstel: BoekvoorstelData,
    rlz_document_id: uuid.UUID,
    rlz_boekstuknummer: str | None,
) -> None:
    """Webhook-outbox (koppelcontract §3, CLAUDE.md-taak 2.5): ONGETEKENDE payload bouwen en in
    de outbox leggen — de afleveraar (app/documenten/webhook_afleveraar.py) tekent per
    verzendpoging (timestamp/nonce/HMAC), anders wijst het ~5 min-replay-venster van de
    ontvanger elke latere aflevering af.

    Scope (hardening-audit 2026-07-13): het koppelcontract beperkt de push tot inkoopfacturen
    van vastgoed-administraties — de outbox-rij ontstaat dus alleen als `is_vastgoed` aan staat
    (migratie 0018). Filteren gebeurt bewust hier bij het aanmaken, niet pas in de afleveraar:
    een rij die er nooit had mogen zijn kan dan ook nooit per ongeluk afgeleverd worden (de
    afleveraar assert dit desondanks nog eens)."""
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.is_vastgoed:
        return

    vendor_naam = None
    if voorstel.vendor_id is not None:
        vendor = session.get(VendorCache, (voorstel.vendor_id, administratie_id))
        vendor_naam = vendor.naam if vendor else None

    webhook_regels = []
    for regel in voorstel.regels:
        grootboek = session.get(Grootboekrekening, (regel.ledger_id, administratie_id))
        webhook_regels.append(
            WebhookRegel(
                ledger_id=regel.ledger_id,
                grootboek_code=grootboek.code if grootboek else "",
                project_id=regel.project_id,
                netto_bedrag=regel.netto_bedrag,
                btw_bedrag=regel.btw_bedrag,
                omschrijving=regel.omschrijving,
            )
        )

    payload = bouw_factuur_geboekt_payload(
        administratie_id=administratie_id,
        rlz_admin_id=rlz_admin_id,
        rlz_document_id=rlz_document_id,
        rlz_boekstuknummer=rlz_boekstuknummer,
        factuurdatum=voorstel.factuurdatum,
        vendor_id=voorstel.vendor_id,
        vendor_naam=vendor_naam,
        referentie=voorstel.referentie or "",
        # Boekstand-reeks (v1.14): een herboeking ná storno (zelfde deterministische
        # client-GUID) krijgt zo een hoger volgnummer dan de eerdere boeking/storno.
        volgnummer=volgend_volgnummer(session, document_id=document_id, rlz_document_id=rlz_document_id),
        regels=webhook_regels,
    )
    session.add(WebhookUitgaand(document_id=document_id, event=payload["event"], payload=payload))


def boek_document(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    extra_overgang_detail: dict | None = None,
    match_afwijking_bevestigd: bool = False,
    materiaal_afwijking_bevestigd: bool = False,
) -> BoekResultaat:
    """De boekactie (CLAUDE.md-taak 2.3): harde checks herhalen (nooit de client-kant vertrouwen),
    dan de twee resterende failsafes (toggle+kill switch, volumerem), dan pas de echte RLZ-
    schrijfacties. Een blokkerende check/failsafe laat de status ongewijzigd, bùiten het
    klaarzetten op klaar_om_te_boeken zodra de checks zelf doorstaan — dat wordt in zijn eigen,
    los gecommitte transactie gedaan (vóór de failsafe-checks), zodat een falende failsafe die
    winst niet weer terugdraait: een latere retry hoeft de checks dan niet opnieuw te doorstaan."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status not in _KAN_BOEKPOGING_STARTEN_VANUIT:
            raise OngeldigeBoekpoging(f"Document staat op status {document.status.value}, kan niet boeken")
        # Poort op documentsoort (migratie 0027/0028): deze motor boekt uitsluitend
        # PurchaseInvoices — een kassarapport gaat via app/omzet/boeken.py, een
        # Vastly-verkoopfactuur (§2d) via het (nog te bouwen) verkoopfactuur-reviewpad op de
        # omzetmotor. Nooit stil het verkeerde documenttype in de inkoop-motor.
        if document.soort != "inkoopfactuur":
            raise OngeldigeBoekpoging(
                f"Document heeft soort {document.soort} — deze boekactie is alleen voor inkoopfacturen"
            )
        bestandsnaam = document.bestandsnaam
        opslag_pad = document.opslag_pad
        rlz_admin_id = rlz_admin_id_voor(administratie_id)

    # Klant-accorderingspoort (migratie 0033, server-side — nooit de client-knop vertrouwen):
    # staat accordering aan, dan mag deze motor alleen draaien mét een afgeronde ronde (de
    # accorderingsflow roept 'm dan zelf aan na het laatste akkoord, of een retry na boekfout).
    # Lazy import: accordering.service gebruikt deze module — geen kringimport op moduleniveau.
    from app.accordering import service as accordering_service

    if accordering_service.is_accordering_ingeschakeld(administratie_id=administratie_id):
        with scoped_session(administratie_id) as session:
            blokkade = accordering_service.accordering_blokkade_voor_boeken(session, document_id=document_id)
            if blokkade is not None:
                raise AccorderingVereist(blokkade)

    # Factuurmatch-poort (fase 2): staten-versheid + afwijking-bevestiging, vóór de checks en
    # dus ruim vóór de RLZ-schrijfacties. Ná de accorderingspoort: "Ter accordering" hoort als
    # eerste te winnen op het controlescherm (de aanbieden-flow toetst deze poort zelf ook).
    toets_match_afwijking_poort(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        bevestigd=match_afwijking_bevestigd,
    )
    # Materiaalmatch-poort (steigerbouw-run D6, besluit Peter 24-08): zelfde vlag-patroon —
    # afwijking = 409 mét cijfers, boeken alleen mét de expliciete "ondanks materiaal-afwijking"-klik
    # (persistent + audit; de systeem-actor bevestigt nooit zelf). Lazy import: geen kring.
    from app.materiaal.match import toets_materiaalmatch_poort

    toets_materiaalmatch_poort(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        bevestigd=materiaal_afwijking_bevestigd,
    )

    with _rlz_client_voor(administratie_id) as client:
        rapport = voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=client)
        if rapport.geblokkeerd:
            raise BoekenGeblokkeerdDoorChecks(rapport)

        with scoped_session(administratie_id, actor_id=actor_id) as session:
            document = session.get(Document, document_id)
            assert document is not None
            _zorg_voor_klaar_om_te_boeken(session, document=document, actor_id=actor_id)

        with scoped_session(administratie_id) as session:
            if not _is_boeken_toegestaan(session, administratie_id=administratie_id):
                raise BoekenUitgeschakeld("Boeken staat uit voor deze administratie of via de globale kill switch")
            limiet = settings.max_boekingen_per_dag_per_administratie
            if _boekingen_vandaag(session, administratie_id=administratie_id) >= limiet:
                raise VolumeremBereikt(f"Dagelijkse limiet van {limiet} boekingen bereikt voor deze administratie")

        try:
            voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
            bestand = _standaard_opslag().lezen(pad=opslag_pad)
            rlz_document_id, rlz_boekstuknummer = _boek_bij_rlz(
                client=client, document_id=document_id, voorstel=voorstel, bestand=bestand, bestandsnaam=bestandsnaam
            )
        except RlzApiError as exc:
            _zet_boeken_mislukt(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=str(exc)
            )
            raise RlzBoekingMislukt(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            # Elke andere fout tijdens de boekpoging (netwerkfout die alle retries overleeft,
            # opslagfout bij het lezen van de bijlage, bug) mag het document nooit in limbo
            # laten staan — dezelfde blokkerende afhandeling als een RlzApiError, alleen zonder
            # aanname dat het per se een RLZ-fout is. De oorspronkelijke fout gaat door naar de
            # globale exception-handler (app/main.py), die 'm loggen en er een nette melding +
            # correlatie-id van maakt.
            _zet_boeken_mislukt(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=str(exc)
            )
            raise

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        boekvoorstel = session.get(Boekvoorstel, document_id)
        assert boekvoorstel is not None
        boekvoorstel.rlz_boekstuknummer = rlz_boekstuknummer

        # Factuurmatch (fase 2): een bevestigde afwijking draagt "geboekt ondanks
        # match-afwijking" in tijdlijn + audit (besluit 2 — de _schrijf_overgang hieronder
        # schrijft het detail in beide). Lazy import: geen kringimport op moduleniveau.
        from app.uren.factuurmatch import verreken_staten_in_sessie
        from app.uren.models import Factuurmatch, FactuurmatchUitkomst

        match = session.get(Factuurmatch, document_id)
        match_detail: dict = {}
        if match is not None and match.uitkomst == FactuurmatchUitkomst.AFWIJKING.value:
            match_detail["geboekt_ondanks_match_afwijking"] = {
                "verschil_bedrag": _als_str(match.verschil_bedrag),
                "verschil_uren": _als_str(match.verschil_uren),
                "bevestigd_door": _als_str(match.afwijking_bevestigd_door),
            }

        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.GEBOEKT,
            actor_id=actor_id,
            # extra_overgang_detail: herkomst-markering van de aanroeper (autoboeken zet hier
            # `automatisch_geboekt` — zichtbaar in tijdlijn + queryable voor het
            # werkvoorraad-filter) — nooit de kernvelden overschrijven.
            detail={
                **(extra_overgang_detail or {}),
                **match_detail,
                "rlz_document_id": str(rlz_document_id),
                "rlz_boekstuknummer": rlz_boekstuknummer,
                "reden": f"geboekt in RLZ — boekstuk {rlz_boekstuknummer or str(rlz_document_id)[:8]}",
            },
        )
        # Staten-verrekening ín de boek-transactie (fase 2, dubbeltelling-preventie): de
        # betrokken weekstaten gaan op verrekend_met_document_id — samen met de
        # GEBOEKT-overgang, of samen niet (zelfde argument als leg_boeking_vast hieronder).
        # De poort aan het begin toetste de versheid al vóór de RLZ-call.
        if match is not None:
            verreken_staten_in_sessie(
                session, administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
            )
        _sla_webhook_op(
            session,
            administratie_id=administratie_id,
            rlz_admin_id=rlz_admin_id,
            document_id=document_id,
            voorstel=voorstel,
            rlz_document_id=rlz_document_id,
            rlz_boekstuknummer=rlz_boekstuknummer,
        )
        # Leerlus boekingsgeheugen (B5): de zojuist bevestigde boeking als bron='app'-observaties,
        # in dezelfde transactie als de GEBOEKT-overgang — vendor is hier altijd gevuld
        # (afgedwongen door de harde checks die deze functie zelf herhaalde). bron_datum =
        # boekdatum: het moment van menselijke bevestiging, zodat een latere correctie
        # (actie 19 -> opnieuw boeken) via recency wint van de oorspronkelijke boeking.
        assert voorstel.vendor_id is not None
        leg_boeking_vast(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            vendor_id=voorstel.vendor_id,
            boekdatum=datetime.now(UTC).date(),
            boekstuk_ref=rlz_boekstuknummer,
            regels=voorstel.regels,
            regels_samenvoegen=voorstel.regels_samenvoegen,
        )
        # Aanbetaling-verrekening (feedbackronde 25-08 deel 4 punt 3): draagt het voorstel de
        # tegenregel −X op de vooruitbetalingsrekening, dan sluit de open aanbetaling van deze
        # crediteur ín dezelfde transactie (append-only spoor + audit). Lazy import: geen kring.
        from app.bank.relatie import markeer_verrekend_bij_boeking

        markeer_verrekend_bij_boeking(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            vendor_id=voorstel.vendor_id,
            regels=voorstel.regels,
            actor_id=actor_id,
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="boekvoorstel",
            record_id=document_id,
            actie="geboekt_in_rlz",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"rlz_document_id": str(rlz_document_id), "rlz_boekstuknummer": rlz_boekstuknummer},
            administratie_id=administratie_id,
        )

    return BoekResultaat(
        document_id=document_id,
        status=DocumentStatus.GEBOEKT,
        rlz_document_id=rlz_document_id,
        rlz_boekstuknummer=rlz_boekstuknummer,
    )
