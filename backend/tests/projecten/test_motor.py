"""Geldlogica-tests voor de idempotente projectaanmaak (route A): idempotentie, fail-closed
foutpaden, anker-hergebruik en de directe project_cache-bijwerking."""

from __future__ import annotations

import uuid

import pytest

from app.db.session import scoped_session
from app.documenten.rlz_ids import rlz_pand_project_id
from app.projecten import motor
from app.projecten.models import ProjectAanvraagStatus
from app.sync.models import ProjectCache
from tests.projecten.conftest import FakeProjectClient

PAND_REF = "vastly-object-42"
NAAM = "Dorpsstraat 1, Zwolle"


def _maak(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, fake: FakeProjectClient, **kw):
    return motor.maak_pand_project_aan(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        pand_referentie=kw.pop("pand_referentie", PAND_REF),
        naam_invoer=kw.pop("naam_invoer", NAAM),
        client=fake,
        **kw,
    )


def test_aanmaak_zet_is_active_en_vult_cache(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    resultaat = _maak(administratie_id, beheerder_id, fake_rlz)

    assert resultaat.status is ProjectAanvraagStatus.AANGEMAAKT
    assert resultaat.projectnaam == NAAM
    assert resultaat.rlz_project_id == rlz_pand_project_id(administratie_id, PAND_REF)
    project = fake_rlz.projects[str(resultaat.rlz_project_id)]
    # STAP-0 §6: zonder expliciet IsActive:true zou het project inactief zijn.
    assert project["IsActive"] is True
    # Het project hangt onder het systeemanker (STAP-0 §3: écht customer-gebonden).
    assert fake_rlz.customers[project["_customer"]] == motor.ANKER_CUSTOMER_NAAM
    with scoped_session(administratie_id) as session:
        rij = session.get(ProjectCache, (resultaat.rlz_project_id, administratie_id))
        assert rij is not None and rij.naam == NAAM and rij.is_actief is True


def test_tweede_aanvraag_zelfde_pand_is_zelfde_project_geen_duplicaat(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    eerste = _maak(administratie_id, beheerder_id, fake_rlz)
    tweede = _maak(administratie_id, beheerder_id, fake_rlz, naam_invoer="Dorpsstraat 1,  Zwolle")

    assert tweede.status is ProjectAanvraagStatus.BESTOND_AL
    assert tweede.rlz_project_id == eerste.rlz_project_id
    # De RLZ-staat wint: geen herhaal-PUT (die zou muteren, STAP-0 §5) en de naam blijft die
    # van het bestaande project.
    assert fake_rlz.put_project_aanroepen == 1
    assert tweede.projectnaam == NAAM
    assert len(fake_rlz.projects) == 1


def test_naam_conflict_is_fail_closed(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    ander_id = str(uuid.uuid4())
    fake_rlz.projects[ander_id] = {"id": ander_id, "Name": NAAM, "IsActive": True}

    with pytest.raises(motor.ProjectNaamConflict):
        _maak(administratie_id, beheerder_id, fake_rlz)
    assert fake_rlz.put_project_aanroepen == 0


def test_rlz_fout_is_zichtbaar_en_laat_geen_cache_achter(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    fake_rlz.faal_bij_put_project = True

    with pytest.raises(motor.ProjectAanmakenMislukt):
        _maak(administratie_id, beheerder_id, fake_rlz)
    with scoped_session(administratie_id) as session:
        rij = session.get(
            ProjectCache, (rlz_pand_project_id(administratie_id, PAND_REF), administratie_id)
        )
        assert rij is None


def test_lookup_fout_blokkeert_voor_de_put(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    fake_rlz.faal_bij_lookup = True

    with pytest.raises(motor.ProjectAanmakenMislukt, match="lookup"):
        _maak(administratie_id, beheerder_id, fake_rlz)
    assert fake_rlz.put_project_aanroepen == 0


def test_bestaand_anker_wordt_hergebruikt(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    bestaand_anker = str(uuid.uuid4())
    fake_rlz.customers[bestaand_anker] = motor.ANKER_CUSTOMER_NAAM

    resultaat = _maak(administratie_id, beheerder_id, fake_rlz)

    assert fake_rlz.put_customer_aanroepen == 0
    assert fake_rlz.projects[str(resultaat.rlz_project_id)]["_customer"] == bestaand_anker


def test_twee_ankers_is_fout_nooit_gokken(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    fake_rlz.customers[str(uuid.uuid4())] = motor.ANKER_CUSTOMER_NAAM
    fake_rlz.customers[str(uuid.uuid4())] = motor.ANKER_CUSTOMER_NAAM

    with pytest.raises(motor.ProjectAanmakenMislukt, match="Meerdere"):
        _maak(administratie_id, beheerder_id, fake_rlz)
    assert fake_rlz.put_project_aanroepen == 0
