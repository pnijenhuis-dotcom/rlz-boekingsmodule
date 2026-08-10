"""Blok E grote opdracht 2026-08-10 — waarborg-SCHRIJF-STAP-0 tegen de échte
RLZ-test-administratie: het volledige waarborg-boekpad (intake-registratie → tegenrekening →
harde checks mét live RLZ-duplicaatquery → PUT ManualJournal saldo 0 + bijlage + actie 17) en
daarna storno (actie 19 — nooit hard verwijderen, §7.3). Verifieert en passant de
§6.4-verwachting dat balansrekening 0204 "Waarborgsommen" (RLZ-template) ook in de
test-administratie bestaat. Marker `write_integration` (skipt zonder TESTADMIN-credentials)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten.models import DocumentStatus
from app.documenten.rlz_ids import rlz_waarborg_memoriaal_id
from app.documenten.storage import LokaleBestandsopslag
from app.intake.verwerking import verwerk_eml
from app.rlz.client import RlzClient
from app.sync.service import sync_ledgers
from app.waarborg import boeken as waarborg_boeken
from app.waarborg import service as waarborg_service
from tests.intake.conftest import bouw_eml
from tests.waarborg.conftest import bouw_waarborg_xml

pytestmark = pytest.mark.write_integration

TESTADMIN_RLZ_ADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"


@pytest.fixture
def administratie_id(admin_engine: Engine) -> uuid.UUID:
    """Lokale administratie-rij met het échte TESTADMIN-adminId; de naam is de tenaamstelling
    waarop het waarborg-bericht toegewezen wordt."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, boeken_ingeschakeld) "
                "VALUES (:id, 'Administratiekantoor Nijenhuis (waarborg-test)', :rlz, true)"
            ),
            {"id": aid, "rlz": TESTADMIN_RLZ_ADMIN_ID},
        )
    return aid


def _tegenrekening(administratie_id: uuid.UUID) -> uuid.UUID:
    """Een boekbare balansrekening ≠ 0204 uit het échte rekeningschema — voorkeur Kruisposten
    (het parkeer-patroon uit de bank-PoC), anders de eerste boekbare activa-rekening."""
    from app.db.models import Grootboekrekening as GB

    from sqlalchemy import select

    with scoped_session(administratie_id) as session:
        rijen = session.scalars(
            select(GB).where(
                GB.administratie_id == administratie_id,
                GB.verdwenen_uit_bron_op.is_(None),
                GB.is_totaalrekening.is_(False),
            )
        ).all()
    kruis = [r for r in rijen if "kruispost" in (r.naam or "").lower()]
    if kruis:
        return kruis[0].ledger_id
    activa = [r for r in rijen if r.soort == 3 and r.code != "0204"]
    assert activa, "Geen boekbare activa-rekening gevonden in de test-administratie"
    return activa[0].ledger_id


def test_waarborg_stap0_volledige_cyclus_met_storno(
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    opslag: LokaleBestandsopslag,
    testadmin_client: RlzClient,
    _opslag_naar_tmp: None,
) -> None:
    # Écht rekeningschema in de cache (verifieert meteen §6.4: 0204 bestaat in de test-admin).
    sync_ledgers(administratie_id=administratie_id, client=testadmin_client)

    bericht_id = uuid.uuid4()
    eml = bouw_eml(
        afzender="boekhouding@vastly.nl",
        bijlagen=[(
            "vastly-waarborg-stap0.xml",
            bouw_waarborg_xml(
                bericht_id=bericht_id,
                verhuurder="Administratiekantoor Nijenhuis (waarborg-test)",
                rlz_admin_id=TESTADMIN_RLZ_ADMIN_ID,
                contract_referentie="TEST-WBG-STAP0",
                huurder="Testhuurder STAP-0",
                bedrag="1.50",
            ),
            "application", "xml",
        )],
    )
    resultaat = verwerk_eml(eml, actor_id=gescoopte_gebruiker)
    assert resultaat.bijlagen[0].uitkomst == "toegewezen", resultaat.bijlagen[0]
    document_id = resultaat.bijlagen[0].document_id
    assert document_id is not None

    voorstel = waarborg_service.haal_waarborg_voorstel_op(
        administratie_id=administratie_id, document_id=document_id
    )
    assert voorstel.balans_gb_status == "bekend", (
        "§6.4-verwachting geschonden: balansrekening 0204 niet (boekbaar) aanwezig in de test-administratie"
    )
    waarborg_service.sla_tegenrekening_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=gescoopte_gebruiker,
        tegenrekening_ledger_id=_tegenrekening(administratie_id),
    )

    boek_resultaat = waarborg_boeken.boek_waarborg_document(
        administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
    )
    rlz_id = rlz_waarborg_memoriaal_id(document_id)
    try:
        assert boek_resultaat.status == DocumentStatus.GEBOEKT
        assert boek_resultaat.memoriaal_rlz_id == rlz_id

        # Onafhankelijke verificatie rechtstreeks bij RLZ: geboekt (memoriaal = direct Status 3,
        # saldo 0 — niets staat open) en sluitend.
        geboekt = testadmin_client.get_manual_journal(rlz_id)
        assert geboekt["Status"] in (2, 3), geboekt.get("Status")
        assert geboekt.get("BalanceAmount") in (0, 0.0, None), geboekt.get("BalanceAmount")
        assert boek_resultaat.rlz_boekstuknummer
    finally:
        # Storno — actie 19, nooit hard verwijderen (§7.3).
        storno = testadmin_client.correct_manual_journal(rlz_id)
        assert storno.status_code < 300, storno.text
    gestorneerd = testadmin_client.get_manual_journal(rlz_id)
    assert gestorneerd["Status"] == 1
