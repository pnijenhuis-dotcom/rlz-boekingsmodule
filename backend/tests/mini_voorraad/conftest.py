# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/voorraad)
"""Fixtures mini-voorraad (blok F 06-09): hergebruik van de documenten-/auth-fixtures + een documentbouwer die een
inkoopfactuur mét boekvoorstel én veldvoorstel (regels mét hoeveelheid/artikelcode/eenheid) klaarzet, de opt-in-
schakelaars en de FakeBoekClient (mét ingediende Q3-aangifte zodat het tegenboek-pad open staat)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, tegenboeken
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentGebeurtenis
from app.documenten.storage import LokaleBestandsopslag
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.projectverdeling.conftest import maak_project  # noqa: F401

VENDOR_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
VENDOR_NAAM = "Huvanco B.V."
ANDERE_VENDOR_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
AANGIFTE_Q3_INGEDIEND = {"Status": 2, "StartDate": "2026-07-01T00:00:00", "Date": "2026-09-30T00:00:00"}
FACTUURDATUM = date(2026, 7, 1)


def regel(o: str, h: str | None, a: str | None = None, e: str | None = "st", n: str = "100.00") -> dict:
    """Veldvoorstel-regel zoals de extractie 'm schrijft (zelfde sleutels als tests/voorraad)."""
    return {"omschrijving": o, "hoeveelheid": h, "netto_bedrag": n, "eenheid": e, "stuksprijs": None, "artikelcode": a}


def _boekregel() -> boekvoorstel.BoekvoorstelRegelData:
    return boekvoorstel.BoekvoorstelRegelData(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"),
        omschrijving="Speciale producten",
    )


def seed_vendor(admin_engine: Engine, aid: uuid.UUID, vendor_id: uuid.UUID, naam: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, :naam, '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": vendor_id, "aid": aid, "naam": naam},
        )


def maak_document(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    regels: list[dict],
    vendor_id: uuid.UUID = VENDOR_ID,
    referentie: str | None = None,
    naam: str = "factuur.pdf",
) -> uuid.UUID:
    """Inkoopfactuur klaar om te boeken: boekvoorstel (één boekregel) + veldvoorstel mét de productregels."""
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=f"%PDF-1.4 {naam} {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie or f"F-{resultaat.document_id}",
        factuurdatum=FACTUURDATUM,
        totaalbedrag=Decimal("121.00"),
        regels=[_boekregel()],
    )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, resultaat.document_id)
        assert document is not None
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=resultaat.document_id,
                van_status=document.status,
                naar_status=document.status,
                actor_id=actor_id,
                detail={"veldvoorstel": {"bron": "ai", "leverancier_naam": VENDOR_NAAM, "regels": regels}},
            )
        )
    return resultaat.document_id


def standen(admin_engine: Engine, aid: uuid.UUID) -> dict[str, Decimal]:
    """Stand per product (omschrijving → Σ aantal) als schema-owner — de toetsbron náást de API."""
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT p.omschrijving, COALESCE(SUM(m.aantal), 0) FROM mi.mini_product p "
                "LEFT JOIN mi.mini_voorraad_mutatie m ON m.product_id = p.id "
                "WHERE p.administratie_id = :aid GROUP BY p.omschrijving"
            ),
            {"aid": aid},
        ).all()
    return {o: Decimal(s) for o, s in rijen}


def mutaties(admin_engine: Engine, aid: uuid.UUID, soort: str | None = None) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT m.soort, m.aantal, m.datum, m.document_id, m.boek_cyclus, m.regel_volgnummer, "
                "m.project_id, m.gemeld_door, p.omschrijving FROM mi.mini_voorraad_mutatie m "
                "JOIN mi.mini_product p ON p.id = m.product_id "
                "WHERE m.administratie_id = :aid AND (CAST(:soort AS text) IS NULL OR m.soort = :soort) "
                "ORDER BY m.aangemaakt_op, m.soort, m.regel_volgnummer NULLS LAST, m.id"
            ),
            {"aid": aid, "soort": soort},
        ).mappings()
        return [dict(r) for r in rijen]


def tijdlijn_details(admin_engine: Engine, document_id: uuid.UUID, sleutel: str) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id AND detail ? :sleutel "
                "ORDER BY tijdstip"
            ),
            {"id": document_id, "sleutel": sleutel},
        ).scalars()
        return [r[sleutel] for r in rijen]


def audit_acties(admin_engine: Engine, actie: str) -> int:
    with admin_engine.connect() as conn:
        return int(
            conn.execute(text("SELECT count(*) FROM platform.audit_event WHERE actie = :a"), {"a": actie}).scalar_one()
        )


@pytest.fixture
def mini_voorraad_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    beheer_service.zet_mini_voorraad_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    seed_vendor(admin_engine, administratie_id, VENDOR_ID, VENDOR_NAAM)
    seed_vendor(admin_engine, administratie_id, ANDERE_VENDOR_ID, "Wola b.v.")


@pytest.fixture
def boeken_aan_zonder_mini(beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    seed_vendor(admin_engine, administratie_id, VENDOR_ID, VENDOR_NAAM)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    fake = FakeBoekClient(aangiften=[AANGIFTE_Q3_INGEDIEND])
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    monkeypatch.setattr(tegenboeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    return fake


@pytest.fixture
def actief_project(admin_engine: Engine, administratie_id: uuid.UUID) -> uuid.UUID:
    return maak_project(admin_engine, administratie_id, "26127 Tilburg (Heijmans)")


@pytest.fixture
def inactief_project(admin_engine: Engine, administratie_id: uuid.UUID) -> uuid.UUID:
    return maak_project(admin_engine, administratie_id, "25099 Oud project", actief=False)
