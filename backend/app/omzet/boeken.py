"""Omzet-boekmotor: entity-loze Receipt + gekoppeld kostprijsmemoriaal als ÉÉN logische transactie.

Kasomzet boekt als entity-loze SalesInvoice (= Receipt, RLZ-UI "Verkopen → Boekingen") —
besluit Peter 2026-08-08, Receipts-verkenning 2026-08-07: geen dummy-debiteur "Kasomzet" meer;
zelfde PUT-route, `Entity` weggelaten, mét de administratie-specifieke DocumentCategory
"Verkoopfactuur (Omzet)". Btw-aangifte-gedrag is bewezen identiek (verkenning §3).

RLZ kent geen cross-call-atomiciteit (STAP 0 §6) — de één-transactie-garantie komt volledig
hieruit:
- Deterministische client-GUID's per document (rlz_sales_invoice_id / rlz_kostprijs_memoriaal_id):
  elke retry raakt exact dezelfde twee RLZ-documenten, nooit een duplicaat.
- Vaste volgorde: eerst de verkoopboeking, dan het memoriaal. Faalt het memoriaal ná een
  geboekte verkoop, dan wordt de verkoop gestorneerd (actie 19); faalt óók die storno, dan
  ontstaat de zichtbare foutstatus HALF_GEBOEKT (omzet_boeking-rij + boeken_mislukt op het
  document + omzet-reconciliatie) — nooit stil één helft laten staan.
- Retry-inhaal via GET-op-eigen-GUID (SalesInvoices/{id} leest ook een Receipt); duplicaten
  van ándere documenten vangt de lokale periode-bewaking plus — sinds de Receipts-verkenning —
  de Receipts-collectie-check op de deterministische periode-omschrijving (Description).

De verkoopmotor (`_boek_verkoopfactuur`) is bewust generiek gehouden (klant optioneel, regels,
datum, bijlage — geen kassarapport-aannames): dit is de GEDEELDE SalesInvoice-boekmotor waar de
Vastly-verkoopfactuur-routing (koppelcontract §2d, fase 3, mét Entity) op aansluit.

Failsafes: zelfde poorten als het inkoop-boeken (checks server-side herhalen, toggle per
administratie + globale kill switch, volumerem — gedeeld geteld over álle boekingen van de
administratie).
"""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.bank.matchmotor import splits_incl_bedrag
from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.boeken import (
    _KAN_BOEKPOGING_STARTEN_VANUIT,
    BoekenGeblokkeerdDoorChecks,
    BoekenUitgeschakeld,
    OngeldigeBoekpoging,
    RlzBoekingMislukt,
    VolumeremBereikt,
    _boekingen_vandaag,
    _is_boeken_toegestaan,
    _rlz_client_voor,
    _zet_boeken_mislukt,
)
from app.documenten.models import Document, DocumentStatus
from app.documenten.rlz_ids import (
    rlz_kostprijs_memoriaal_id,
    rlz_omzet_upload_id,
    rlz_sales_invoice_id,
)
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang, _standaard_opslag
from app.omzet.models import OmzetBoeking, OmzetBoekingStatus, OmzetInstelling
from app.omzet.voorstel import (
    OmzetVoorstelData,
    haal_omzet_voorstel_op,
    memoriaal_referentie,
    verkoop_omschrijving,
    voer_omzet_checks_uit,
)
from app.rlz.bijlage import zorg_voor_bijlage
from app.rlz.client import RlzApiError, RlzClient
from app.sync.models import TaxRateCache

logger = logging.getLogger(__name__)

# De administratie-specifieke DocumentCategory van entity-loze Receipts (Receipts-verkenning;
# read-only geverifieerd 2026-08-09: 4 DocumentType-10-categorieën, deze naam is daarbinnen
# uniek en HasSystemId is — anders dan eerst aangenomen — geen bruikbaar selectieveld).
VERKOOP_OMZET_CATEGORIE_NAAM = "Verkoopfactuur (Omzet)"
_VERKOOP_DOCUMENTTYPE = 10

# RLZ's foutmelding bij een botsend verkoopnummer (STAP 0 §1) — het signaal voor het
# deterministische nummer-herstel hieronder.
_FACTUURNUMMER_IN_GEBRUIK = "factuurnummer is al in gebruik"


