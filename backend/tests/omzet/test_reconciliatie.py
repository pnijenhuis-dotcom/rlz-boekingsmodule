"""Omzet-reconciliatie: eigen registratie ↔ werkelijke RLZ-staat van beide documenten."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.session import scoped_session
from app.omzet import reconciliatie
from app.omzet.models import OmzetBoeking, OmzetBoekingStatus
from tests.omzet.conftest import FakeOmzetClient


def _registreer_boeking(
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    verkoop_rlz_id: uuid.UUID,
    memoriaal_rlz_id: uuid.UUID | None,
    status: str = OmzetBoekingStatus.GEBOEKT.value,
) -> None:
    extra: dict = {}
    if status == OmzetBoekingStatus.HALF_GEBOEKT.value:
        # Expliciet None zou een JSON-null worden (geen SQL NULL) en de CHECK-constraint raken —
        # het veld dus alleen zetten als er echt detail is, zoals de motor zelf ook doet.
        extra["half_geboekt_detail"] = {"memoriaal_fout": "x", "storno_verkoop_fout": "y"}
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        session.add(
            OmzetBoeking(
                administratie_id=administratie_id,
                document_id=document_id,
                periode_start=date(2025, 9, 15),
                periode_eind=date(2025, 9, 21),
                totaal_omzet=Decimal("100"),
                totaal_kostprijs=Decimal("60"),
                verkoop_rlz_id=verkoop_rlz_id,
                memoriaal_rlz_id=memoriaal_rlz_id,
                memoriaal_referentie="OMZ-20250915-20250921-KP" if memoriaal_rlz_id else None,
                status=status,
                geboekt_door=actor_id,
                **extra,
            )
        )


@pytest.fixture
def document_id(kassarapport_document: uuid.UUID) -> uuid.UUID:
    return kassarapport_document


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: FakeOmzetClient) -> None:
    monkeypatch.setattr(reconciliatie, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)


class TestReconcilieerOmzet:
    def test_kloppende_boeking_geeft_geen_afwijking(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        document_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = FakeOmzetClient()
        verkoop_id, memoriaal_id = uuid.uuid4(), uuid.uuid4()
        client.put_sales_invoice(verkoop_id, customer_id=uuid.uuid4(), lines=[])
        client.sales_invoices[str(verkoop_id)]["Status"] = 2
        client.put_manual_journal(memoriaal_id, diary_id=uuid.uuid4(), lines=[])
        client.manual_journals[str(memoriaal_id)]["Status"] = 3
        _patch_client(monkeypatch, client)
        _registreer_boeking(
            administratie_id, gescoopte_gebruiker, document_id,
            verkoop_rlz_id=verkoop_id, memoriaal_rlz_id=memoriaal_id,
        )

        assert reconciliatie.reconcilieer_omzet(administratie_id) == []

    def test_in_rlz_teruggedraaide_verkoop_wordt_gemeld(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        document_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = FakeOmzetClient()
        verkoop_id, memoriaal_id = uuid.uuid4(), uuid.uuid4()
        client.put_sales_invoice(verkoop_id, customer_id=uuid.uuid4(), lines=[])  # Status 1
        client.put_manual_journal(memoriaal_id, diary_id=uuid.uuid4(), lines=[])
        client.manual_journals[str(memoriaal_id)]["Status"] = 3
        _patch_client(monkeypatch, client)
        _registreer_boeking(
            administratie_id, gescoopte_gebruiker, document_id,
            verkoop_rlz_id=verkoop_id, memoriaal_rlz_id=memoriaal_id,
        )

        afwijkingen = reconciliatie.reconcilieer_omzet(administratie_id)
        assert len(afwijkingen) == 1
        assert afwijkingen[0].soort == "rlz_afwijking"
        assert "Status 1" in afwijkingen[0].detail

    def test_verdwenen_memoriaal_wordt_gemeld(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        document_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = FakeOmzetClient()
        verkoop_id = uuid.uuid4()
        client.put_sales_invoice(verkoop_id, customer_id=uuid.uuid4(), lines=[])
        client.sales_invoices[str(verkoop_id)]["Status"] = 2
        _patch_client(monkeypatch, client)
        _registreer_boeking(
            administratie_id, gescoopte_gebruiker, document_id,
            verkoop_rlz_id=verkoop_id, memoriaal_rlz_id=uuid.uuid4(),
        )

        afwijkingen = reconciliatie.reconcilieer_omzet(administratie_id)
        assert len(afwijkingen) == 1
        assert "bestaat niet" in afwijkingen[0].detail

    def test_half_geboekt_wordt_altijd_gemeld(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        document_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_client(monkeypatch, FakeOmzetClient())
        _registreer_boeking(
            administratie_id, gescoopte_gebruiker, document_id,
            verkoop_rlz_id=uuid.uuid4(), memoriaal_rlz_id=uuid.uuid4(),
            status=OmzetBoekingStatus.HALF_GEBOEKT.value,
        )

        afwijkingen = reconciliatie.reconcilieer_omzet(administratie_id)
        assert len(afwijkingen) == 1
        assert afwijkingen[0].soort == "half_geboekt"

    def test_zonder_boekingen_geen_rlz_verkeer(
        self, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explodeer(rlz_admin_id: str):  # pragma: no cover — mag nooit aangeroepen worden
            raise AssertionError("Geen RLZ-verbinding verwacht zonder omzet-boekingen")

        monkeypatch.setattr(reconciliatie, "client_voor_rlz_admin_id", explodeer)
        assert reconciliatie.reconcilieer_omzet(administratie_id) == []
