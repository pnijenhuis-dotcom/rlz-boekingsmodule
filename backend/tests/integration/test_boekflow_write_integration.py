"""Schrijf-integratietest van de VOLLEDIGE boekcyclus (CLAUDE.md-taak 2.6) — via de echte
servicelaag (app.documenten.boeken.boek_document), niet los tegen RlzClient zoals
test_write_integration.py. Uitsluitend tegen de RLZ-test-administratie ('Administratiekantoor
Nijenhuis', Platform/registers/entiteiten.md); marker `write_integration`, skipt automatisch
zonder TESTADMIN_USERNAME/TESTADMIN_PASSWORD in verkenning/.env.

Flow: document uploaden -> boekvoorstel opslaan (echte vendor + geverifieerde test-rekeningen) ->
boek_document() (harde checks incl. live duplicaatcheck -> PUT + /Uploads + actie 17 tegen de
échte RLZ-test-administratie) -> verifiëren via een onafhankelijke RLZ-GET -> storneren (actie 19,
nooit hard verwijderen — koppelcontract §7.3).

De `administratie_id`-fixture hieronder overschrijft bewust die uit tests/auth/conftest.py: deze
test heeft een lokale platform.administratie-rij nodig waarvan `rlz_admin_id` het ECHTE
TESTADMIN-adminId is (anders resolvet de credential-laag nooit de juiste RLZ-inloggegevens) én
`boeken_ingeschakeld=true` (CLAUDE.md: 'boeken staat alleen aan voor de test-administratie').
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.documenten import boeken, boekvoorstel, service
from app.documenten.models import DocumentStatus
from app.documenten.rlz_ids import rlz_purchase_invoice_id
from app.documenten.storage import LokaleBestandsopslag
from app.rlz.client import RlzClient

pytestmark = pytest.mark.write_integration

TESTADMIN_RLZ_ADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
# Geverifieerde rekeningen in de test-administratie (UseForPurchaseInvoiceDetails=true) — zie
# test_write_integration.py.
TEST_ACCOUNT_ID = uuid.UUID("79b6f64a-dad9-4683-9e47-9c182ebae1c1")
TEST_TAXRATE_ID = uuid.UUID("1e44993a-15f6-419f-87e5-3e31ac3d9383")


@pytest.fixture
def administratie_id(admin_engine: Engine) -> uuid.UUID:
    """Overschrijft tests/auth/conftest.py::administratie_id — zie moduledocstring."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, boeken_ingeschakeld) "
                "VALUES (:id, 'Administratiekantoor Nijenhuis (test)', :rlz, true)"
            ),
            {"id": aid, "rlz": TESTADMIN_RLZ_ADMIN_ID},
        )
    return aid


@pytest.fixture
def test_vendor_id(testadmin_client: RlzClient) -> uuid.UUID:
    vendor_id = uuid.uuid4()
    resp = testadmin_client.put_vendor(vendor_id, name="TEST boekflow-integratie — verwijderen")
    assert resp.status_code < 300, resp.text
    return vendor_id