class OmzetBoekenFout(Exception):
    """Basis voor domeinfouten in de omzet-boekactie."""


class HalfGeboekt(OmzetBoekenFout):
    """De verkoopfactuur is geboekt, het kostprijsmemoriaal faalde én de storno van de verkoop
    faalde ook — de zichtbare "nooit stil een halve boeking"-foutstatus. De omzet_boeking-rij
    staat op half_geboekt; de omzet-reconciliatie rapporteert 'm tot een mens het oplost."""


@dataclass(frozen=True)
class OmzetBoekResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    verkoop_rlz_id: uuid.UUID
    verkoop_referentie: str | None
    verkoop_boekstuknummer: str | None
    memoriaal_rlz_id: uuid.UUID | None
    memoriaal_boekstuknummer: str | None


def _taxrate_percentages(administratie_id: uuid.UUID) -> dict[uuid.UUID, Decimal | None]:
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(select(TaxRateCache).where(TaxRateCache.administratie_id == administratie_id)).all()
        return {rij.id: rij.percentage for rij in rijen}


def _verkoop_lines(
    voorstel: OmzetVoorstelData, percentages: dict[uuid.UUID, Decimal | None], *, marker: str
) -> list[dict]:
    """Verkoopregels per categorie. Kassarapport-bedragen zijn kassabedragen (inclusief btw) —
    de btw-splitsing gebeurt hier deterministisch op het percentage uit de taxrate-cache
    (app/bank/matchmotor.splits_incl_bedrag: som is per constructie exact het rapportbedrag).
    Vrijgesteld/0% → geen splitsing, TaxAmount 0 (BLOW-case).

    De deterministische periode-marker (verkoop_omschrijving) staat als PREFIX in de Description
    van regel 1: RLZ negeert de document-Description op SalesInvoices en leidt 'm af uit de
    éérste regel-Description (verkoop-STAP-0 2026-08-09) — zonder deze prefix zou de
    Receipts-duplicaatcheck nooit een treffer zien."""
    lines: list[dict] = []
    for regel in voorstel.regels:
        if regel.omzet_bedrag is None:
            continue
        assert regel.omzet_ledger_id is not None and regel.taxrate_id is not None  # checks draaiden al
        netto, btw = splits_incl_bedrag(regel.omzet_bedrag, percentages.get(regel.taxrate_id))
        omschrijving = regel.categorie if lines else f"{marker} · {regel.categorie}"
        lines.append(
            {
                "Account": {"id": str(regel.omzet_ledger_id)},
                "TaxRate": {"id": str(regel.taxrate_id)},
                "NetAmount": float(netto),
                "TaxAmount": float(btw),
                "Description": omschrijving,
            }
        )
    return lines


def _memoriaal_lines(voorstel: OmzetVoorstelData) -> list[dict]:
    """Kostprijsmemoriaal: debet kostprijs-GB per categorie, credit voorraad voor het totaal
    (mockup: "aan Voorraad handelsgoederen") — saldo 0 per constructie, en door de harde check
    (memoriaal-saldo-0) én RLZ zelf (STAP 0 §4) nogmaals afgedwongen."""
    kostprijs_regels = [r for r in voorstel.regels if r.kostprijs_bedrag is not None and r.kostprijs_bedrag != 0]
    if not kostprijs_regels:
        return []
    assert voorstel.voorraad_ledger_id is not None  # afgedwongen door de harde checks
    lines: list[dict] = [
        {
            "Account": {"id": str(r.kostprijs_ledger_id)},
            "CreditOrDebit": 1,
            "DebitAmount": float(r.kostprijs_bedrag or 0),
            "Description": f"Kostprijs {r.categorie}",
        }
        for r in kostprijs_regels
    ]
    totaal = sum((r.kostprijs_bedrag or Decimal(0) for r in kostprijs_regels), Decimal(0))
    lines.append(
        {
            "Account": {"id": str(voorstel.voorraad_ledger_id)},
            "CreditOrDebit": 2,
            "CreditAmount": float(totaal),
            "Description": "Aan voorraad (kostprijs omzetperiode)",
        }
    )
    return lines


