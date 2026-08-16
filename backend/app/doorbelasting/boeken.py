"""De tweezijdige doorbelastingsmotor (opdracht blok 1c/1d): per doelentiteit, in vaste
volgorde, met het bewezen half-geboekt-patroon uit de omzetmotor —

  (1) SalesInvoice in de BRON-administratie op de bestaande verkoopmotor
      (app/omzet/boeken.py::_boek_verkoopfactuur, Entity = doel-customer-GUID uit de mapping,
      kostenregel(s) met de bron-referentie in de omschrijving + losse provisieregel,
      omzet-GB en vlak btw-tarief uit de config);
  (2) spiegel-INKOOPFACTUUR in de DOEL-administratie (crediteur = de bron-administratie,
      idempotente crediteur-aanmaak; Reference = het verkoopnummer van stap 1 — het bestaat
      pas ná het boeken van de bron-kant, STAP-0 2026-08-13; kosten-GB per verdeelregel,
      provisie op de vaste provisie-GB van de mapping).

Faalt stap 2: storno van stap 1 (actie 19); faalt die storno óók → zichtbaar `half_geboekt`
mét detail (reconciliatie vangt 'm elke ochtend). Is de doel-administratie niet onboarded
(geen credential): alléén stap 1 + een zichtbare open taak `spiegel_open` — nooit stil half.

Idempotentie: deterministische client-GUID's per (bron-factuur, doelentiteit, kant)
(rlz_ids), DB-unieke duplicaatbewaking per bron-factuur+doelentiteit (partial unique 0044),
retry-inhaal via GET-op-eigen-GUID in beide motoren. Volumerem + boeken-toggles onverkort,
aan BEIDE kanten (de doel-administratie heeft eigen rijen noch documenten — de toggle- en
scope-poorten draaien er expliciet)."""

from __future__ import annotations

import base64
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, Grootboekrekening
from app.db.session import scoped_session
from app.documenten.boeken import (
    BoekenUitgeschakeld,
    VolumeremBereikt,
    _is_boeken_toegestaan,
    _rlz_client_voor,
)
from app.documenten.boekstand import laatste_boekstand_rij, stand_van_rij, volgend_volgnummer
from app.documenten.models import (
    Boekvoorstel,
    BoekvoorstelRegel,
    Document,
    DocumentGebeurtenis,
    WebhookUitgaand,
)
from app.documenten.rlz_ids import (
    rlz_doorbelasting_spiegel_id,
    rlz_doorbelasting_upload_id,
    rlz_doorbelasting_verkoop_id,
    rlz_vendor_id,
)
from app.documenten.service import _standaard_opslag
from app.documenten.webhook import (
    FACTUUR_GEBOEKT_EVENT,
    GESTORNEERD_BRON_MODULE,
    WebhookRegel,
    bouw_factuur_geboekt_payload,
    bouw_factuur_gestorneerd_payload,
)
from app.doorbelasting.checks import voer_doorbelasting_checks_uit
from app.doorbelasting.geld import btw_over, provisie_over
from app.doorbelasting.models import (
    DoorbelastingBoeking,
    DoorbelastingBoekingStatus,
    DoorbelastingMapping,
    DoorbelastingRegel,
    DoorbelastingRun,
    DoorbelastingRunStatus,
)
from app.doorbelasting.service import (
    DoorbelastingFout,
    RunNietGevonden,
    _check_invoer,
    actor_heeft_scope,
    upsert_intercompany_tegenpartij,
)
from app.omzet.boeken import _boek_verkoopfactuur
from app.projecten.anker import anker_customer_id
from app.rlz.aangifte import AangiftePoort, KantToets, blokkeer_bij_ingediende_aangifte
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import GeenRlzCredentials
from app.sync.models import TaxRateCache, VendorCache

logger = logging.getLogger(__name__)

_MODULE = "boekhouding"


class BoekenGeblokkeerdDoorChecks(DoorbelastingFout):
    def __init__(self, rapport) -> None:
        super().__init__("Harde checks blokkeren het doorbelasten")
        self.rapport = rapport


class AdministratieNietBereikbaar(DoorbelastingFout):
    """Rechten-probe faalde vóór de eerste write (opdracht 1e)."""


class DoorbelastingHalfGeboekt(DoorbelastingFout):
    """Spiegel gefaald én storno van de bron-verkoop gefaald — zichtbaar geregistreerd."""


class DeelboekingMislukt(DoorbelastingFout):
    """Eén doelentiteit faalde (netjes teruggedraaid of nog niet begonnen); de fout staat
    per doelentiteit in run.laatste_fout — retry mogelijk."""


def _btw_percentage(session, *, administratie_id: uuid.UUID, taxrate_id: uuid.UUID) -> Decimal:
    """Percentage (bv. 21,00) uit de taxrate-cache; de cache draagt de FRACTIE (0.2100 —
    RLZ-bronformaat, zie app/sync/btw.py). Fail-closed: onbekend tarief = fout, nooit een
    stil aangenomen 21%."""
    rij = session.get(TaxRateCache, (taxrate_id, administratie_id))
    if rij is None or rij.percentage is None:
        raise DoorbelastingFout(f"Btw-tarief {taxrate_id} niet in de cache van deze administratie — sync eerst")
    return (rij.percentage * Decimal(100)).quantize(Decimal("0.01"))


def _leverancier_naam(session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None) -> str | None:
    if vendor_id is None:
        return None
    rij = session.get(VendorCache, (vendor_id, administratie_id))
    return rij.naam if rij else None


def _eigen_boekingen_vandaag(session, *, administratie_id: uuid.UUID) -> int:
    vandaag = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return session.scalar(
        select(func.count())
        .select_from(DoorbelastingBoeking)
        .where(
            DoorbelastingBoeking.administratie_id == administratie_id,
            DoorbelastingBoeking.aangemaakt_op >= vandaag,
        )
    )


def _boek_spiegel_inkoop(
    *,
    client: RlzClient,
    rlz_id: uuid.UUID,
    vendor_id: uuid.UUID,
    lines: list[dict],
    referentie: str,
    datum_iso: str,
    upload_id: uuid.UUID,
    bestandsnaam: str,
    bestand: bytes,
) -> str | None:
    """Kleine inkoopmotor voor de spiegel (bewust los van documenten/boeken.py::_boek_bij_rlz —
    die is aan BoekvoorstelData gebonden): retry-inhaal via GET-op-eigen-GUID → PUT →
    bijlage → actie 17. Retourneert het RLZ-boekstuknummer."""
    try:
        bestaand = client.get(f"PurchaseInvoices/{rlz_id}")
    except RlzApiError as exc:
        if exc.status_code != 404:
            raise
        bestaand = None
    if bestaand is not None and bestaand.get("Status") in (2, 3):
        return bestaand.get("ReceiptNumber")

    client.put_purchase_invoice(rlz_id, vendor_id=vendor_id, lines=lines, reference=referentie, Date=datum_iso)
    if bestand:
        client.upload_bijlage(
            "PurchaseInvoices",
            rlz_id,
            upload_id=upload_id,
            filename=bestandsnaam,
            content_base64=base64.b64encode(bestand).decode(),
        )
    client.book_purchase_invoice(rlz_id)
    geboekt = client.get(f"PurchaseInvoices/{rlz_id}")
    return geboekt.get("ReceiptNumber")


