from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.auth import service as auth_service
from app.documenten import boekvoorstel
from app.documenten import service as documenten_service
from app.documenten.storage import LokaleBestandsopslag
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

VENDOR_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
TOTAAL = Decimal("121.00")


def maak_accordeur(admin_engine: Engine, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, naam: str) -> uuid.UUID:  # noqa: F811
    """Actieve gebruiker met rol klant_accordeur + scope op de administratie (zelfde patroon
    als gescoopte_gebruiker in tests/documenten/conftest.py)."""
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, :naam, :mail, 'klant_accordeur', 'actief')"
            ),
            {"id": gid, "naam": naam, "mail": f"{gid}@test.local"},
        )
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=administratie_id)
    return gid


@pytest.fixture
def accordeur_1(admin_engine: Engine, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> uuid.UUID:  # noqa: F811
    return maak_accordeur(admin_engine, beheerder_id, administratie_id, "S. Bakker")


@pytest.fixture
def accordeur_2(admin_engine: Engine, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> uuid.UUID:  # noqa: F811
    return maak_accordeur(admin_engine, beheerder_id, administratie_id, "R. Jansen")


@pytest.fixture
def klaar_document(
    gescoopte_gebruiker: uuid.UUID,  # noqa: F811
    administratie_id: uuid.UUID,  # noqa: F811
    admin_engine: Engine,
    opslag: LokaleBestandsopslag,  # noqa: F811
) -> uuid.UUID:
    """Boekklaar inkoopfactuur-document (€ 121,00, vaste vendor mét cache-naam) — status
    klaar_om_te_boeken via de normale service-route."""
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, 'Energieleverancier B.V.', '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": VENDOR_ID, "aid": administratie_id},
        )
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"%PDF-1.4 testfactuur",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=VENDOR_ID,
        referentie=f"F-{resultaat.document_id}",
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=TOTAAL,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(),
                taxrate_id=uuid.uuid4(),
                project_id=None,
                netto_bedrag=Decimal("100.00"),
                btw_bedrag=Decimal("21.00"),
                omschrijving="Testregel",
            )
        ],
    )
    # De checks + failsafe-route klaarzetten gebeurt normaal in boek_document; voor de
    # accorderingstests zetten we het document expliciet boekklaar via de service-overgang.
    from app.db.session import scoped_session
    from app.documenten.models import Document, DocumentStatus
    from app.documenten.service import _schrijf_overgang

    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
        document = session.get(Document, resultaat.document_id)
        _schrijf_overgang(
            session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
        )
    return resultaat.document_id


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:  # noqa: F811
    from app.beheer import service as beheer_service

    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


def zet_schema(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    beheerder_id: uuid.UUID,  # noqa: F811
    lagen: list[accordering_service.LaagInput],
    ingeschakeld: bool = True,
) -> None:
    accordering_service.instellingen_opslaan(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        actor_rol="beheerder",
        ingeschakeld=ingeschakeld,
        lagen=lagen,
    )


def document_status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()