def _zorg_voor_verkoop_categorie(*, client: RlzClient, administratie_id: uuid.UUID) -> uuid.UUID:
    """De DocumentCategory "Verkoopfactuur (Omzet)" van deze administratie — verplicht op de
    entity-loze Receipt-PUT (Receipts-verkenning §2). Per administratie opgehaald (GUID nooit
    hardcoden — LastBankImport-les: systeem-GUID's lijken identiek over administraties, maar
    daar bouwen we nooit op) en daarna gecachet in omzet_instelling, zelfde patroon als het
    memoriaal-dagboek."""
    with scoped_session(administratie_id) as session:
        instelling = session.get(OmzetInstelling, administratie_id)
        if instelling is not None and instelling.verkoop_categorie_id is not None:
            return instelling.verkoop_categorie_id

    kandidaten = [
        c
        for c in client.list_document_categories()
        if c.get("DocumentType") == _VERKOOP_DOCUMENTTYPE and c.get("Name") == VERKOOP_OMZET_CATEGORIE_NAAM
    ]
    if len(kandidaten) != 1:
        raise RlzBoekingMislukt(
            f'DocumentCategory "{VERKOOP_OMZET_CATEGORIE_NAAM}" (DocumentType {_VERKOOP_DOCUMENTTYPE}) niet '
            f"eenduidig gevonden in deze administratie ({len(kandidaten)} treffers) — "
            "de entity-loze verkoopboeking kan niet geboekt worden"
        )
    categorie_id = uuid.UUID(kandidaten[0]["id"])

    with scoped_session(administratie_id) as session:
        instelling = session.get(OmzetInstelling, administratie_id)
        if instelling is None:
            instelling = OmzetInstelling(administratie_id=administratie_id)
            session.add(instelling)
        instelling.verkoop_categorie_id = categorie_id
    return categorie_id


def _zorg_voor_memoriaal_dagboek(*, client: RlzClient, administratie_id: uuid.UUID) -> uuid.UUID:
    """Het dagboek voor algemene memoriaalboekingen, per administratie opgevraagd (STAP 0 §3:
    lijkt een RLZ-breed systeem-GUID, maar nooit hardcoden) en daarna gecachet."""
    with scoped_session(administratie_id) as session:
        instelling = session.get(OmzetInstelling, administratie_id)
        if instelling is not None and instelling.memoriaal_diary_id is not None:
            return instelling.memoriaal_diary_id

    diaries = client.list_journal_entry_diaries()
    memoriaal = [d for d in diaries if "memoriaal" in (d.get("Description") or "").lower()]
    if not memoriaal:
        raise RlzBoekingMislukt(
            "Geen memoriaal-dagboek gevonden in deze administratie (JournalEntryDiaries) — "
            "het kostprijsmemoriaal kan niet geboekt worden"
        )
    diary_id = uuid.UUID(memoriaal[0]["id"])

    with scoped_session(administratie_id) as session:
        instelling = session.get(OmzetInstelling, administratie_id)
        if instelling is None:
            instelling = OmzetInstelling(administratie_id=administratie_id)
            session.add(instelling)
        instelling.memoriaal_diary_id = diary_id
    return diary_id


def _lokaal_max_invoice_number(administratie_id: uuid.UUID) -> int:
    """Hoogste door óns gebruikte verkoopnummer — het lokale deel van het nummer-herstel: de
    RLZ-collectie ziet onze eigen API-facturen niet (STAP 0 §2), dus RLZ's collectie-max alleen
    is niet genoeg."""
    with scoped_session(administratie_id) as session:
        maximum = session.scalar(
            select(OmzetBoeking.verkoop_invoice_number)
            .where(
                OmzetBoeking.administratie_id == administratie_id,
                OmzetBoeking.verkoop_invoice_number.isnot(None),
            )
            .order_by(OmzetBoeking.verkoop_invoice_number.desc())
            .limit(1)
        )
        return maximum or 0