def test_volledige_boekcyclus_via_de_servicelaag(
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    opslag: LokaleBestandsopslag,
    testadmin_client: RlzClient,
    test_vendor_id: uuid.UUID,
    _opslag_naar_tmp: None,
) -> None:
    # 1. Document binnen (PDF — geen UBL nodig, het boekvoorstel wordt hier handmatig ingevuld
    # zoals een controleur dat in het echte controlescherm zou doen).
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="testfactuur.pdf",
        inhoud=b"%PDF-1.4 boekflow-write-integration-test",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    document_id = resultaat.document_id
    reference = f"TEST-BOEKFLOW-{document_id}"

    # 2. Boekvoorstel opslaan — echte vendor, geverifieerde grootboek-/btw-GUID's.
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=test_vendor_id,
        referentie=reference,
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal("1.21"),
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=TEST_ACCOUNT_ID,
                taxrate_id=TEST_TAXRATE_ID,
                project_id=None,
                netto_bedrag=Decimal("1.00"),
                btw_bedrag=Decimal("0.21"),
                omschrijving="Write-integration testregel",
            )
        ],
    )

    # 3. De echte boekactie: harde checks (incl. live duplicaatcheck) -> PUT + /Uploads + actie 17
    # tegen de RLZ-test-administratie.
    boek_resultaat = boeken.boek_document(
        administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
    )

    assert boek_resultaat.status == DocumentStatus.GEBOEKT
    assert boek_resultaat.rlz_document_id == rlz_purchase_invoice_id(document_id)
    assert boek_resultaat.rlz_boekstuknummer is not None and boek_resultaat.rlz_boekstuknummer.startswith("RLZ-")

    # 4. Onafhankelijke verificatie rechtstreeks bij RLZ (los van de servicelaag-fixture-client).
    geboekte_factuur = testadmin_client.get(f"PurchaseInvoices/{boek_resultaat.rlz_document_id}")
    assert geboekte_factuur["Status"] == 2, "Verwachtte definitief-geboekt (2) na actie 17"
    assert geboekte_factuur["Reference"] == reference[:30]
    assert geboekte_factuur["ReceiptNumber"] == boek_resultaat.rlz_boekstuknummer
    assert geboekte_factuur["BaseInvoiceAmount"] == 1.21

    # 5. Storneren — nooit hard verwijderen (koppelcontract §7.3): actie 19 zet het document terug
    # naar concept (Status 1), geen apart creditdocument.
    correct_resp = testadmin_client.correct_purchase_invoice(boek_resultaat.rlz_document_id)
    assert correct_resp.status_code < 300, correct_resp.text
    gestorneerde_factuur = testadmin_client.get(f"PurchaseInvoices/{boek_resultaat.rlz_document_id}")
    assert gestorneerde_factuur["Status"] == 1, "Actie 19 hoort het document terug naar concept te zetten"


def test_duplicaatcheck_blokkeert_een_tweede_boeking_met_dezelfde_referentie(
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    opslag: LokaleBestandsopslag,
    testadmin_client: RlzClient,
    test_vendor_id: uuid.UUID,
    _opslag_naar_tmp: None,
) -> None:
    """Twee VERSCHILLENDE documenten (dus twee verschillende client-GUID's) met dezelfde
    referentie+crediteur+bedrag: het eerste boekt, het tweede moet de eigen duplicaatcheck raken
    (RLZ zelf blokkeert dit niet — besluit 0013) en blijft op klaar_om_te_boeken staan."""
    reference = f"TEST-BOEKFLOW-DUP-{uuid.uuid4()}"

    def _upload_en_boekvoorstel() -> uuid.UUID:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam=f"{uuid.uuid4()}.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=test_vendor_id,
            referentie=reference,
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("1.21"),
            regels=[
                boekvoorstel.BoekvoorstelRegelData(
                    ledger_id=TEST_ACCOUNT_ID,
                    taxrate_id=TEST_TAXRATE_ID,
                    project_id=None,
                    netto_bedrag=Decimal("1.00"),
                    btw_bedrag=Decimal("0.21"),
                    omschrijving="Duplicaatcheck-test",
                )
            ],
        )
        return resultaat.document_id

    eerste_document_id = _upload_en_boekvoorstel()
    eerste_resultaat = boeken.boek_document(
        administratie_id=administratie_id, document_id=eerste_document_id, actor_id=gescoopte_gebruiker
    )
    assert eerste_resultaat.status == DocumentStatus.GEBOEKT

    tweede_document_id = _upload_en_boekvoorstel()
    with pytest.raises(boeken.BoekenGeblokkeerdDoorChecks) as excinfo:
        boeken.boek_document(
            administratie_id=administratie_id, document_id=tweede_document_id, actor_id=gescoopte_gebruiker
        )
    duplicaatcheck = next(r for r in excinfo.value.rapport.resultaten if r.naam == "Duplicaatcheck")
    assert not duplicaatcheck.ok

    # Opruimen: het eerste (echt geboekte) document storneren.
    testadmin_client.correct_purchase_invoice(eerste_resultaat.rlz_document_id)