def _zorg_voor_crediteur_in_doel(
    *, client: RlzClient, doel_administratie_id: uuid.UUID, naam: str
) -> uuid.UUID:
    """Idempotente crediteur-aanmaak in de DOEL-administratie: lookup-vóór-PUT tegen de
    RLZ-Vendors-collectie (níét de lokale VendorCache — die kan voor een verse
    doel-administratie leeg zijn), anders PUT met deterministisch client-GUID.
    Fail-closed bij meerdere treffers (zelfde ontwerp als zorg_voor_debiteur)."""
    naam = " ".join(naam.split())
    bestaand = client.find_vendors_by_name(name=naam)
    if len(bestaand) == 1:
        return uuid.UUID(bestaand[0]["id"])
    if len(bestaand) > 1:
        raise DoorbelastingFout(
            f"Meerdere crediteuren '{naam}' in de doel-administratie — kies/schoon eerst op in RLZ"
        )
    vendor_id = rlz_vendor_id(doel_administratie_id, naam)
    client.put_vendor(vendor_id, name=naam)
    return vendor_id


def _spiegel_regelspec(
    *,
    regels: list[DoorbelastingRegel],
    bron_regels: dict[uuid.UUID, BoekvoorstelRegel],
    omschrijving_basis: str,
    btw_pct: Decimal,
    provisie: Decimal,
    provisie_btw: Decimal,
    provisie_kosten_ledger_id: uuid.UUID,
    provisie_omschrijving: str,
) -> list[tuple[uuid.UUID, Decimal, Decimal, str]]:
    """Eén regelspecificatie (ledger, netto, btw, omschrijving) voor de spiegel-inkoopfactuur,
    als enige bron voor zowel de RLZ-DocumentLineList als de webhook-regels — wat geboekt
    wordt en wat aan vastgoed gemeld wordt kan zo nooit uit elkaar lopen."""
    spec: list[tuple[uuid.UUID, Decimal, Decimal, str]] = []
    for r in regels:
        bron_regel = bron_regels[r.bron_regel_id]
        omschrijving = omschrijving_basis
        if bron_regel.omschrijving:
            omschrijving = f"{omschrijving_basis} — {bron_regel.omschrijving}"[:200]
        spec.append((r.doel_kosten_ledger_id, r.netto_deel, btw_over(r.netto_deel, btw_pct), omschrijving))
    spec.append((provisie_kosten_ledger_id, provisie, provisie_btw, provisie_omschrijving))
    return spec


def _spiegel_lines_van_spec(
    spec: list[tuple[uuid.UUID, Decimal, Decimal, str]], *, btw_taxrate_id: uuid.UUID
) -> list[dict]:
    return [
        {
            "Account": {"id": str(ledger_id)},
            "TaxRate": {"id": str(btw_taxrate_id)},
            "NetAmount": float(netto),
            "TaxAmount": float(btw),
            "Description": omschrijving,
        }
        for ledger_id, netto, btw, omschrijving in spec
    ]


def _bouw_spiegel_webhook_payload(
    *,
    bron_document_id: uuid.UUID,
    doel_administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    leverancier_naam: str,
    spiegel_rlz_id: uuid.UUID,
    spiegel_boekstuknummer: str | None,
    referentie: str,
    factuurdatum: date,
    regelspec: list[tuple[uuid.UUID, Decimal, Decimal, str]],
) -> dict | None:
    """ONGETEKENDE `factuur_geboekt`-payload voor een spiegel-inkoopfactuur in een
    vastgoed-doel-administratie (besluit Peter 2026-08-14, koppelcontract §3: het event geldt
    voor élke geboekte inkoopfactuur van een vastgoed-administratie, óók buiten de
    document-pipeline; leverancier = de bron-administratie, i.c. Kempen Facilities). None als
    de doel-administratie geen vastgoed-administratie is — zelfde aanmaak-filter als
    documenten/boeken.py::_sla_webhook_op: een rij die er niet hoort ontstaat niet.

    Standaard inkoop-veldvorm, geen eigen variant: `referentie` = de spiegel-Reference (het
    verkoopnummer van de bron-kant), `rlz_document_id` = de spiegel-GUID in de
    doel-administratie. De GB-codes komen uit de ledger-cache van de dóél-administratie
    (eigen scope — RLS laat die niet vanuit de bron-sessie lezen)."""
    with scoped_session(None) as session:
        doel = session.get(Administratie, doel_administratie_id)
        if doel is None or not doel.is_vastgoed:
            return None
        rlz_admin_id = doel.rlz_admin_id
    webhook_regels: list[WebhookRegel] = []
    with scoped_session(doel_administratie_id) as session:
        for ledger_id, netto, btw, omschrijving in regelspec:
            grootboek = session.get(Grootboekrekening, (ledger_id, doel_administratie_id))
            webhook_regels.append(
                WebhookRegel(
                    ledger_id=ledger_id,
                    grootboek_code=grootboek.code if grootboek else "",
                    project_id=None,
                    netto_bedrag=netto,
                    btw_bedrag=btw,
                    omschrijving=omschrijving,
                )
            )
        # Boekstand-reeks per spiegel (v1.14): na een storno + nieuwe run hergebruikt het
        # deterministische spiegel-GUID hetzelfde rlz_document_id — het volgnummer maakt de
        # herboeking voor vastgoed onderscheidbaar. Doel-scope ziet de eerdere spiegel-rijen
        # via de administratie_id-kolom (RLS, migratie 0046).
        volgnummer = volgend_volgnummer(session, document_id=bron_document_id, rlz_document_id=spiegel_rlz_id)
    return bouw_factuur_geboekt_payload(
        administratie_id=doel_administratie_id,
        rlz_admin_id=rlz_admin_id,
        rlz_document_id=spiegel_rlz_id,
        rlz_boekstuknummer=spiegel_boekstuknummer,
        factuurdatum=factuurdatum,
        vendor_id=vendor_id,
        vendor_naam=leverancier_naam,
        referentie=referentie,
        volgnummer=volgnummer,
        regels=webhook_regels,
    )


def _rechten_probe(client: RlzClient, *, label: str) -> None:
    """Goedkope read vóór de eerste write (opdracht 1e: beide administraties bereikbaar).
    Eén GET met $top=1 — faalt die, dan is er nog niets geschreven."""
    try:
        client.get("Ledgers", params={"$top": "1"})
    except RlzApiError as exc:
        raise AdministratieNietBereikbaar(
            f"Rechten-probe {label} faalde ({exc.status_code}) — er is niets geboekt"
        ) from exc