def _boek_verkoopfactuur(
    *,
    client: RlzClient,
    rlz_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    lines: list[dict],
    datum_iso: str,
    upload_id: uuid.UUID,
    bestandsnaam: str,
    bestand: bytes,
    lokaal_max_invoice_number: int,
    categorie_id: uuid.UUID | None = None,
    omschrijving: str | None = None,
) -> tuple[int | None, str | None, str | None]:
    """Generieke SalesInvoice-boekmotor (herbruikbaar — Vastly-routing fase 3, koppelcontract
    §2d, dan mét customer_id): PUT → bijlage → actie 17, met (a) retry-inhaal via
    GET-op-eigen-GUID en (b) het deterministische nummer-herstel voor RLZ's "factuurnummer al
    in gebruik" (STAP 0 §1: RLZ's eigen nummerteller kan botsen met import-historie).
    `customer_id=None` + `categorie_id` = de entity-loze Receipt-vorm (Receipts-verkenning §2);
    `omschrijving` wordt de Description — voor kasomzet de deterministische periode-omschrijving
    waar de duplicaatbewaking-op-afstand op filtert. Retourneert
    (invoice_number, referentie, boekstuknummer)."""

    def _huidige_staat() -> dict | None:
        try:
            return client.get_sales_invoice(rlz_id)
        except RlzApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    bestaand = _huidige_staat()
    if bestaand is not None and bestaand.get("Status") in (2, 3):
        # Retry-inhaal: een eerdere poging heeft deze factuur al geboekt.
        return bestaand.get("InvoiceNumber"), bestaand.get("Reference"), bestaand.get("ReceiptNumber")

    # Punt 15 (28-08): BookDate = documentdatum — de journaalpost volgt BookDate (STAP 0 boekdatum).
    body_extra: dict = {"Date": datum_iso, "BookDate": datum_iso}
    if omschrijving is not None:
        body_extra["Description"] = omschrijving
    put_extra: dict = {"document_category_id": categorie_id} if categorie_id is not None else {}
    client.put_sales_invoice(rlz_id, customer_id=customer_id, lines=lines, **put_extra, **body_extra)
    zorg_voor_bijlage(
        client,
        "SalesInvoices",
        rlz_id,
        upload_id=upload_id,
        filename=bestandsnaam,
        content_base64=base64.b64encode(bestand).decode(),
    )
    try:
        client.book_sales_invoice(rlz_id)
    except RlzApiError as exc:
        if exc.status_code != 400 or _FACTUURNUMMER_IN_GEBRUIK not in exc.body.lower():
            raise
        # Nummer-herstel (STAP 0 §1): RLZ's auto-nummer botst (teller loopt achter op de
        # import-historie). Deterministisch nieuw nummer = max(RLZ-collectie, eigen lokale
        # boekingen) + 1; één herstelpoging, daarna zichtbare boekfout. (De Receipts-collectie
        # ziet wél alles maar kent InvoiceNumber niet als filter-/sorteerveld — read-only
        # geverifieerd 2026-08-09 — dus dit blijft het herstel-pad.)
        nieuw_nummer = max(client.max_sales_invoice_number(), lokaal_max_invoice_number) + 1
        logger.warning(
            "Verkoopnummer-botsing op SalesInvoice %s — herstel met expliciet InvoiceNumber %s",
            rlz_id,
            nieuw_nummer,
        )
        client.put_sales_invoice(
            rlz_id, customer_id=customer_id, lines=lines, InvoiceNumber=nieuw_nummer, **put_extra, **body_extra
        )
        client.book_sales_invoice(rlz_id)

    geboekt = client.get_sales_invoice(rlz_id)
    return geboekt.get("InvoiceNumber"), geboekt.get("Reference"), geboekt.get("ReceiptNumber")


def _boek_memoriaal(
    *,
    client: RlzClient,
    rlz_id: uuid.UUID,
    diary_id: uuid.UUID,
    lines: list[dict],
    referentie: str,
    datum_iso: str,
    upload_id: uuid.UUID,
    bestandsnaam: str,
    bestand: bytes,
) -> str | None:
    """ManualJournal-motor: PUT (autoCorrect=false — wij rekenen, RLZ corrigeert niets stil) →
    bijlage → actie 17. Retry-inhaal via GET-op-eigen-GUID. Retourneert het boekstuknummer."""
    try:
        bestaand = client.get_manual_journal(rlz_id)
    except RlzApiError as exc:
        if exc.status_code != 404:
            raise
        bestaand = None
    if bestaand is not None and bestaand.get("Status") in (2, 3):
        return bestaand.get("ReceiptNumber")

    client.put_manual_journal(
        rlz_id, diary_id=diary_id, lines=lines, Reference=referentie, Date=datum_iso, BookDate=datum_iso
    )
    zorg_voor_bijlage(
        client,
        "ManualJournals",
        rlz_id,
        upload_id=upload_id,
        filename=bestandsnaam,
        content_base64=base64.b64encode(bestand).decode(),
    )
    client.book_manual_journal(rlz_id)
    geboekt = client.get_manual_journal(rlz_id)
    return geboekt.get("ReceiptNumber")


