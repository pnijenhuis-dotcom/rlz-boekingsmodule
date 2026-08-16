"""Opruimlijst achtergebleven RLZ-concepten (hygiëne-run 2026-08-16).

Poortlogica: gestorneerde boekingen en vervallen (gefaalde) runs worden tegen de échte
RLZ-staat geprobed — Status 1 = opruim-kandidaat, 404 = al opgeruimd (geen bevinding),
ontbrekende doel-credentials = zichtbare fout. Puur informatief: de app verwijdert nooit.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.db.session import scoped_session
from app.documenten.rlz_ids import rlz_doorbelasting_spiegel_id, rlz_doorbelasting_verkoop_id
from app.doorbelasting import reconciliatie
from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingBoekingStatus
from app.rlz.client import RlzApiError
from app.rlz.credentials import GeenRlzCredentials

from .conftest import DoorbelastingOpzet  # noqa: F401 — typegemak


class _FakeRlz:
    """Duck-typed credential-client: status per RLZ-id, 404 voor onbekende id's."""

    def __init__(self, statussen: dict[uuid.UUID, int]) -> None:
        self.statussen = statussen

    def for_administration(self, admin_id: str) -> _FakeRlz:
        return self

    def __enter__(self) -> _FakeRlz:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def get(self, pad: str) -> dict:
        rlz_id = uuid.UUID(pad.split("/")[1])
        if rlz_id not in self.statussen:
            raise RlzApiError(404, "GET", pad, "not found")
        return {"Status": self.statussen[rlz_id]}


@pytest.fixture
def gestorneerde_boeking(onboarded_opzet: DoorbelastingOpzet) -> DoorbelastingBoeking:
    """Handmatig ingelegde gestorneerde boeking met bekende RLZ-GUID's."""
    opzet = onboarded_opzet
    verkoop_id = rlz_doorbelasting_verkoop_id(opzet.document_id, opzet.mapping.doel_customer_guid)
    spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)
    with scoped_session(opzet.administratie_id) as session:
        boeking = DoorbelastingBoeking(
            run_id=opzet.run.id,
            administratie_id=opzet.administratie_id,
            document_id=opzet.document_id,
            mapping_id=opzet.mapping.id,
            doel_administratie_id=opzet.doel_administratie_id,
            status=DoorbelastingBoekingStatus.GESTORNEERD.value,
            netto_totaal=Decimal("100.00"),
            provisie_bedrag=Decimal("5.00"),
            btw_bedrag=Decimal("22.05"),
            verkoop_rlz_id=verkoop_id,
            verkoop_referentie="V26-0001",
            spiegel_rlz_id=spiegel_id,
            storno_reden="kliktest",
            geboekt_door=opzet.run.aangemaakt_door,
        )
        session.add(boeking)
        session.flush()
        session.expunge(boeking)
    return boeking


def _patch_rlz(monkeypatch: pytest.MonkeyPatch, fake: _FakeRlz) -> None:
    monkeypatch.setattr(reconciliatie, "rlz_admin_id_voor", lambda aid: str(aid))
    monkeypatch.setattr(reconciliatie, "client_voor_rlz_admin_id", lambda rid: fake)


def test_gestorneerde_boeking_met_concepten_beide_kanten(
    gestorneerde_boeking: DoorbelastingBoeking, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeRlz(
        {
            gestorneerde_boeking.verkoop_rlz_id: 1,
            gestorneerde_boeking.spiegel_rlz_id: 1,
        }
    )
    _patch_rlz(monkeypatch, fake)

    resultaat = reconciliatie.verzamel_opruimlijst(gestorneerde_boeking.administratie_id)

    assert resultaat.fouten == []
    kanten = {(k.kant, k.rlz_id) for k in resultaat.kandidaten}
    assert kanten == {
        ("verkoop_bron", gestorneerde_boeking.verkoop_rlz_id),
        ("spiegel_doel", gestorneerde_boeking.spiegel_rlz_id),
    }
    assert all(k.reden == "gestorneerd" for k in resultaat.kandidaten)
    spiegel = next(k for k in resultaat.kandidaten if k.kant == "spiegel_doel")
    assert spiegel.concept_administratie_id == gestorneerde_boeking.doel_administratie_id


def test_al_opgeruimde_concepten_geven_geen_bevinding(
    gestorneerde_boeking: DoorbelastingBoeking, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_rlz(monkeypatch, _FakeRlz({}))  # alles 404 = door Peter al verwijderd in de RLZ-UI
    resultaat = reconciliatie.verzamel_opruimlijst(gestorneerde_boeking.administratie_id)
    assert resultaat.kandidaten == [] and resultaat.fouten == []


def test_herboekt_document_is_geen_opruimkandidaat(
    gestorneerde_boeking: DoorbelastingBoeking, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Status 2/3 = opnieuw geboekt op dezelfde GUID (herstart-cyclus) — niet opruimen."""
    _patch_rlz(monkeypatch, _FakeRlz({gestorneerde_boeking.verkoop_rlz_id: 2}))
    resultaat = reconciliatie.verzamel_opruimlijst(gestorneerde_boeking.administratie_id)
    assert resultaat.kandidaten == []


def test_vervallen_run_via_deterministische_guids(
    onboarded_opzet: DoorbelastingOpzet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Een concept-run mét laatste_fout (gefaalde boekpoging, geen boeking-rij) wordt via de
    afgeleide UUIDv5-GUID's geprobed."""
    opzet = onboarded_opzet
    from app.doorbelasting.models import DoorbelastingRun

    with scoped_session(opzet.administratie_id) as session:
        run = session.get(DoorbelastingRun, opzet.run.id)
        run.laatste_fout = {str(opzet.mapping.id): "actie 17 faalde (test)"}
    verkoop_id = rlz_doorbelasting_verkoop_id(opzet.document_id, opzet.mapping.doel_customer_guid)
    _patch_rlz(monkeypatch, _FakeRlz({verkoop_id: 1}))

    resultaat = reconciliatie.verzamel_opruimlijst(opzet.administratie_id)

    assert [k.kant for k in resultaat.kandidaten] == ["verkoop_bron"]
    assert resultaat.kandidaten[0].reden == "vervallen_run"
    assert resultaat.kandidaten[0].rlz_id == verkoop_id


def test_doel_zonder_credentials_geeft_zichtbare_fout(
    gestorneerde_boeking: DoorbelastingBoeking, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeRlz({gestorneerde_boeking.verkoop_rlz_id: 1})

    def _admin_id_voor(administratie_id: uuid.UUID) -> str:
        if administratie_id == gestorneerde_boeking.doel_administratie_id:
            raise GeenRlzCredentials(f"geen credentials voor {administratie_id}")
        return str(administratie_id)

    monkeypatch.setattr(reconciliatie, "rlz_admin_id_voor", _admin_id_voor)
    monkeypatch.setattr(reconciliatie, "client_voor_rlz_admin_id", lambda rid: fake)

    resultaat = reconciliatie.verzamel_opruimlijst(gestorneerde_boeking.administratie_id)

    assert [k.kant for k in resultaat.kandidaten] == ["verkoop_bron"]
    assert len(resultaat.fouten) == 1 and "geen credentials" in resultaat.fouten[0]