def _registreer_fout(run_id: uuid.UUID, administratie_id: uuid.UUID, mapping_id: uuid.UUID, fout: str) -> None:
    with scoped_session(administratie_id) as session:
        run = session.get(DoorbelastingRun, run_id)
        if run is not None:
            laatste = dict(run.laatste_fout or {})
            laatste[str(mapping_id)] = {"fout": fout[:500], "ts": datetime.now(UTC).isoformat()}
            run.laatste_fout = laatste


def _wis_fout(session, run: DoorbelastingRun, mapping_id: uuid.UUID) -> None:
    if run.laatste_fout and str(mapping_id) in run.laatste_fout:
        laatste = dict(run.laatste_fout)
        laatste.pop(str(mapping_id), None)
        run.laatste_fout = laatste or None


def _tijdlijn(session, *, document: Document, actor_id: uuid.UUID, detail: dict) -> None:
    """Tijdlijnregel zonder statuswijziging (het bron-document blijft 'geboekt') — bestaand
    patroon (iban_accordering/accordering)."""
    session.add(
        DocumentGebeurtenis(
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail=detail,
        )
    )


def boek_doorbelasting_run(
    *,
    administratie_id: uuid.UUID,
    run_id: uuid.UUID,
    actor_id: uuid.UUID,
    bron_client: RlzClient | None = None,
    doel_client_factory: Callable[[uuid.UUID], RlzClient] | None = None,
) -> dict[str, str]:
    """Boekt de run per doelentiteit (onafhankelijk: één falende doelentiteit stopt de rest
    niet — mockup: "zichtbare status per deelboeking"). Retourneert status per mapping-id.
    `bron_client`/`doel_client_factory` zijn test-seams (patroon omzet/verkoop-tests)."""
    # --- poorten (alles vóór de eerste RLZ-call) ------------------------------------------
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        run = session.get(DoorbelastingRun, run_id)
        if run is None or run.administratie_id != administratie_id:
            raise RunNietGevonden("Onbekende run voor deze administratie")
        if run.status == DoorbelastingRunStatus.GESTORNEERD.value:
            raise DoorbelastingFout("Deze run is gestorneerd")
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.doorbelasting_ingeschakeld:
            raise DoorbelastingFout("Doorbelasting staat uit voor deze administratie")
        if not _is_boeken_toegestaan(session, administratie_id=administratie_id):
            raise BoekenUitgeschakeld("Boeken staat uit voor deze administratie of via de globale kill switch")

        invoer, mapping_invoer, instelling = _check_invoer(session, run)
        rapport = voer_doorbelasting_checks_uit(
            regels=invoer,
            mappings=mapping_invoer,
            provisie_percentage=instelling.provisie_percentage,
            btw_taxrate_id=instelling.btw_taxrate_id,
            omzet_ledger_id=instelling.omzet_ledger_id,
            anker_customer_guid=anker_customer_id(administratie_id),
        )
        if rapport.geblokkeerd:
            raise BoekenGeblokkeerdDoorChecks(rapport)

        document = session.get(Document, run.document_id)
        voorstel = session.get(Boekvoorstel, run.document_id)
        if document is None or voorstel is None:
            raise DoorbelastingFout("Bron-document of boekvoorstel niet gevonden")
        bron_regels = {
            r.id: r
            for r in session.scalars(
                select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == run.document_id)
            )
        }
        mappings = {
            m.id: m
            for m in session.scalars(
                select(DoorbelastingMapping).where(DoorbelastingMapping.administratie_id == administratie_id)
            )
        }
        regels = list(session.scalars(select(DoorbelastingRegel).where(DoorbelastingRegel.run_id == run_id)))
        bestaande_boekingen = {
            b.mapping_id
            for b in session.scalars(
                select(DoorbelastingBoeking).where(
                    DoorbelastingBoeking.document_id == run.document_id,
                    DoorbelastingBoeking.status != DoorbelastingBoekingStatus.GESTORNEERD.value,
                )
            )
        }
        btw_pct = _btw_percentage(session, administratie_id=administratie_id, taxrate_id=instelling.btw_taxrate_id)
        leverancier = _leverancier_naam(session, administratie_id=administratie_id, vendor_id=voorstel.vendor_id)
        bron_referentie = voorstel.referentie or document.bestandsnaam
        opslag_pad = document.opslag_pad
        bestandsnaam = document.bestandsnaam
        instelling_snapshot = {
            "provisie_pct": instelling.provisie_percentage,
            "btw_taxrate_id": instelling.btw_taxrate_id,
            "omzet_ledger_id": instelling.omzet_ledger_id,
            "provisie_omzet_ledger_id": instelling.provisie_omzet_ledger_id or instelling.omzet_ledger_id,
        }
        te_boeken = sorted({r.mapping_id for r in regels} - bestaande_boekingen, key=str)
        bron_administratie_naam = administratie.naam

        # volumerem: eigen telling (elke doelentiteit = één tweezijdige boeking)
        limiet = settings.max_boekingen_per_dag_per_administratie
        if _eigen_boekingen_vandaag(session, administratie_id=administratie_id) + len(te_boeken) > limiet:
            raise VolumeremBereikt(
                f"Dagelijkse limiet van {limiet} doorbelastings-boekingen zou overschreden worden"
            )

    if not te_boeken:
        raise DoorbelastingFout("Alle doelentiteiten zijn al geboekt voor dit document")

    # scope- en toggle-poort per DOEL-administratie, vóór de eerste write (opdracht 1e)
    for mapping_id in te_boeken:
        mapping = mappings[mapping_id]
        if mapping.doel_administratie_id is None:
            continue
        if not actor_heeft_scope(actor_id=actor_id, administratie_id=mapping.doel_administratie_id):
            raise DoorbelastingFout(
                f"Geen scope op doel-administratie van {mapping.doelentiteit_naam} — doorbelasten geweigerd"
            )
        with scoped_session(mapping.doel_administratie_id) as doel_sessie:
            if not _is_boeken_toegestaan(doel_sessie, administratie_id=mapping.doel_administratie_id):
                raise BoekenUitgeschakeld(
                    f"Boeken staat uit voor doel-administratie {mapping.doelentiteit_naam}"
                )

    bestand = _standaard_opslag().lezen(pad=opslag_pad)
    datum_iso = f"{datetime.now(UTC).date().isoformat()}T00:00:00"

    eigen_bron_client = bron_client is None
    if bron_client is None:
        bron_client = _rlz_client_voor(administratie_id)
    eigen_doel_clients = doel_client_factory is None
    if doel_client_factory is None:
        doel_client_factory = _rlz_client_voor

    resultaat: dict[str, str] = {}
    doel_clients: dict[uuid.UUID, RlzClient] = {}
    try:
        _rechten_probe(bron_client, label="bron-administratie")
        # rechten-probe voor elk onboarded doel vóór de eerste write
        for mapping_id in te_boeken:
            mapping = mappings[mapping_id]
            if mapping.doel_administratie_id is not None:
                client = doel_client_factory(mapping.doel_administratie_id)
                _rechten_probe(client, label=f"doel-administratie {mapping.doelentiteit_naam}")
                doel_clients[mapping_id] = client

        for mapping_id in te_boeken:
            mapping = mappings[mapping_id]
            mijn_regels = [r for r in regels if r.mapping_id == mapping_id]
            try:
                status = _boek_voor_doelentiteit(
                    administratie_id=administratie_id,
                    run_id=run_id,
                    actor_id=actor_id,
                    bron_client=bron_client,
                    doel_client=doel_clients.get(mapping_id),
                    mapping=mapping,
                    regels=mijn_regels,
                    bron_regels=bron_regels,
                    document_id=document.id,
                    bron_referentie=bron_referentie,
                    leverancier=leverancier,
                    bron_administratie_naam=bron_administratie_naam,
                    instelling=instelling_snapshot,
                    btw_pct=btw_pct,
                    bestand=bestand,
                    bestandsnaam=bestandsnaam,
                    datum_iso=datum_iso,
                )
                resultaat[str(mapping_id)] = status
            except DoorbelastingHalfGeboekt:
                resultaat[str(mapping_id)] = DoorbelastingBoekingStatus.HALF_GEBOEKT.value
            except (DoorbelastingFout, RlzApiError) as exc:
                logger.warning("Doorbelasting doelentiteit %s mislukt: %s", mapping.doelentiteit_naam, exc)
                _registreer_fout(run_id, administratie_id, mapping_id, str(exc))
                resultaat[str(mapping_id)] = "mislukt"
    finally:
        if eigen_bron_client:
            bron_client.close()
        if eigen_doel_clients:
            # verbindings-lek-fix (testbevinding 2026-08-13): zelf-geopende doel-clients ook
            # sluiten — geïnjecteerde factories beheren hun eigen levensduur
            for doel_client in doel_clients.values():
                doel_client.close()

    # run-status bijwerken: GEBOEKT zodra élke doelentiteit een áfgeronde boeking heeft
    # (geboekt of bewuste open spiegel-taak). Een half_geboekt-rij houdt de run bewust op
    # concept: er staat menselijk herstelwerk open (reconciliatie-signaal) — de rij zelf
    # blokkeert intussen via de duplicaatbewaking elke nieuwe boekpoging over de halve heen.
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        run = session.get(DoorbelastingRun, run_id)
        afgeronde_mappings = {
            b.mapping_id
            for b in session.scalars(
                select(DoorbelastingBoeking).where(
                    DoorbelastingBoeking.document_id == run.document_id,
                    DoorbelastingBoeking.status.in_(
                        (
                            DoorbelastingBoekingStatus.GEBOEKT.value,
                            DoorbelastingBoekingStatus.SPIEGEL_OPEN.value,
                        )
                    ),
                )
            )
        }
        if {r.mapping_id for r in regels} <= afgeronde_mappings:
            run.status = DoorbelastingRunStatus.GEBOEKT.value
            run.geboekt_op = datetime.now(UTC)
    return resultaat