def _registreer_half_geboekt(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    voorstel: OmzetVoorstelData,
    verkoop_rlz_id: uuid.UUID,
    verkoop_nummer: int | None,
    verkoop_referentie: str | None,
    verkoop_boekstuknummer: str | None,
    memoriaal_rlz_id: uuid.UUID,
    memoriaal_fout: str,
    storno_fout: str,
) -> None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        assert voorstel.periode_start is not None and voorstel.periode_eind is not None
        boeking = OmzetBoeking(
            administratie_id=administratie_id,
            document_id=document_id,
            periode_start=voorstel.periode_start,
            periode_eind=voorstel.periode_eind,
            totaal_omzet=voorstel.rapport_totaal_omzet or Decimal(0),
            totaal_kostprijs=voorstel.rapport_totaal_kostprijs or Decimal(0),
            verkoop_rlz_id=verkoop_rlz_id,
            verkoop_invoice_number=verkoop_nummer,
            verkoop_referentie=verkoop_referentie,
            verkoop_boekstuknummer=verkoop_boekstuknummer,
            memoriaal_rlz_id=memoriaal_rlz_id,
            memoriaal_referentie=memoriaal_referentie(voorstel.periode_start, voorstel.periode_eind),
            status=OmzetBoekingStatus.HALF_GEBOEKT.value,
            half_geboekt_detail={
                "memoriaal_fout": memoriaal_fout,
                "storno_verkoop_fout": storno_fout,
                "herstel": "verkoopfactuur staat geboekt in RLZ zonder kostprijsmemoriaal — "
                "handmatig storneren (actie 19) in RLZ of een nieuwe boekpoging doen",
            },
            geboekt_door=actor_id,
        )
        session.add(boeking)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="omzet_boeking",
            record_id=boeking.id,
            actie="omzet_half_geboekt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "verkoop_rlz_id": str(verkoop_rlz_id),
                "memoriaal_fout": memoriaal_fout,
                "storno_verkoop_fout": storno_fout,
            },
            administratie_id=administratie_id,
        )


