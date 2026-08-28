"""Fixtures + FakeDoorbelastingClient voor de doorbelastings-motor- en servicetests.

Patroon conform tests/omzet/conftest.py (duck-typed fake, geen echte HTTP) en
tests/verkoop (client-injectie via de test-seams `bron_client`/`doel_client_factory`).
De fake bootst het geverifieerde RLZ-gedrag na: SalesInvoice-PUT kent auto-InvoiceNumbers
toe, GET-op-eigen-GUID geeft 404 vóór de eerste PUT (retry-inhaal), actie 19 zet Status
terug naar 1, en de Vendors-collectie is op naam filterbaar (STAP-0 2026-08-13)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select, text

from app.auth import service as auth_service
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import (
    Boekvoorstel,
    BoekvoorstelRegel,
    Document,
    DocumentSoort,
    DocumentStatus,
)
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.doorbelasting import service as doorbelasting_service
from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingMapping, DoorbelastingRun
from app.doorbelasting.service import VerdeelRegelInvoerData
from app.rlz.client import RlzApiError
from app.sync.models import TaxRateCache
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

# Vaste test-GUID's (zelfde stijl als tests/verkoop/conftest.py).
BTW_TAXRATE_ID = uuid.UUID("22222222-2222-2222-2222-222222222221")
OMZET_LEDGER_ID = uuid.UUID("11111111-1111-1111-1111-111111111101")
DOEL_KOSTEN_LEDGER_ID = uuid.UUID("11111111-1111-1111-1111-111111111102")
PROVISIE_KOSTEN_LEDGER_ID = uuid.UUID("11111111-1111-1111-1111-111111111103")


# --- administraties -----------------------------------------------------------------------


@pytest.fixture
def doorbelasting_aan(administratie_id: uuid.UUID, admin_engine: Engine) -> None:  # noqa: F811
    """Bron-administratie boekbaar én doorbelasting-enabled (de BoekenInstelling-singleton
    staat globaal aan via tests/conftest.py::_clean_tables)."""
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE platform.administratie "
                "SET doorbelasting_ingeschakeld = true, boeken_ingeschakeld = true WHERE id = :id"
            ),
            {"id": administratie_id},
        )


def maak_administratie(admin_engine: Engine, naam: str, *, boeken: bool = True) -> uuid.UUID:
    """Tweede platform.administratie-rij (doel-kant) — boeken default aan, want de motor
    draait de toggle-poort óók voor de doel-administratie."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, boeken_ingeschakeld) "
                "VALUES (:id, :naam, :rlz, :boeken)"
            ),
            {"id": aid, "naam": naam, "rlz": f"rlz-{aid}", "boeken": boeken},
        )
    return aid


@pytest.fixture
def doel_administratie_id(admin_engine: Engine) -> uuid.UUID:
    return maak_administratie(admin_engine, "Veldhoven Recreatie B.V.")


def geef_scope(*, beheerder_id: uuid.UUID, gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> None:  # noqa: F811
    """Scope-rij via de servicelaag (audit-trigger krijgt een actor) — de RLS-les: doel-scope-
    toetsen altijd óók met een echte niet-Beheerder MÉT scope testen (bugfix 2026-08-25)."""
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=gebruiker_id, administratie_id=administratie_id
    )


# --- instellingen + btw-cache -------------------------------------------------------------