def _boek_voor_doelentiteit(
    *,
    administratie_id: uuid.UUID,
    run_id: uuid.UUID,
    actor_id: uuid.UUID,
    bron_client: RlzClient,
    doel_client: RlzClient | None,
    mapping: DoorbelastingMapping,
    regels: list[DoorbelastingRegel],
    bron_regels: dict[uuid.UUID, BoekvoorstelRegel],
    document_id: uuid.UUID,
    bron_referentie: str,
    leverancier: str | None,
    bron_administratie_naam: str,
    instelling: dict,
    btw_pct: Decimal,
    bestand: bytes,
    bestandsnaam: str,
    datum_iso: str,
) -> str:
    verkoop_rlz_id = rlz_doorbelasting_verkoop_id(document_id, mapping.doel_customer_guid)
    spiegel_rlz_id = rlz_doorbelasting_spiegel_id(document_id, mapping.doel_customer_guid)

    netto_totaal = sum((r.netto_deel for r in regels), Decimal(0))
    provisie = provisie_over(netto_totaal, instelling["provisie_pct"])

    # --- kant 1: verkoop in de bron (Kempen-patroon: bron-referentie in de regelomschrijving,
    # --- provisie als losse laatste regel — §2a, spiegel bevestigd §2c)
    omschrijving_basis = " ".join(x for x in (leverancier, bron_referentie) if x)
    verkoop_lines: list[dict] = []
    btw_totaal = Decimal(0)
    for r in regels:
        bron_regel = bron_regels[r.bron_regel_id]
        omschrijving = omschrijving_basis
        if bron_regel.omschrijving:
            omschrijving = f"{omschrijving_basis} — {bron_regel.omschrijving}"[:200]
        btw = btw_over(r.netto_deel, btw_pct)
        btw_totaal += btw
        verkoop_lines.append(
            {
                "Account": {"id": str(instelling["omzet_ledger_id"])},
                "TaxRate": {"id": str(instelling["btw_taxrate_id"])},
                "NetAmount": float(r.netto_deel),
                "TaxAmount": float(btw),
                "Description": omschrijving,
            }
        )
    provisie_btw = btw_over(provisie, btw_pct)
    btw_totaal += provisie_btw
    provisie_pct_tekst = f"{instelling['provisie_pct']:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    verkoop_lines.append(
        {
            "Account": {"id": str(instelling["provisie_omzet_ledger_id"])},
            "TaxRate": {"id": str(instelling["btw_taxrate_id"])},
            "NetAmount": float(provisie),
            "TaxAmount": float(provisie_btw),
            "Description": f"Provisie {provisie_pct_tekst}% over nettobedrag",
        }
    )

    invoice_number, verkoop_referentie, _ = _boek_verkoopfactuur(
        client=bron_client,
        rlz_id=verkoop_rlz_id,
        customer_id=mapping.doel_customer_guid,
        lines=verkoop_lines,
        datum_iso=datum_iso,
        upload_id=rlz_doorbelasting_upload_id(document_id, mapping.doel_customer_guid, kant="verkoop"),
        bestandsnaam=bestandsnaam,
        bestand=bestand,
        lokaal_max_invoice_number=_lokaal_max_doorbelasting_invoice_number(administratie_id),
    )

    def _leg_boeking_vast(
        status: DoorbelastingBoekingStatus,
        *,
        half_detail: dict | None = None,
        webhook_payload: dict | None = None,
    ) -> None:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            boeking = DoorbelastingBoeking(
                run_id=run_id,
                administratie_id=administratie_id,
                document_id=document_id,
                mapping_id=mapping.id,
                doel_administratie_id=mapping.doel_administratie_id,
                status=status.value,
                netto_totaal=netto_totaal,
                provisie_bedrag=provisie,
                btw_bedrag=btw_totaal,
                verkoop_rlz_id=verkoop_rlz_id,
                verkoop_referentie=verkoop_referentie,
                verkoop_invoice_number=invoice_number,
                spiegel_rlz_id=spiegel_rlz_id,
                spiegel_geboekt_op=datetime.now(UTC) if status == DoorbelastingBoekingStatus.GEBOEKT else None,
                half_geboekt_detail=half_detail,
                geboekt_door=actor_id,
            )
            session.add(boeking)
            if webhook_payload is not None:
                # Outbox in dezelfde transactie als de boeking (patroon documenten/boeken.py):
                # document_id = het bron-document (FK + traceerbaarheid), administratie_id =
                # de doel-administratie — de afleveraar levert 'm dáár af (migratie 0046).
                session.add(
                    WebhookUitgaand(
                        document_id=document_id,
                        administratie_id=mapping.doel_administratie_id,
                        event=webhook_payload["event"],
                        payload=webhook_payload,
                    )
                )
            run = session.get(DoorbelastingRun, run_id)
            _wis_fout(session, run, mapping.id)
            # geheugen-v1: onthoud de laatst gebruikte doel-kosten-GB als voorstel
            mapping_rij = session.get(DoorbelastingMapping, mapping.id)
            laatste_gb = next((r.doel_kosten_ledger_id for r in regels if r.doel_kosten_ledger_id), None)
            if mapping_rij is not None and laatste_gb is not None:
                mapping_rij.laatste_kosten_ledger_id = laatste_gb
            document = session.get(Document, document_id)
            _tijdlijn(
                session,
                document=document,
                actor_id=actor_id,
                detail={
                    "gebeurtenis": "doorbelast",
                    "doelentiteit": mapping.doelentiteit_naam,
                    "status": status.value,
                    "verkoop_referentie": verkoop_referentie,
                    "netto": str(netto_totaal),
                    "provisie": str(provisie),
                },
            )
            record_audit_event(
                session,
                actor_id=actor_id,
                module=_MODULE,
                tabel="doorbelasting_boeking",
                record_id=boeking.id,
                actie=f"doorbelasting_{status.value}",
                correlatie_id=document_id,
                nieuwe_waarde={
                    "doelentiteit": mapping.doelentiteit_naam,
                    "verkoop_rlz_id": str(verkoop_rlz_id),
                    "spiegel_rlz_id": str(spiegel_rlz_id),
                    "netto": str(netto_totaal),
                    "provisie": str(provisie),
                    **({"half_detail": half_detail} if half_detail else {}),
                },
                administratie_id=administratie_id,
            )

    # --- kant 2: spiegel in de doel-administratie (of open taak) --------------------------
    if doel_client is None or mapping.doel_administratie_id is None:
        _leg_boeking_vast(DoorbelastingBoekingStatus.SPIEGEL_OPEN)
        return DoorbelastingBoekingStatus.SPIEGEL_OPEN.value

    try:
        vendor_id = _zorg_voor_crediteur_in_doel(
            client=doel_client,
            doel_administratie_id=mapping.doel_administratie_id,
            naam=bron_administratie_naam,
        )
        # doel-kant IC-rij (blok 2): nu de crediteur-GUID bekend is, geldt de bron-administratie
        # in de doel-administratie als intercompany-tegenpartij (RC, nooit afletteren)
        if mapping.intercompany:
            with scoped_session(mapping.doel_administratie_id) as doel_sessie:
                upsert_intercompany_tegenpartij(
                    doel_sessie,
                    administratie_id=mapping.doel_administratie_id,
                    entity_guid=vendor_id,
                    naam=bron_administratie_naam,
                    mapping_id=mapping.id,
                    actief=True,
                )
        spiegel_spec = _spiegel_regelspec(
            regels=regels,
            bron_regels=bron_regels,
            omschrijving_basis=omschrijving_basis,
            btw_pct=btw_pct,
            provisie=provisie,
            provisie_btw=provisie_btw,
            provisie_kosten_ledger_id=mapping.provisie_kosten_ledger_id,
            provisie_omschrijving=f"Provisie {provisie_pct_tekst}% over nettobedrag",
        )
        spiegel_boekstuknummer = _boek_spiegel_inkoop(
            client=doel_client,
            rlz_id=spiegel_rlz_id,
            vendor_id=vendor_id,
            lines=_spiegel_lines_van_spec(spiegel_spec, btw_taxrate_id=instelling["btw_taxrate_id"]),
            referentie=verkoop_referentie or f"DOORB-{invoice_number}",
            datum_iso=datum_iso,
            upload_id=rlz_doorbelasting_upload_id(document_id, mapping.doel_customer_guid, kant="spiegel"),
            bestandsnaam=bestandsnaam,
            bestand=bestand,
        )
    except (RlzApiError, DoorbelastingFout) as spiegel_fout:
        # spiegel gefaald → storno van de bron-verkoop (omzetmotor-patroon)
        try:
            bron_client.correct_sales_invoice(verkoop_rlz_id)
        except RlzApiError as storno_fout:
            detail = {
                "spiegel_fout": str(spiegel_fout)[:500],
                "storno_verkoop_fout": str(storno_fout)[:500],
                "herstel": "storno verkoopfactuur handmatig in RLZ (actie 19) of retry na oorzaak-fix",
            }
            _leg_boeking_vast(DoorbelastingBoekingStatus.HALF_GEBOEKT, half_detail=detail)
            raise DoorbelastingHalfGeboekt(
                "Spiegel-inkoopfactuur mislukt én storno van de verkoopfactuur mislukt — zichtbaar "
                "geregistreerd als half_geboekt"
            ) from spiegel_fout
        _registreer_fout(run_id, administratie_id, mapping.id, f"spiegel mislukt, verkoop gestorneerd: {spiegel_fout}")
        raise DeelboekingMislukt(
            f"Spiegel-inkoopfactuur mislukt ({spiegel_fout}); de verkoopfactuur is gestorneerd — niets half"
        ) from spiegel_fout

    # Spiegel-webhook (besluit Peter 2026-08-14): een vastgoed-doel-administratie krijgt óók
    # het `factuur_geboekt`-event — payload buiten de boeking-transactie opgebouwd (eigen
    # doel-scope-reads), de outbox-rij erbinnen (zelfde atomaire outbox-garantie als inkoop).
    webhook_payload = _bouw_spiegel_webhook_payload(
        bron_document_id=document_id,
        doel_administratie_id=mapping.doel_administratie_id,
        vendor_id=vendor_id,
        leverancier_naam=bron_administratie_naam,
        spiegel_rlz_id=spiegel_rlz_id,
        spiegel_boekstuknummer=spiegel_boekstuknummer,
        referentie=verkoop_referentie or f"DOORB-{invoice_number}",
        factuurdatum=date.fromisoformat(datum_iso[:10]),
        regelspec=spiegel_spec,
    )
    _leg_boeking_vast(DoorbelastingBoekingStatus.GEBOEKT, webhook_payload=webhook_payload)
    return DoorbelastingBoekingStatus.GEBOEKT.value