def boek_omzet_document(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    extra_overgang_detail: dict | None = None,
) -> OmzetBoekResultaat:
    """De omzet-boekactie: harde checks server-side herhalen → failsafes (toggle + kill switch,
    volumerem) → systeemdebiteur/dagboek borgen → verkoopfactuur boeken → kostprijsmemoriaal
    boeken → registratie + GEBOEKT. Zelfde poortvolgorde als het inkoop-boeken; het
    half-geboekt-pad is hierboven gedocumenteerd."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status not in _KAN_BOEKPOGING_STARTEN_VANUIT:
            raise OngeldigeBoekpoging(f"Document staat op status {document.status.value}, kan niet boeken")
        bestandsnaam = document.bestandsnaam
        opslag_pad = document.opslag_pad

    with _rlz_client_voor(administratie_id) as client:
        rapport = voer_omzet_checks_uit(administratie_id=administratie_id, document_id=document_id, client=client)
        if rapport.geblokkeerd:
            raise BoekenGeblokkeerdDoorChecks(rapport)

        with scoped_session(administratie_id, actor_id=actor_id) as session:
            document = session.get(Document, document_id)
            assert document is not None
            if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
                _schrijf_overgang(
                    session,
                    document=document,
                    naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                    actor_id=actor_id,
                    detail={"harde_checks": "doorstaan", "reden": "harde checks doorstaan — boekpoging gestart"},
                )

        with scoped_session(administratie_id) as session:
            if not _is_boeken_toegestaan(session, administratie_id=administratie_id):
                raise BoekenUitgeschakeld("Boeken staat uit voor deze administratie of via de globale kill switch")
            limiet = settings.max_boekingen_per_dag_per_administratie
            if _boekingen_vandaag(session, administratie_id=administratie_id) >= limiet:
                raise VolumeremBereikt(f"Dagelijkse limiet van {limiet} boekingen bereikt voor deze administratie")

        voorstel = haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert voorstel.periode_start is not None and voorstel.periode_eind is not None  # checks
        periode_marker = verkoop_omschrijving(voorstel.periode_start, voorstel.periode_eind)
        verkoop_rlz_id = rlz_sales_invoice_id(document_id)
        memoriaal_rlz_id = rlz_kostprijs_memoriaal_id(document_id)
        datum_iso = f"{voorstel.periode_eind.isoformat()}T00:00:00"
        memoriaal_lines = _memoriaal_lines(voorstel)

        try:
            bestand = _standaard_opslag().lezen(pad=opslag_pad)
            categorie_id = _zorg_voor_verkoop_categorie(client=client, administratie_id=administratie_id)
            diary_id = (
                _zorg_voor_memoriaal_dagboek(client=client, administratie_id=administratie_id)
                if memoriaal_lines
                else None
            )
            verkoop_nummer, verkoop_ref, verkoop_boekstuk = _boek_verkoopfactuur(
                client=client,
                rlz_id=verkoop_rlz_id,
                customer_id=None,  # entity-loze Receipt — besluit Peter 2026-08-08
                categorie_id=categorie_id,
                # NB de document-Description wordt door RLZ genegeerd/afgeleid van regel 1
                # (verkoop-STAP-0 2026-08-09) — de marker zit dáárom als prefix in regel 1;
                # deze parameter blijft gezet voor het geval RLZ dit ooit herstelt.
                omschrijving=periode_marker,
                lines=_verkoop_lines(voorstel, _taxrate_percentages(administratie_id), marker=periode_marker),
                datum_iso=datum_iso,
                upload_id=rlz_omzet_upload_id(document_id, doel="verkoop"),
                bestandsnaam=bestandsnaam,
                bestand=bestand,
                lokaal_max_invoice_number=_lokaal_max_invoice_number(administratie_id),
            )
        except RlzApiError as exc:
            _zet_boeken_mislukt(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=str(exc)
            )
            raise RlzBoekingMislukt(str(exc)) from exc
        except (OmzetBoekenFout, RlzBoekingMislukt):
            raise
        except Exception as exc:  # noqa: BLE001 — nooit in limbo, zelfde vangnet als inkoop-boeken
            _zet_boeken_mislukt(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=str(exc)
            )
            raise

        memoriaal_boekstuk: str | None = None
        if memoriaal_lines:
            try:
                assert diary_id is not None
                memoriaal_boekstuk = _boek_memoriaal(
                    client=client,
                    rlz_id=memoriaal_rlz_id,
                    diary_id=diary_id,
                    lines=memoriaal_lines,
                    referentie=memoriaal_referentie(voorstel.periode_start, voorstel.periode_eind),
                    datum_iso=datum_iso,
                    upload_id=rlz_omzet_upload_id(document_id, doel="memoriaal"),
                    bestandsnaam=bestandsnaam,
                    bestand=bestand,
                )
            except Exception as memoriaal_exc:  # noqa: BLE001 — élk faalpad hier vergt de storno-afweging
                # Document 2 faalde ná een geboekte verkoopfactuur: eerst proberen de verkoop te
                # storneren (actie 19) zodat er níéts half staat; faalt ook dat, dan de zichtbare
                # half-geboekt-status. Beide uitkomsten eindigen als boeken_mislukt op het document.
                logger.exception("Kostprijsmemoriaal mislukt na geboekte verkoopfactuur (document %s)", document_id)
                storno_exc: Exception | None = None
                try:
                    client.correct_sales_invoice(verkoop_rlz_id)
                except Exception as exc:  # noqa: BLE001 — óók een netwerkfout hier moet in half_geboekt eindigen
                    storno_exc = exc
                if storno_exc is None:
                    reden = (
                        f"Kostprijsmemoriaal mislukte ({memoriaal_exc}); de verkoopfactuur is "
                        "teruggedraaid (actie 19) — niets half geboekt, een nieuwe poging kan"
                    )
                    _zet_boeken_mislukt(
                        administratie_id=administratie_id,
                        document_id=document_id,
                        actor_id=actor_id,
                        reden=reden,
                    )
                    raise RlzBoekingMislukt(reden) from memoriaal_exc
                _registreer_half_geboekt(
                    administratie_id=administratie_id,
                    document_id=document_id,
                    actor_id=actor_id,
                    voorstel=voorstel,
                    verkoop_rlz_id=verkoop_rlz_id,
                    verkoop_nummer=verkoop_nummer,
                    verkoop_referentie=verkoop_ref,
                    verkoop_boekstuknummer=verkoop_boekstuk,
                    memoriaal_rlz_id=memoriaal_rlz_id,
                    memoriaal_fout=str(memoriaal_exc),
                    storno_fout=str(storno_exc),
                )
                reden = (
                    f"HALF GEBOEKT: verkoopfactuur staat in RLZ, kostprijsmemoriaal mislukte "
                    f"({memoriaal_exc}) en de storno van de verkoop mislukte ook ({storno_exc}) — "
                    "zie de omzet-reconciliatie"
                )
                _zet_boeken_mislukt(
                    administratie_id=administratie_id,
                    document_id=document_id,
                    actor_id=actor_id,
                    reden=reden,
                )
                raise HalfGeboekt(reden) from memoriaal_exc

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        boeking = OmzetBoeking(
            administratie_id=administratie_id,
            document_id=document_id,
            periode_start=voorstel.periode_start,
            periode_eind=voorstel.periode_eind,
            totaal_omzet=voorstel.rapport_totaal_omzet or Decimal(0),
            totaal_kostprijs=voorstel.rapport_totaal_kostprijs or Decimal(0),
            verkoop_rlz_id=verkoop_rlz_id,
            verkoop_invoice_number=verkoop_nummer,
            verkoop_referentie=verkoop_ref,
            verkoop_boekstuknummer=verkoop_boekstuk,
            memoriaal_rlz_id=memoriaal_rlz_id if memoriaal_lines else None,
            memoriaal_referentie=(
                memoriaal_referentie(voorstel.periode_start, voorstel.periode_eind) if memoriaal_lines else None
            ),
            memoriaal_boekstuknummer=memoriaal_boekstuk,
            status=OmzetBoekingStatus.GEBOEKT.value,
            geboekt_door=actor_id,
        )
        session.add(boeking)
        session.flush()
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.GEBOEKT,
            actor_id=actor_id,
            detail={
                "verkoop_rlz_id": str(verkoop_rlz_id),
                "verkoop_boekstuknummer": verkoop_boekstuk,
                "memoriaal_rlz_id": str(memoriaal_rlz_id) if memoriaal_lines else None,
                "memoriaal_boekstuknummer": memoriaal_boekstuk,
                "periode": f"{voorstel.periode_start} t/m {voorstel.periode_eind}",
                "reden": f"geboekt in RLZ — verkoopboekstuk {verkoop_boekstuk or str(verkoop_rlz_id)[:8]}",
                # Omzet-autoboeken (GO 01-09): `automatisch_geboekt` + bron reizen mee in de tijdlijn —
                # zelfde chip/filter als inkoop en verkoop.
                **(extra_overgang_detail or {}),
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="omzet_boeking",
            record_id=boeking.id,
            actie="omzet_geboekt_in_rlz",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "verkoop_rlz_id": str(verkoop_rlz_id),
                "verkoop_boekstuknummer": verkoop_boekstuk,
                "memoriaal_rlz_id": str(memoriaal_rlz_id) if memoriaal_lines else None,
                "memoriaal_boekstuknummer": memoriaal_boekstuk,
                "periode_start": voorstel.periode_start.isoformat(),
                "periode_eind": voorstel.periode_eind.isoformat(),
                "totaal_omzet": str(voorstel.rapport_totaal_omzet),
                "totaal_kostprijs": str(voorstel.rapport_totaal_kostprijs),
            },
            administratie_id=administratie_id,
        )

    return OmzetBoekResultaat(
        document_id=document_id,
        status=DocumentStatus.GEBOEKT,
        verkoop_rlz_id=verkoop_rlz_id,
        verkoop_referentie=verkoop_ref,
        verkoop_boekstuknummer=verkoop_boekstuk,
        memoriaal_rlz_id=memoriaal_rlz_id if memoriaal_lines else None,
        memoriaal_boekstuknummer=memoriaal_boekstuk,
    )
