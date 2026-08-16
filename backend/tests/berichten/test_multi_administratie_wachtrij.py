"""Verificatiepunt IA-verbouwing (designronde 2026-08-15): één accordeur met méérdere
administraties — de PWA-wachtrij voegt de administraties samen tot één lijst en de dagelijkse
09:00-herinnering telt over de administraties heen op tot één bericht (idempotent per accordeur
per dag, nooit één bericht per administratie)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.auth import service as auth_service
from app.berichten import herinneringen
from app.db.session import scoped_session
from app.documenten import boekvoorstel
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag

# Fixtures (accordeur_1, administratie_id, opslag, …) komen automatisch uit
# tests/berichten/conftest.py (zelfde package) — expliciete imports botsen met de
# gelijknamige testparameters (ruff F811, hygiëne-run 16-08); alleen de niet-fixture-helper
# zet_schema wordt geïmporteerd.
from tests.berichten.conftest import zet_schema
from tests.berichten.test_herinneringen import mail_log  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp  # noqa: F401

VANDAAG = date(2026, 8, 16)


@pytest.fixture
def tweede_administratie_id(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Scope-test B', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def _maak_boekklaar_document(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
    referentie: str,
) -> uuid.UUID:
    """Zelfde route als de klaar_document-fixture (tests/accordering/conftest.py), maar
    parameterizeerbaar per administratie."""
    vendor_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, 'Leverancier per admin B.V.', '{}')"
            ),
            {"id": vendor_id, "aid": administratie_id},
        )
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"{referentie}.pdf",
        inhoud=f"%PDF-1.4 {referentie}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=date(2026, 8, 1),
        totaalbedrag=Decimal("121.00"),
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
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, resultaat.document_id)
        _schrijf_overgang(session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=actor_id)
    return resultaat.document_id


@pytest.fixture
def twee_admins_bij_een_accordeur(
    admin_engine: Engine,
    beheerder_id: uuid.UUID,  # noqa: F811
    administratie_id: uuid.UUID,  # noqa: F811
    tweede_administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,  # noqa: F811
    accordeur_1: uuid.UUID,  # noqa: F811
    opslag: LokaleBestandsopslag,  # noqa: F811
) -> tuple[uuid.UUID, uuid.UUID]:
    """In béíde administraties één document ter accordering, laag 1 = dezelfde accordeur.
    Returns (document_a, document_b)."""
    # De accordeur en de aanbiedende medewerker krijgen óók scope op administratie B.
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=accordeur_1, administratie_id=tweede_administratie_id
    )
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=gescoopte_gebruiker, administratie_id=tweede_administratie_id
    )
    documenten: list[uuid.UUID] = []
    for aid, referentie in ((administratie_id, "F-ADMIN-A"), (tweede_administratie_id, "F-ADMIN-B")):
        document_id = _maak_boekklaar_document(
            administratie_id=aid,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            admin_engine=admin_engine,
            referentie=referentie,
        )
        zet_schema(
            administratie_id=aid,
            beheerder_id=beheerder_id,
            lagen=[
                accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur_1, bedrag_drempel=None)
            ],
        )
        accordering_service.bied_ter_accordering_aan(
            administratie_id=aid,
            document_id=document_id,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        documenten.append(document_id)
    return documenten[0], documenten[1]


class TestWachtrijOverAdministratiesHeen:
    def test_wachtrij_voegt_administraties_samen(
        self,
        twee_admins_bij_een_accordeur: tuple[uuid.UUID, uuid.UUID],
        administratie_id: uuid.UUID,  # noqa: F811
        tweede_administratie_id: uuid.UUID,
        accordeur_1: uuid.UUID,  # noqa: F811
    ) -> None:
        document_a, document_b = twee_admins_bij_een_accordeur
        items = accordering_service.wachtrij_voor_accordeur(
            actor_id=accordeur_1, administratie_ids=[administratie_id, tweede_administratie_id]
        )
        assert {item.document_id for item in items} == {document_a, document_b}
        assert {item.administratie_id for item in items} == {administratie_id, tweede_administratie_id}
        # Gesorteerd op aanbiedmoment (oudste eerst) — één samengevoegde lijst, geen per-admin-blokken.
        aangeboden = [item.aangeboden_op for item in items]
        assert aangeboden == sorted(aangeboden)
        # Elke rij draagt de administratienaam, zodat de PWA het onderscheid kan tonen.
        assert all(item.administratie_naam for item in items)

    def test_herinnering_telt_over_administraties_heen_en_stuurt_een_bericht(
        self,
        twee_admins_bij_een_accordeur: tuple[uuid.UUID, uuid.UUID],
        accordeur_1: uuid.UUID,  # noqa: F811
        mail_log: list[dict],  # noqa: F811
        admin_engine: Engine,
    ) -> None:
        totalen = herinneringen.open_aantallen_per_accordeur()
        assert totalen[accordeur_1] == 2
        rapport = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert rapport.verzonden_mail == 1
        onze_mails = [m for m in mail_log if "2 facturen" in m["tekst"]]
        assert len(onze_mails) == 1
        with admin_engine.connect() as conn:
            rijen = conn.execute(
                text(
                    "SELECT aantal_open FROM platform.accordeur_herinnering "
                    "WHERE gebruiker_id = :gid AND datum = :datum"
                ),
                {"gid": accordeur_1, "datum": VANDAAG},
            ).all()
        # Eén dagrij voor de accordeur (niet één per administratie), met het samengetelde aantal.
        assert [rij[0] for rij in rijen] == [2]