def _lokaal_max_doorbelasting_invoice_number(administratie_id: uuid.UUID) -> int:
    """Lokaal deel van het verkoopnummer-herstel, over álle eigen SalesInvoice-nummers van deze
    administratie: doorbelasting + verkoop + omzet (zie ook de spiegel-uitbreiding in
    app/verkoop/boeken.py::_lokaal_max_verkoop_invoice_number)."""
    from app.verkoop.boeken import _lokaal_max_verkoop_invoice_number

    with scoped_session(administratie_id) as session:
        eigen_max = session.scalar(
            select(DoorbelastingBoeking.verkoop_invoice_number)
            .where(
                DoorbelastingBoeking.administratie_id == administratie_id,
                DoorbelastingBoeking.verkoop_invoice_number.isnot(None),
            )
            .order_by(DoorbelastingBoeking.verkoop_invoice_number.desc())
            .limit(1)
        )
    return max(eigen_max or 0, _lokaal_max_verkoop_invoice_number(administratie_id))


def boek_spiegel_alsnog(
    *,
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    actor_id: uuid.UUID,
    doel_client: RlzClient | None = None,
) -> DoorbelastingBoeking:
    """De open taak "spiegel boeken in <entiteit>" afronden nadat de doel-administratie
    onboarded is: alleen de doel-kant; de bron-verkoop staat al. Zelfde poorten als de motor
    (scope, toggle, rechten-probe) en dezelfde deterministische spiegel-GUID."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        boeking = session.get(DoorbelastingBoeking, boeking_id)
        if boeking is None or boeking.administratie_id != administratie_id:
            raise DoorbelastingFout("Onbekende doorbelastings-boeking")
        if boeking.status != DoorbelastingBoekingStatus.SPIEGEL_OPEN.value:
            raise DoorbelastingFout("Deze boeking heeft geen open spiegel-taak")
        mapping = session.get(DoorbelastingMapping, boeking.mapping_id)
        if mapping is None or mapping.doel_administratie_id is None:
            raise DoorbelastingFout(
                "Doel-administratie is nog niet gekoppeld op de mapping — onboarden en koppelen eerst"
            )
        regels = list(
            session.scalars(
                select(DoorbelastingRegel).where(
                    DoorbelastingRegel.run_id == boeking.run_id,
                    DoorbelastingRegel.mapping_id == boeking.mapping_id,
                )
            )
        )
        if any(r.doel_kosten_ledger_id is None for r in regels) or mapping.provisie_kosten_ledger_id is None:
            raise DoorbelastingFout("Doel-kosten-GB per regel en provisie-GB moeten eerst gekozen zijn")
        document = session.get(Document, boeking.document_id)
        voorstel = session.get(Boekvoorstel, boeking.document_id)
        bron_regels = {
            r.id: r
            for r in session.scalars(
                select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == boeking.document_id)
            )
        }
        from app.doorbelasting.models import DoorbelastingInstelling

        instelling = session.get(DoorbelastingInstelling, administratie_id)
        if instelling is None or instelling.btw_taxrate_id is None:
            raise DoorbelastingFout("Doorbelasting-instellingen incompleet")
        btw_pct = _btw_percentage(session, administratie_id=administratie_id, taxrate_id=instelling.btw_taxrate_id)
        leverancier = _leverancier_naam(session, administratie_id=administratie_id, vendor_id=voorstel.vendor_id)
        bron_referentie = voorstel.referentie or document.bestandsnaam
        opslag_pad, bestandsnaam = document.opslag_pad, document.bestandsnaam
        doel_administratie_id = mapping.doel_administratie_id
        doelentiteit_naam = mapping.doelentiteit_naam
        provisie_kosten_ledger_id = mapping.provisie_kosten_ledger_id
        doel_customer_guid = mapping.doel_customer_guid
        mapping_intercompany = mapping.intercompany
        mapping_id_snapshot = mapping.id
        btw_taxrate_id = instelling.btw_taxrate_id
        administratie = session.get(Administratie, administratie_id)
        bron_administratie_naam = administratie.naam

    if not actor_heeft_scope(actor_id=actor_id, administratie_id=doel_administratie_id):
        raise DoorbelastingFout(f"Geen scope op doel-administratie van {doelentiteit_naam}")
    with scoped_session(doel_administratie_id) as doel_sessie:
        if not _is_boeken_toegestaan(doel_sessie, administratie_id=doel_administratie_id):
            raise BoekenUitgeschakeld(f"Boeken staat uit voor doel-administratie {doelentiteit_naam}")

    eigen_client = doel_client is None
    if doel_client is None:
        doel_client = _rlz_client_voor(doel_administratie_id)
    try:
        _rechten_probe(doel_client, label=f"doel-administratie {doelentiteit_naam}")
        vendor_id = _zorg_voor_crediteur_in_doel(
            client=doel_client, doel_administratie_id=doel_administratie_id, naam=bron_administratie_naam
        )
        if mapping_intercompany:
            with scoped_session(doel_administratie_id) as doel_sessie:
                upsert_intercompany_tegenpartij(
                    doel_sessie,
                    administratie_id=doel_administratie_id,
                    entity_guid=vendor_id,
                    naam=bron_administratie_naam,
                    mapping_id=mapping_id_snapshot,
                    actief=True,
                )
        omschrijving_basis = " ".join(x for x in (leverancier, bron_referentie) if x)
        spiegel_spec = _spiegel_regelspec(
            regels=regels,
            bron_regels=bron_regels,
            omschrijving_basis=omschrijving_basis,
            btw_pct=btw_pct,
            provisie=boeking.provisie_bedrag,
            provisie_btw=btw_over(boeking.provisie_bedrag, btw_pct),
            provisie_kosten_ledger_id=provisie_kosten_ledger_id,
            provisie_omschrijving="Provisie over nettobedrag (doorbelasting)",
        )
        bestand = _standaard_opslag().lezen(pad=opslag_pad)
        boekdatum = datetime.now(UTC).date()
        spiegel_boekstuknummer = _boek_spiegel_inkoop(
            client=doel_client,
            rlz_id=boeking.spiegel_rlz_id,
            vendor_id=vendor_id,
            lines=_spiegel_lines_van_spec(spiegel_spec, btw_taxrate_id=btw_taxrate_id),
            referentie=boeking.verkoop_referentie or f"DOORB-{boeking.verkoop_invoice_number}",
            datum_iso=f"{boekdatum.isoformat()}T00:00:00",
            upload_id=rlz_doorbelasting_upload_id(boeking.document_id, doel_customer_guid, kant="spiegel"),
            bestandsnaam=bestandsnaam,
            bestand=bestand,
        )
    finally:
        if eigen_client:
            doel_client.close()

    # Spiegel-webhook, zelfde regel als de motor (besluit Peter 2026-08-14): het alsnog-boeken
    # van een open spiegel-taak in een vastgoed-doel-administratie meldt zich óók bij vastgoed.
    webhook_payload = _bouw_spiegel_webhook_payload(
        bron_document_id=boeking.document_id,
        doel_administratie_id=doel_administratie_id,
        vendor_id=vendor_id,
        leverancier_naam=bron_administratie_naam,
        spiegel_rlz_id=boeking.spiegel_rlz_id,
        spiegel_boekstuknummer=spiegel_boekstuknummer,
        referentie=boeking.verkoop_referentie or f"DOORB-{boeking.verkoop_invoice_number}",
        factuurdatum=boekdatum,
        regelspec=spiegel_spec,
    )

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        boeking = session.get(DoorbelastingBoeking, boeking_id)
        boeking.status = DoorbelastingBoekingStatus.GEBOEKT.value
        boeking.doel_administratie_id = doel_administratie_id
        boeking.spiegel_geboekt_op = datetime.now(UTC)
        if webhook_payload is not None:
            session.add(
                WebhookUitgaand(
                    document_id=boeking.document_id,
                    administratie_id=doel_administratie_id,
                    event=webhook_payload["event"],
                    payload=webhook_payload,
                )
            )
        document = session.get(Document, boeking.document_id)
        _tijdlijn(
            session,
            document=document,
            actor_id=actor_id,
            detail={
                "gebeurtenis": "doorbelasting_spiegel_geboekt",
                "doelentiteit": doelentiteit_naam,
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="doorbelasting_boeking",
            record_id=boeking.id,
            actie="doorbelasting_spiegel_alsnog_geboekt",
            correlatie_id=boeking.document_id,
            oude_waarde={"status": DoorbelastingBoekingStatus.SPIEGEL_OPEN.value},
            nieuwe_waarde={"status": DoorbelastingBoekingStatus.GEBOEKT.value},
            administratie_id=administratie_id,
        )
        session.flush()
        session.expunge(boeking)
        return boeking


def _meld_spiegel_gestorneerd(
    session,
    *,
    document_id: uuid.UUID,
    doel_administratie_id: uuid.UUID | None,
    spiegel_rlz_id: uuid.UUID,
    reden: str,
) -> None:
    """`factuur_gestorneerd` voor de spiegel-kant (koppelcontract §3 v1.14, kostenflow-randvraag
    c): alleen als de spiegel eerder een factuur_geboekt-event kreeg (vastgoed-doel) én de
    laatste boekstand geboekt is — anders valt er bij vastgoed niets te corrigeren. De
    kop-velden (rlz_admin_id, boekstuknummer, referentie) komen uit die laatste geboekt-stand:
    exact wat de ontvanger kent. Bron-scope ziet de spiegel-rijen via de document-clausule van
    de RLS (migratie 0046); de nieuwe rij passeert de WITH CHECK via dezelfde clausule."""
    if doel_administratie_id is None:
        return
    rij = laatste_boekstand_rij(session, document_id=document_id, rlz_document_id=spiegel_rlz_id)
    if rij is None or rij.event != FACTUUR_GEBOEKT_EVENT:
        return
    data = (rij.payload or {}).get("data") or {}
    payload = bouw_factuur_gestorneerd_payload(
        administratie_id=doel_administratie_id,
        rlz_admin_id=data.get("rlz_admin_id") or "",
        rlz_document_id=spiegel_rlz_id,
        rlz_boekstuknummer=data.get("rlz_boekstuknummer"),
        referentie=data.get("referentie"),
        volgnummer=stand_van_rij(rij) + 1,
        bron=GESTORNEERD_BRON_MODULE,
        reden=reden,
        gestorneerd_op=datetime.now(UTC),
    )
    session.add(
        WebhookUitgaand(
            document_id=document_id,
            administratie_id=doel_administratie_id,
            event=payload["event"],
            payload=payload,
        )
    )


def storno_doorbelasting_boeking(
    *,
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    actor_id: uuid.UUID,
    reden: str,
    bron_client: RlzClient | None = None,
    doel_client: RlzClient | None = None,
) -> DoorbelastingBoeking:
    """Storno beide kanten (actie 19, opdracht 1d), verplichte reden (DB-CHECK 0044). Vaste
    volgorde: spiegel eerst, dan de bron-verkoop — mislukt de bron-storno daarna, dan blijft
    de boeking staan mét zichtbare fout (niets verdwijnt stil)."""
    if not reden or len(reden.strip()) < 5:
        raise DoorbelastingFout("Storneren vereist een reden (minimaal 5 tekens)")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        boeking = session.get(DoorbelastingBoeking, boeking_id)
        if boeking is None or boeking.administratie_id != administratie_id:
            raise DoorbelastingFout("Onbekende doorbelastings-boeking")
        if boeking.status == DoorbelastingBoekingStatus.GESTORNEERD.value:
            raise DoorbelastingFout("Deze boeking is al gestorneerd")
        mapping = session.get(DoorbelastingMapping, boeking.mapping_id)
        doelentiteit_naam = mapping.doelentiteit_naam if mapping else "?"
        oude_status = boeking.status
        doel_administratie_id = boeking.doel_administratie_id
        verkoop_rlz_id, spiegel_rlz_id = boeking.verkoop_rlz_id, boeking.spiegel_rlz_id

    spiegel_geboekt = (
        oude_status == DoorbelastingBoekingStatus.GEBOEKT.value and doel_administratie_id is not None
    )
    eigen_doel = doel_client is None
    eigen_bron = bron_client is None
    if spiegel_geboekt and doel_client is None:
        doel_client = _rlz_client_voor(doel_administratie_id)
    if bron_client is None:
        bron_client = _rlz_client_voor(administratie_id)
    try:
        # Aangifte-poort (besluit Peter 2026-08-15): BEIDE kanten toetsen vóór de eerste
        # RLZ-write — alles-of-niets: valt de bron-verkoop óf de doel-spiegel in een
        # ingediende btw-aangifte, dan gaat er aan géén van beide kanten iets terug (per
        # kant zichtbaar waarom). Fail-closed bij onleesbare aangifte-status.
        toetsen = [
            AangiftePoort(bron_client).toets_document(
                lambda: bron_client.get(f"SalesInvoices/{verkoop_rlz_id}"),
                kant="verkoopfactuur (bron-administratie)",
            )
        ]
        if spiegel_geboekt:
            toetsen.append(
                AangiftePoort(doel_client).toets_document(
                    lambda: doel_client.get(f"PurchaseInvoices/{spiegel_rlz_id}"),
                    kant=f"spiegel-inkoopfactuur ({doelentiteit_naam})",
                )
            )
        blokkeer_bij_ingediende_aangifte(toetsen)

        # spiegel eerst (alleen als die kant geboekt is)
        if spiegel_geboekt:
            try:
                doel_client.correct_purchase_invoice(spiegel_rlz_id)
            except RlzApiError as exc:
                if exc.status_code != 404:
                    raise DoorbelastingFout(
                        f"Storno spiegel-inkoopfactuur bij {doelentiteit_naam} faalde ({exc.status_code}) — "
                        "boeking blijft staan, niets half teruggedraaid"
                    ) from exc
        try:
            bron_client.correct_sales_invoice(verkoop_rlz_id)
        except RlzApiError as exc:
            if exc.status_code != 404:
                raise DoorbelastingFout(
                    f"Storno verkoopfactuur faalde ({exc.status_code}) — LET OP: de spiegel is al "
                    "teruggedraaid; herstel de verkoop-kant en probeer opnieuw"
                ) from exc
    finally:
        if eigen_doel and doel_client is not None:
            doel_client.close()
        if eigen_bron:
            bron_client.close()

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        boeking = session.get(DoorbelastingBoeking, boeking_id)
        boeking.status = DoorbelastingBoekingStatus.GESTORNEERD.value
        boeking.storno_reden = reden.strip()
        # Storno-event naar vastgoed (v1.14, randvraag c) — in dezelfde transactie als de
        # statuswijziging: geen storno zonder melding, geen melding zonder storno.
        _meld_spiegel_gestorneerd(
            session,
            document_id=boeking.document_id,
            doel_administratie_id=doel_administratie_id,
            spiegel_rlz_id=spiegel_rlz_id,
            reden=reden.strip(),
        )
        run = session.get(DoorbelastingRun, boeking.run_id)
        nog_actief = session.scalar(
            select(func.count())
            .select_from(DoorbelastingBoeking)
            .where(
                DoorbelastingBoeking.run_id == boeking.run_id,
                DoorbelastingBoeking.status != DoorbelastingBoekingStatus.GESTORNEERD.value,
            )
        )
        if nog_actief == 0 and run.status == DoorbelastingRunStatus.GEBOEKT.value:
            run.status = DoorbelastingRunStatus.GESTORNEERD.value
        document = session.get(Document, boeking.document_id)
        _tijdlijn(
            session,
            document=document,
            actor_id=actor_id,
            detail={
                "gebeurtenis": "doorbelasting_gestorneerd",
                "doelentiteit": doelentiteit_naam,
                "reden": reden.strip(),
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="doorbelasting_boeking",
            record_id=boeking.id,
            actie="doorbelasting_gestorneerd",
            correlatie_id=boeking.document_id,
            oude_waarde={"status": oude_status},
            nieuwe_waarde={"status": boeking.status, "reden": reden.strip()},
            administratie_id=administratie_id,
        )
        session.flush()
        session.expunge(boeking)
        return boeking


def storno_toets_voor_document(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    bron_client: RlzClient | None = None,
    doel_client_factory: Callable[[uuid.UUID], RlzClient] | None = None,
) -> dict[uuid.UUID, list[KantToets]]:
    """Aangifte-poort als LEESROUTE voor de UI (opdracht: de storno-knop is uitgeschakeld
    mét melding — geen klikbare knop die pas server-side faalt): per niet-gestorneerde
    boeking van dit document exact dezelfde toetsen die storno_doorbelasting_boeking straks
    hard afdwingt. Fail-closed: elke fout (credentials, onleesbaar document of onleesbare
    aangifte-status) wordt een geblokkeerde kant — nooit een 500 op het detailscherm.
    TaxDeclarations wordt per administratie éénmaal gelezen (poort-cache)."""
    with scoped_session(administratie_id) as session:
        boekingen = list(
            session.scalars(
                select(DoorbelastingBoeking).where(
                    DoorbelastingBoeking.document_id == document_id,
                    DoorbelastingBoeking.administratie_id == administratie_id,
                    DoorbelastingBoeking.status != DoorbelastingBoekingStatus.GESTORNEERD.value,
                )
            )
        )
        namen = {
            m.id: m.doelentiteit_naam
            for m in session.scalars(
                select(DoorbelastingMapping).where(DoorbelastingMapping.administratie_id == administratie_id)
            )
        }
        snapshot = [
            (b.id, b.status, b.doel_administratie_id, b.verkoop_rlz_id, b.spiegel_rlz_id, namen.get(b.mapping_id, "?"))
            for b in boekingen
        ]
    if not snapshot:
        return {}

    eigen_bron = bron_client is None
    if bron_client is None:
        bron_client = _rlz_client_voor(administratie_id)
    eigen_doel_clients = doel_client_factory is None
    if doel_client_factory is None:
        doel_client_factory = _rlz_client_voor

    resultaat: dict[uuid.UUID, list[KantToets]] = {}
    bron_poort = AangiftePoort(bron_client)
    doel_clients: dict[uuid.UUID, RlzClient] = {}
    doel_poorten: dict[uuid.UUID, AangiftePoort | None] = {}  # None = credentials-fout (fail-closed)
    try:
        for boeking_id, status, doel_administratie_id, verkoop_rlz_id, spiegel_rlz_id, naam in snapshot:
            toetsen = [
                bron_poort.toets_document(
                    lambda v=verkoop_rlz_id: bron_client.get(f"SalesInvoices/{v}"),
                    kant="verkoopfactuur (bron-administratie)",
                )
            ]
            if status == DoorbelastingBoekingStatus.GEBOEKT.value and doel_administratie_id is not None:
                kant = f"spiegel-inkoopfactuur ({naam})"
                if doel_administratie_id not in doel_poorten:
                    try:
                        client = doel_client_factory(doel_administratie_id)
                        doel_clients[doel_administratie_id] = client
                        doel_poorten[doel_administratie_id] = AangiftePoort(client)
                    except GeenRlzCredentials:
                        doel_poorten[doel_administratie_id] = None
                poort = doel_poorten[doel_administratie_id]
                if poort is None:
                    toetsen.append(
                        KantToets(
                            kant=kant,
                            toegestaan=False,
                            reden="geen RLZ-credentials voor de doel-administratie — storno uit voorzorg geblokkeerd",
                        )
                    )
                else:
                    doel_client = doel_clients[doel_administratie_id]
                    toetsen.append(
                        poort.toets_document(
                            lambda s=spiegel_rlz_id, c=doel_client: c.get(f"PurchaseInvoices/{s}"),
                            kant=kant,
                        )
                    )
            resultaat[boeking_id] = toetsen
    finally:
        if eigen_bron:
            bron_client.close()
        if eigen_doel_clients:
            for client in doel_clients.values():
                client.close()
    return resultaat
