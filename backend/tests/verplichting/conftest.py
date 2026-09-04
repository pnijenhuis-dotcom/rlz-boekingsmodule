"""Fixtures verplichtingen / offerte-matching (04-09): hergebruik van de documenten-/auth-fixtures
(administratie, Beheerder, gescoopte boekhouder, tmp-opslag) + seeds voor vendor_cache/project_cache
en helpers om een verplichting-document (offerte) door de bestaande accorderingsflow te duwen."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.documenten import service as documenten_service
from app.documenten.models import DocumentSoort
from app.documenten.storage import LokaleBestandsopslag
from app.verplichting import service as verplichting_service
from tests.accordering.conftest import maak_accordeur  # noqa: F401 — her-exporteren
from tests.documenten.conftest import (  # noqa: F401 — fixtures her-exporteren
    _opslag_naar_tmp,
    actieve_gebruiker,
    administratie_id,
    beheerder_id,
    gescoopte_gebruiker,
    opslag,
)
from tests.intake.conftest import (  # noqa: F401 — intake-fixtures voor de routing-test
    administratie_heet_blow,
    intake_ai_aan,
)

VENDOR_ID = uuid.UUID("cafe0000-1111-2222-3333-444444444444")
VENDOR_2_ID = uuid.UUID("cafe0000-1111-2222-3333-555555555555")
OFFERTEBEDRAG = Decimal("48500.00")


def seed_vendor(admin_engine: Engine, aid: uuid.UUID, vendor_id: uuid.UUID, naam: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, :naam, '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": vendor_id, "aid": aid, "naam": naam},
        )


def seed_project(admin_engine: Engine, aid: uuid.UUID, naam: str, *, actief: bool = True) -> uuid.UUID:
    pid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_cache (id, administratie_id, naam, is_actief, brondata) "
                "VALUES (:id, :aid, :naam, :actief, '{}')"
            ),
            {"id": pid, "aid": aid, "naam": naam, "actief": actief},
        )
    return pid


def document_status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


@pytest.fixture
def vendors(admin_engine: Engine, administratie_id: uuid.UUID) -> None:  # noqa: F811
    seed_vendor(admin_engine, administratie_id, VENDOR_ID, "Confide Bouw B.V.")
    seed_vendor(admin_engine, administratie_id, VENDOR_2_ID, "GNM Dakwerken B.V.")


@pytest.fixture
def project_id(admin_engine: Engine, administratie_id: uuid.UUID) -> uuid.UUID:  # noqa: F811
    return seed_project(admin_engine, administratie_id, "26140 Koningstraat (Confide)")


def upload_verplichting(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,  # noqa: F811
    bestandsnaam: str = "offerte-26140.pdf",
) -> uuid.UUID:
    """Verplichting-document via de normale upload-route (AI staat in tests uit → de extractie
    wordt zichtbaar overgeslagen en het document landt op te_controleren)."""
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=bestandsnaam,
        inhoud=f"%PDF-1.4 offerte {bestandsnaam}".encode(),
        actor_id=actor_id,
        opslag=opslag,
        soort=DocumentSoort.VERPLICHTING,
    )
    return resultaat.document_id


def sla_offerte_op(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    vendor_id: uuid.UUID = VENDOR_ID,
    project_id: uuid.UUID | None = None,
    offertenummer: str | None = "26140-OFF-01",
    totaalbedrag_excl: Decimal | None = OFFERTEBEDRAG,
    datum: date | None = date(2026, 9, 1),
    geldig_tot: date | None = date(2026, 12, 31),
    soort_label: str | None = "offerte",
    omschrijving: str | None = "Verbouwing Koningstraat",
) -> verplichting_service.VerplichtingVoorstel:
    return verplichting_service.sla_voorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        soort_label=soort_label,
        vendor_id=vendor_id,
        project_id=project_id,
        offertenummer=offertenummer,
        datum=datum,
        totaalbedrag_excl=totaalbedrag_excl,
        geldig_tot=geldig_tot,
        omschrijving=omschrijving,
    )


def laat_accorderen(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    document_id: uuid.UUID,
    kantoor_id: uuid.UUID,
    accordeur_id: uuid.UUID,
) -> accordering_service.AkkoordResultaat:
    """Aanbieden (kantoor) + akkoord (accordeur) → status geaccordeerd, goedgekeurd bedrag vast."""
    accordering_service.bied_ter_accordering_aan(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=kantoor_id,
        actor_rol="boekhouding",
    )
    return accordering_service.geef_akkoord(
        administratie_id=administratie_id, document_id=document_id, actor_id=accordeur_id
    )


@pytest.fixture
def geaccordeerde_offerte(offerte_via_accordering: uuid.UUID) -> uuid.UUID:
    """Alias: de volledig doorlopen offerte MÉT de klant-accorderingspoort nog aan."""
    return offerte_via_accordering


@pytest.fixture
def offerte_via_accordering(
    admin_engine: Engine,
    administratie_id: uuid.UUID,  # noqa: F811
    beheerder_id: uuid.UUID,  # noqa: F811
    gescoopte_gebruiker: uuid.UUID,  # noqa: F811
    opslag: LokaleBestandsopslag,  # noqa: F811
    vendors: None,
    project_id: uuid.UUID,
) -> uuid.UUID:
    """Volledig doorlopen offerte: € 48.500 excl. op project 26140, één accorderingslaag, akkoord."""
    accordeur = maak_accordeur(admin_engine, beheerder_id, administratie_id, "J. de Groot")
    accordering_service.instellingen_opslaan(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        actor_rol="beheerder",
        ingeschakeld=True,
        lagen=[accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)],
    )
    document_id = upload_verplichting(
        administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
    )
    sla_offerte_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=gescoopte_gebruiker,
        project_id=project_id,
    )
    laat_accorderen(
        administratie_id=administratie_id,
        document_id=document_id,
        kantoor_id=gescoopte_gebruiker,
        accordeur_id=accordeur,
    )
    return document_id
