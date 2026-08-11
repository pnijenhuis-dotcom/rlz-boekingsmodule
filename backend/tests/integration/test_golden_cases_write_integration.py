"""Blok D grote opdracht 2026-08-10 — golden-case-SCHRIJFVERIFICATIE tegen de échte
RLZ-test-administratie ('Administratiekantoor Nijenhuis', TESTADMIN): boek minstens één golden
380 via het volledige verkoop-boekpad (debiteur-aanmaak + SalesInvoice + actie 17), verifieer
de factuur_geboekt-outbox-registratie, storneer (actie 19 — nooit hard verwijderen, §7.3);
daarna de golden 381 als creditboeking (negatieve tegenboeking op DEZELFDE debiteur) + storno.

Marker `write_integration` (skipt automatisch zonder TESTADMIN-credentials in verkenning/.env);
zelfde administratie-fixture-patroon als test_boekflow_write_integration.py. De caches worden
gevuld met een ÉCHTE sync (Ledgers + TaxRates) — dat verifieert en passant blok A live: de
taxrate-cache draagt fracties (bronformaat) en de golden-UBL-percentages resolven erop."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.documenten import service as documenten_service
from app.documenten.models import DocumentSoort, DocumentStatus
from app.documenten.rlz_ids import rlz_sales_invoice_id
from app.documenten.storage import LokaleBestandsopslag
from app.rlz.client import RlzClient
from app.sync.service import sync_ledgers, sync_taxrates
from app.verkoop import boeken as verkoop_boeken
from app.verkoop import voorstel as voorstel_service
from tests.verkoop.conftest import bouw_vastly_verkoop_ubl

pytestmark = pytest.mark.write_integration

TESTADMIN_RLZ_ADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
GOLDEN_DIR = Path(__file__).resolve().parents[3].parent / "Platform" / "uitwisseling"


def _golden(naam: str) -> bytes:
    return (GOLDEN_DIR / naam).read_bytes()


@pytest.fixture
def administratie_id(admin_engine: Engine) -> uuid.UUID:
    """Lokale administratie-rij met het échte TESTADMIN-adminId; is_vastgoed aan zodat het
    factuur_geboekt-event (outbox-scope-filter, migratie 0018) daadwerkelijk ontstaat."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, boeken_ingeschakeld, is_vastgoed) "
                "VALUES (:id, 'Administratiekantoor Nijenhuis (golden-case-test)', :rlz, true, true)"
            ),
            {"id": aid, "rlz": TESTADMIN_RLZ_ADMIN_ID},
        )
    return aid


@pytest.fixture
def echte_caches(administratie_id: uuid.UUID, testadmin_client: RlzClient) -> None:
    """Vul grootboek- én taxrate-cache met een échte sync tegen de test-administratie."""
    sync_ledgers(administratie_id=administratie_id, client=testadmin_client)
    sync_taxrates(administratie_id=administratie_id, client=testadmin_client)


def _upload(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, inhoud: bytes, naam: str
) -> uuid.UUID:
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=inhoud,
        actor_id=actor_id,
        opslag=opslag,
        soort=DocumentSoort.VERKOOPFACTUUR,
    )
    return resultaat.document_id


def _kies_ontbrekende_velden(
    prefill: voorstel_service.VerkoopVoorstelData,
    administratie_id: uuid.UUID,
) -> list[voorstel_service.VerkoopRegelInput]:
    """De golden-codes (8000/8100) bestaan mogelijk niet in het rekeningschema van de
    test-administratie ('onbekende code' is per §2d blokkerend) en de btw kan ambigu zijn
    (twee actieve 21%-tarieven in het RLZ-template — dan één keer kiezen, wordt onthouden).
    Deze helper doet wat de controleur in het scherm zou doen: bij ambiguïteit het
    niet-vooruit-tarief uit de kandidatenset kiezen. Een 'onbekende' GB-code laten we bewust
    staan — dan hoort de check te blokkeren en rapporteert de test dat expliciet."""
    from app.db.session import scoped_session
    from app.sync.models import TaxRateCache

    regels = []
    with scoped_session(administratie_id) as session:
        for r in prefill.regels:
            taxrate_id = r.taxrate_id
            if taxrate_id is None and r.btw_kandidaten:
                namen = {
                    kandidaat: (session.get(TaxRateCache, (kandidaat, administratie_id)) or object)
                    for kandidaat in r.btw_kandidaten
                }
                gekozen = None
                for kandidaat, rij in namen.items():
                    naam = getattr(rij, "naam", "") or ""
                    if "vooruit" not in naam.lower():
                        gekozen = kandidaat
                        break
                taxrate_id = gekozen or r.btw_kandidaten[0]
            regels.append(
                voorstel_service.VerkoopRegelInput(
                    omschrijving=r.omschrijving,
                    netto_bedrag=r.netto_bedrag,
                    btw_bedrag=r.btw_bedrag,
                    gb_code=r.gb_code,
                    ledger_id=r.ledger_id,
                    taxrate_id=taxrate_id,
                )
            )
    return regels


def _sla_op_en_boek(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> verkoop_boeken.VerkoopBoekResultaat:
    prefill = voorstel_service.haal_verkoop_voorstel_op(
        administratie_id=administratie_id, document_id=document_id
    )
    onbekend = [r for r in prefill.regels if r.gb_code_status == "onbekend"]
    assert not onbekend, (
        "Golden-case-GB-code(s) bestaan niet in het rekeningschema van de test-administratie: "
        + ", ".join(f"regel {r.volgnummer}: {r.gb_code}" for r in onbekend)
    )
    voorstel_service.sla_verkoop_voorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        debiteur_naam=prefill.debiteur_naam,
        factuurnummer=prefill.factuurnummer,
        factuurdatum=prefill.factuurdatum,
        totaalbedrag_incl=prefill.totaalbedrag_incl,
        regels=_kies_ontbrekende_velden(prefill, administratie_id),
    )
    return verkoop_boeken.boek_verkoop_document(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
    )