@pytest.fixture
def instelling_compleet(administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> None:  # noqa: F811
    """DoorbelastingInstelling (5%, btw-tarief + omzet-GB) + de bijbehorende TaxRateCache-rij.
    ⚠️ BRONFORMAAT-regel: de cache draagt de FRACTIE (0.2100 = 21%, zoals GET TaxRates levert)."""
    doorbelasting_service.zet_instelling(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        provisie_percentage=Decimal("5.00"),
        btw_taxrate_id=BTW_TAXRATE_ID,
        omzet_ledger_id=OMZET_LEDGER_ID,
        provisie_omzet_ledger_id=None,
    )
    with scoped_session(administratie_id) as session:
        session.add(
            TaxRateCache(
                id=BTW_TAXRATE_ID,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.2100"),
                brondata={
                    "Name": "NL, Hoog Tarief",
                    "Percentage": 0.21,
                    "IsRelayed": False,
                    "IsExcempt": False,
                    "IsMixed": False,
                    "TaxKind": 1,
                },
            )
        )


# --- bron-document (geboekte inkoopfactuur + boekvoorstel) --------------------------------


def maak_geboekt_inkoopfactuur(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,  # noqa: F811
    nettos: list[Decimal],
    referentie: str = "F-2026-0042",
    soort: DocumentSoort = DocumentSoort.INKOOPFACTUUR,
    bestandsnaam: str = "factuur-doorbelasting.pdf",
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Een GEBOEKT bron-document met Boekvoorstel(vendor, referentie) + regel(s) met
    netto_bedrag — de kortste route naar een doorbelastbaar document (pattern
    tests/documenten/test_boekvoorstel.py: overgangen via _schrijf_overgang, nooit losse
    status-writes)."""
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=bestandsnaam,
        inhoud=b"%PDF-1.4 doorbelasting " + referentie.encode(),
        actor_id=actor_id,
        opslag=opslag,
        soort=soort,
    )
    regel_ids: list[uuid.UUID] = []
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, resultaat.document_id)
        assert document is not None
        voorstel = session.get(Boekvoorstel, resultaat.document_id)
        if voorstel is None:
            voorstel = Boekvoorstel(document_id=resultaat.document_id)
            session.add(voorstel)
        voorstel.vendor_id = uuid.uuid4()
        voorstel.referentie = referentie
        # Punt 15 (28-08): de doorbelasting boekt op de factuurdatum van het bron-document.
        voorstel.factuurdatum = date(2026, 7, 1)
        for volgnummer, netto in enumerate(nettos, start=1):
            regel = BoekvoorstelRegel(
                document_id=resultaat.document_id,
                volgnummer=volgnummer,
                netto_bedrag=netto,
                omschrijving=f"Kostenregel {volgnummer}",
            )
            session.add(regel)
            session.flush()
            regel_ids.append(regel.id)
        if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
            _schrijf_overgang(session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=actor_id)
        _schrijf_overgang(session, document=document, naar=DocumentStatus.GEBOEKT, actor_id=actor_id)
    return resultaat.document_id, regel_ids


@pytest.fixture
def geboekt_document(
    gescoopte_gebruiker: uuid.UUID,  # noqa: F811
    administratie_id: uuid.UUID,  # noqa: F811
    opslag: LokaleBestandsopslag,  # noqa: F811
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Eén geboekte inkoopfactuur met één regel van € 100,00 netto."""
    return maak_geboekt_inkoopfactuur(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
        nettos=[Decimal("100.00")],
    )


# --- mapping + run-helpers ----------------------------------------------------------------


def maak_mapping(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    actor_id: uuid.UUID,
    naam: str = "Veldhoven Recreatie B.V.",
    doel_administratie_id: uuid.UUID | None = None,  # noqa: F811
    provisie_kosten_ledger_id: uuid.UUID | None = None,
    intercompany: bool = True,
    doel_customer_guid: uuid.UUID | None = None,
) -> DoorbelastingMapping:
    """Whitelist-rij rechtstreeks in de bron-scope; `doel_administratie_id=None` = niet
    onboarded (spiegel_open-pad)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        mapping = DoorbelastingMapping(
            administratie_id=administratie_id,
            doelentiteit_naam=naam,
            doel_customer_guid=doel_customer_guid or uuid.uuid4(),
            doel_administratie_id=doel_administratie_id,
            intercompany=intercompany,
            provisie_kosten_ledger_id=provisie_kosten_ledger_id,
            aangemaakt_door=actor_id,
        )
        session.add(mapping)
        session.flush()
        session.expunge(mapping)
        return mapping


def start_run_met_verdeling(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    regels: list[VerdeelRegelInvoerData],
) -> DoorbelastingRun:
    run = doorbelasting_service.start_of_haal_run(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
    )
    doorbelasting_service.sla_verdeling_op(
        administratie_id=administratie_id, run_id=run.id, regels=regels, actor_id=actor_id
    )
    return run


def haal_run(administratie_id: uuid.UUID, run_id: uuid.UUID) -> DoorbelastingRun:  # noqa: F811
    with scoped_session(administratie_id) as session:
        run = session.get(DoorbelastingRun, run_id)
        assert run is not None
        session.expunge(run)
        return run


def haal_boekingen(administratie_id: uuid.UUID, run_id: uuid.UUID) -> list[DoorbelastingBoeking]:  # noqa: F811
    with scoped_session(administratie_id) as session:
        rijen = list(session.scalars(select(DoorbelastingBoeking).where(DoorbelastingBoeking.run_id == run_id)))
        session.expunge_all()
        return rijen


# --- volledige opzet (happy path) ---------------------------------------------------------


@dataclass(frozen=True)
class DoorbelastingOpzet:
    administratie_id: uuid.UUID
    doel_administratie_id: uuid.UUID | None
    document_id: uuid.UUID
    regel_ids: list[uuid.UUID]
    mapping: DoorbelastingMapping
    run: DoorbelastingRun


@pytest.fixture
def onboarded_opzet(
    doorbelasting_aan: None,
    instelling_compleet: None,
    geboekt_document: tuple[uuid.UUID, list[uuid.UUID]],
    doel_administratie_id: uuid.UUID,
    administratie_id: uuid.UUID,  # noqa: F811
    beheerder_id: uuid.UUID,  # noqa: F811
) -> DoorbelastingOpzet:
    """Onboarded doel + 100%-verdeling met gekozen doel-kosten-GB — direct boekbaar."""
    document_id, regel_ids = geboekt_document
    mapping = maak_mapping(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        doel_administratie_id=doel_administratie_id,
        provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
    )
    run = start_run_met_verdeling(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=beheerder_id,
        regels=[
            VerdeelRegelInvoerData(
                bron_regel_id=regel_ids[0],
                mapping_id=mapping.id,
                percentage=Decimal("100"),
                doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
            )
        ],
    )
    return DoorbelastingOpzet(
        administratie_id=administratie_id,
        doel_administratie_id=doel_administratie_id,
        document_id=document_id,
        regel_ids=regel_ids,
        mapping=mapping,
        run=run,
    )


@pytest.fixture
def spiegel_open_opzet(
    doorbelasting_aan: None,
    instelling_compleet: None,
    geboekt_document: tuple[uuid.UUID, list[uuid.UUID]],
    administratie_id: uuid.UUID,  # noqa: F811
    beheerder_id: uuid.UUID,  # noqa: F811
) -> DoorbelastingOpzet:
    """Doel níét onboarded (doel_administratie_id=None): bron-kant boekt, spiegel wordt
    een open taak."""
    document_id, regel_ids = geboekt_document
    mapping = maak_mapping(administratie_id=administratie_id, actor_id=beheerder_id)
    run = start_run_met_verdeling(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=beheerder_id,
        regels=[
            VerdeelRegelInvoerData(
                bron_regel_id=regel_ids[0],
                mapping_id=mapping.id,
                percentage=Decimal("100"),
                doel_kosten_ledger_id=None,
            )
        ],
    )
    return DoorbelastingOpzet(
        administratie_id=administratie_id,
        doel_administratie_id=None,
        document_id=document_id,
        regel_ids=regel_ids,
        mapping=mapping,
        run=run,
    )


# --- FakeDoorbelastingClient ---------------------------------------------------------------


class FakeDoorbelastingClient:
    """Duck-typed vervanger van RlzClient voor beide kanten van de doorbelastingsmotor.

    Bron-kant (verkoopmotor, app/omzet/boeken.py::_boek_verkoopfactuur): get_sales_invoice
    (404 vóór de PUT), put_sales_invoice (auto-InvoiceNumber, Reference "RLZ-{nr}"),
    upload_bijlage, book_sales_invoice, max_sales_invoice_number, correct_sales_invoice.
    Doel-kant (spiegelmotor): rechten-probe get("Ledgers"), find_vendors_by_name/put_vendor,
    get("PurchaseInvoices/{id}") (404 vóór de PUT), put_purchase_invoice,
    book_purchase_invoice, correct_purchase_invoice.

    `faal_op`: "spiegel_put" | "spiegel_boek" | "storno_verkoop" | "storno_spiegel" |
    "rechten_probe" | None (of een verzameling daarvan). `logboek` is een optioneel gedeelde
    lijst waarin de storno-volgorde over meerdere fakes heen wordt vastgelegd."""

    def __init__(
        self,
        *,
        faal_op: str | set[str] | None = None,
        logboek: list[tuple[str, str]] | None = None,
        bestaande_vendors: list[dict[str, Any]] | None = None,
        collectie_max_nummer: int = 371,
        aangiften: list[dict[str, Any]] | None = None,
    ) -> None:
        self.faal_op: set[str] = {faal_op} if isinstance(faal_op, str) else set(faal_op or ())
        # Btw-aangiften voor de storno-aangifte-poort (default: géén ingediende aangiften);
        # faal_op "aangiften" simuleert een onleesbare collectie (fail-closed-pad).
        self.aangiften = aangiften or []
        self.logboek = logboek if logboek is not None else []
        self.bestaande_vendors = bestaande_vendors or []
        self.collectie_max_nummer = collectie_max_nummer
        self.sales_invoices: dict[str, dict[str, Any]] = {}
        self.purchase_invoices: dict[str, dict[str, Any]] = {}
        self.vendors: dict[str, dict[str, Any]] = {}
        self.uploads: list[dict[str, Any]] = []
        # STAP-0 "Uploads bij een herstart-boekcyclus" (2026-08-16): een upload-GUID is
        # eenmalig — her-PUT op een bestaand GUID = 400 _InvalidData; een GUID dat verbruikt
        # is op een intussen verwijderd document = 404 _NotFound.
        self.verbruikte_upload_ids: set[str] = set()
        self.verkoop_correcties: list[str] = []
        self.spiegel_correcties: list[str] = []
        self.factuur_renders: list[str] = []
        self.probes = 0
        self._auto_nummer = 0
        self.gesloten = False

    # -- verbinding ---------------------------------------------------------------------
    def close(self) -> None:
        self.gesloten = True

    # -- btw-aangiften (storno-aangifte-poort, app/rlz/aangifte.py) -----------------------
    def list_tax_declarations(self) -> list[dict[str, Any]]:
        if "aangiften" in self.faal_op:
            raise RlzApiError(500, "GET", "TaxDeclarations", "Niet leesbaar (simulatie)")
        return self.aangiften

    # -- rauwe GET (rechten-probe + PurchaseInvoices-leespad) ----------------------------
    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "Ledgers":
            if "rechten_probe" in self.faal_op:
                raise RlzApiError(500, "GET", "Ledgers", "Geen rechten (simulatie)")
            self.probes += 1
            return {"value": [{"id": "00000000-0000-0000-0000-000000000001"}]}
        soort, _, doc_id = path.partition("/")
        if doc_id.endswith("/Uploads"):
            # Uploads-leesroute (STAP-0 2026-08-16: bruikbaar als aanwezigheids-check)
            entity_id = doc_id.removesuffix("/Uploads")
            return {"value": [u for u in self.uploads if u["pad"] == soort and u["entity_id"] == entity_id]}
        bron = {"PurchaseInvoices": self.purchase_invoices, "SalesInvoices": self.sales_invoices}.get(soort)
        if bron is None:
            raise AssertionError(f"Onverwachte GET in de fake: {path}")
        record = bron.get(doc_id)
        if record is None:
            raise RlzApiError(404, "GET", path, "Niet gevonden (simulatie)")
        return record

    # -- bron-kant: verkoopmotor ----------------------------------------------------------
    def get_sales_invoice(self, invoice_id: uuid.UUID | str) -> dict[str, Any]:
        record = self.sales_invoices.get(str(invoice_id))
        if record is None:
            raise RlzApiError(404, "GET", f"SalesInvoices/{invoice_id}", "Niet gevonden (simulatie)")
        return record

    def put_sales_invoice(
        self,
        invoice_id: uuid.UUID,
        *,
        customer_id: uuid.UUID | None,
        lines: list[dict],
        document_category_id: uuid.UUID | None = None,
        **extra: Any,
    ) -> None:
        nummer = extra.get("InvoiceNumber")
        if nummer is None:
            self._auto_nummer += 1
            nummer = self._auto_nummer
        bestaand = self.sales_invoices.get(str(invoice_id)) or {}
        self.sales_invoices[str(invoice_id)] = {
            "id": str(invoice_id),
            "Status": bestaand.get("Status", 1),
            "InvoiceNumber": nummer,
            "Reference": f"RLZ-{nummer}",
            "ReceiptNumber": f"RLZ-01-{nummer:08d}",
            "Entity": {"id": str(customer_id)} if customer_id is not None else None,
            "DocumentLineList": lines,
            "Date": extra.get("Date"),
            "BookDate": extra.get("BookDate"),
        }

    def book_sales_invoice(self, invoice_id: uuid.UUID) -> None:
        self.sales_invoices[str(invoice_id)]["Status"] = 2

    def correct_sales_invoice(self, invoice_id: uuid.UUID) -> None:
        if "storno_verkoop" in self.faal_op:
            raise RlzApiError(500, "POST", f"SalesInvoices/{invoice_id}/Actions", "Storno mislukt (simulatie)")
        record = self.sales_invoices.get(str(invoice_id))
        if record is None:
            raise RlzApiError(404, "POST", f"SalesInvoices/{invoice_id}/Actions", "Niet gevonden (simulatie)")
        record["Status"] = 1
        self.verkoop_correcties.append(str(invoice_id))
        self.logboek.append(("verkoop_storno", str(invoice_id)))

    def max_sales_invoice_number(self) -> int:
        return self.collectie_max_nummer

    # -- doel-kant: crediteur + spiegel-inkoop --------------------------------------------
    def find_vendors_by_name(self, *, name: str) -> list[dict[str, Any]]:
        vooraf = [v for v in self.bestaande_vendors if v.get("Name") == name]
        eigen = [v for v in self.vendors.values() if v.get("Name") == name]
        return vooraf + eigen

    def put_vendor(self, vendor_id: uuid.UUID, *, name: str, **extra: Any) -> None:
        self.vendors[str(vendor_id)] = {"id": str(vendor_id), "Name": name}

    def put_purchase_invoice(
        self,
        invoice_id: uuid.UUID,
        *,
        vendor_id: uuid.UUID,
        lines: list[dict],
        reference: str | None = None,
        **extra: Any,
    ) -> None:
        if "spiegel_put" in self.faal_op:
            raise RlzApiError(500, "PUT", f"PurchaseInvoices/{invoice_id}", "Onverwachte fout (simulatie)")
        bestaand = self.purchase_invoices.get(str(invoice_id)) or {}
        self.purchase_invoices[str(invoice_id)] = {
            "id": str(invoice_id),
            "Status": bestaand.get("Status", 1),
            "Reference": reference,
            "ReceiptNumber": "RLZ-30-00000012",
            "Entity": {"id": str(vendor_id)},
            "DocumentLineList": lines,
            "Date": extra.get("Date"),
            "BookDate": extra.get("BookDate"),
        }

    def book_purchase_invoice(self, invoice_id: uuid.UUID) -> None:
        if "spiegel_boek" in self.faal_op:
            raise RlzApiError(500, "POST", f"PurchaseInvoices/{invoice_id}/Actions", "Onverwachte fout (simulatie)")
        self.purchase_invoices[str(invoice_id)]["Status"] = 2

    def correct_purchase_invoice(self, invoice_id: uuid.UUID) -> None:
        if "storno_spiegel" in self.faal_op:
            raise RlzApiError(500, "POST", f"PurchaseInvoices/{invoice_id}/Actions", "Storno mislukt (simulatie)")
        record = self.purchase_invoices.get(str(invoice_id))
        if record is None:
            raise RlzApiError(404, "POST", f"PurchaseInvoices/{invoice_id}/Actions", "Niet gevonden (simulatie)")
        record["Status"] = 1
        self.spiegel_correcties.append(str(invoice_id))
        self.logboek.append(("spiegel_storno", str(invoice_id)))

    # -- gedeeld ---------------------------------------------------------------------------
    def upload_bijlage(
        self, entity_path: str, entity_id: uuid.UUID, *, upload_id: uuid.UUID, filename: str, content_base64: str
    ) -> None:
        sleutel = str(upload_id)
        if sleutel in self.verbruikte_upload_ids:
            pad = f"{entity_path}/{entity_id}/Uploads/{upload_id}"
            if any(u["upload_id"] == sleutel for u in self.uploads):
                raise RlzApiError(400, "PUT", pad, '{"Message":"_InvalidData"}')
            raise RlzApiError(404, "PUT", pad, '{"Message":"_NotFound"}')
        self.verbruikte_upload_ids.add(sleutel)
        self.uploads.append(
            {"pad": entity_path, "entity_id": str(entity_id), "upload_id": str(upload_id), "FileName": filename}
        )

    # -- bron-kant: RLZ's eigen factuurrender (blok A 26-08, STAP-0 "Factuur-PDF-rendering") ----
    def download_sales_invoice_pdf(self, invoice_id: uuid.UUID | str) -> bytes:
        """Bootst `GET SalesInvoices/{id}/Download` na: een PDF met precies wat RLZ toont —
        nummer (Reference), afzender-KvK/btw-nummer (uit de 'lay-out', hier vast), subtotaal,
        btw-som en totaal BEREKEND UIT DE RLZ-REGELS (NetAmount/TaxAmount) — zodat de toets in
        de motor écht bewijst dat onze geboekte centen en RLZ's render samenvallen.
        `faal_op` "factuur_render" = 500; "factuur_onvolledig" = lay-out zonder KvK/btw-nummer."""
        from decimal import Decimal

        from app.doorbelasting.factuur import nl_bedrag
        from app.materiaal.pdf import TekstRegel, bouw_pdf, paginering

        if "factuur_render" in self.faal_op:
            raise RlzApiError(500, "GET", f"SalesInvoices/{invoice_id}/Download", "Render mislukt (simulatie)")
        record = self.get_sales_invoice(invoice_id)
        netto = sum((Decimal(str(r["NetAmount"])) for r in record["DocumentLineList"]), Decimal(0))
        btw = sum((Decimal(str(r["TaxAmount"])) for r in record["DocumentLineList"]), Decimal(0))
        regels = [
            TekstRegel("Factuur", grootte=15, vet=True),
            TekstRegel(f"Factuurnummer:{record['Reference']}"),
            TekstRegel(f"Subtotaal (excl. BTW) € {nl_bedrag(netto)}"),
            TekstRegel(f"BTW 21 % over € {nl_bedrag(netto)} € {nl_bedrag(btw)}"),
            TekstRegel(f"Te betalen € {nl_bedrag(netto + btw)}"),
        ]
        if "factuur_onvolledig" not in self.faal_op:
            regels.append(TekstRegel("KVK: 12345678  BTW nr: NL123456789B01"))
        self.factuur_renders.append(str(invoice_id))
        return bouw_pdf(paginering(regels))

    def verwijder_document_in_rlz_ui(self, soort: str, doc_id: uuid.UUID | str) -> None:
        """Simuleert Peters handmatige verwijdering in de RLZ-UI (het kliktest-2-scenario):
        het document en zijn bijlagen verdwijnen, maar de verbruikte upload-GUID's blijven
        onbruikbaar (productie-waarneming: her-PUT op zo'n GUID geeft 404 _NotFound)."""
        bron = {"PurchaseInvoices": self.purchase_invoices, "SalesInvoices": self.sales_invoices}[soort]
        del bron[str(doc_id)]
        self.uploads = [u for u in self.uploads if not (u["pad"] == soort and u["entity_id"] == str(doc_id))]