def _webhook_rij(admin_engine: Engine, document_id: uuid.UUID):
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT event, payload FROM boekhouding.webhook_uitgaand WHERE document_id = :id"),
            {"id": document_id},
        ).one_or_none()


def test_golden_380_volledige_boekcyclus_met_webhook_en_storno(
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    opslag: LokaleBestandsopslag,
    testadmin_client: RlzClient,
    echte_caches: None,
    admin_engine: Engine,
    _opslag_naar_tmp: None,
) -> None:
    document_id = _upload(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
        inhoud=_golden("factuur-380-golden-standaard.xml"),
        naam="factuur-380-golden-standaard.xml",
    )
    resultaat = _sla_op_en_boek(
        administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
    )
    rlz_id = rlz_sales_invoice_id(document_id)
    try:
        assert resultaat.status == DocumentStatus.GEBOEKT

        # Onafhankelijke verificatie rechtstreeks bij RLZ.
        geboekt = testadmin_client.get(f"SalesInvoices/{rlz_id}")
        assert geboekt["Status"] in (2, 3), geboekt.get("Status")

        # factuur_geboekt-registratie (outbox; aflevering blijft default UIT).
        rij = _webhook_rij(admin_engine, document_id)
        assert rij is not None, "Geen factuur_geboekt-outbox-rij aangemaakt"
        assert rij.event == "factuur_geboekt"
        assert rij.payload["data"]["referentie"] == "RUB-2026-0001"
        assert rij.payload["data"]["soort"] == "verkoopfactuur"
        assert rij.payload["data"]["debiteur"]["naam"] == "Tester Retail B.V."
    finally:
        # Storno — actie 19, nooit hard verwijderen (§7.3).
        storno = testadmin_client.correct_sales_invoice(rlz_id)
        assert storno.status_code < 300, storno.text
    gestorneerd = testadmin_client.get(f"SalesInvoices/{rlz_id}")
    assert gestorneerd["Status"] == 1


def test_golden_381_creditboeking_op_dezelfde_debiteur_met_storno(
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    opslag: LokaleBestandsopslag,
    testadmin_client: RlzClient,
    echte_caches: None,
    admin_engine: Engine,
    _opslag_naar_tmp: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ De golden 381 crediteert GC-2026-0001 — dat origineel zit niet in de golden-set
    (bevinding, zie OPEN_ITEMS). Het origineel wordt hier daarom eerst écht geboekt als eigen
    380 met dat nummer en dezelfde huurder, zodat de herleiding rond is; daarna de golden 381."""
    from app.config import settings

    monkeypatch.setattr(settings, "creditnota_381_ingeschakeld", True)

    origineel_id = _upload(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
        inhoud=bouw_vastly_verkoop_ubl(
            factuurnummer="GC-2026-0001",
            leverancier="Rubicon Investments B.V.",
            huurder="Tester Retail B.V.",
            regels=[{"naam": "Huur mei 2026", "netto": "864.00", "pct": "21.00",
                     "categorie": "S", "gb_code": "8000"}],
        ),
        naam="origineel-gc-2026-0001.xml",
    )
    origineel = _sla_op_en_boek(
        administratie_id=administratie_id, document_id=origineel_id, actor_id=gescoopte_gebruiker
    )
    origineel_rlz_id = rlz_sales_invoice_id(origineel_id)
    credit_rlz_id = None
    try:
        assert origineel.status == DocumentStatus.GEBOEKT

        credit_id = _upload(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=_golden("creditnote-381-golden-standaard.xml"),
            naam="creditnote-381-golden-standaard.xml",
        )
        credit = _sla_op_en_boek(
            administratie_id=administratie_id, document_id=credit_id, actor_id=gescoopte_gebruiker
        )
        credit_rlz_id = rlz_sales_invoice_id(credit_id)
        assert credit.status == DocumentStatus.GEBOEKT

        # Negatieve tegenboeking op DEZELFDE debiteur (besluit Peter 2026-08-08).
        geboekt_credit = testadmin_client.get(f"SalesInvoices/{credit_rlz_id}?$expand=Entity")
        assert geboekt_credit["Status"] in (2, 3)
        assert float(geboekt_credit["BaseInvoiceAmount"]) < 0, geboekt_credit["BaseInvoiceAmount"]
        geboekt_origineel = testadmin_client.get(f"SalesInvoices/{origineel_rlz_id}?$expand=Entity")
        assert geboekt_credit["Entity"]["id"] == geboekt_origineel["Entity"]["id"]

        rij = _webhook_rij(admin_engine, credit_id)
        assert rij is not None and rij.payload["data"]["referentie"] == "GC-2026-0002"
        assert rij.payload["data"]["is_creditnota"] is True
    finally:
        if credit_rlz_id is not None:
            storno_credit = testadmin_client.correct_sales_invoice(credit_rlz_id)
            assert storno_credit.status_code < 300, storno_credit.text
        storno_origineel = testadmin_client.correct_sales_invoice(origineel_rlz_id)
        assert storno_origineel.status_code < 300, storno_origineel.text
    assert testadmin_client.get(f"SalesInvoices/{origineel_rlz_id}")["Status"] == 1
    if credit_rlz_id is not None:
        assert testadmin_client.get(f"SalesInvoices/{credit_rlz_id}")["Status"] == 1
