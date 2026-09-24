# ruff: noqa: F811 — pytest-fixtures als parameters
"""Fixtures activa fase 1: een administratie mét MVA-rekening 0107 (is_activa) + afschrijvingskostenrekening 4708, boeken aan,
een inkoopfactuur mét boekvoorstel (regel 1 op 0107 ≥ grens, regel 2 kosten) en de FakeBoekClient als RLZ-kant."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.activa import service as activa_service
from app.beheer import service as beheer_service
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, tegenboeken
from app.documenten import service as documenten_service
from app.documenten.storage import LokaleBestandsopslag
from app.sync.models import VendorCache
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient

GB_0107 = uuid.UUID("44444444-0000-0000-0000-000000000107")  # Inventaris (MVA)
GB_0108 = uuid.UUID("44444444-0000-0000-0000-000000000108")  # 4708 Afschrijving inventaris (KOSTEN, blok 6 24-09)
GB_0170 = uuid.UUID("44444444-0000-0000-0000-000000000170")  # Computers (MVA)
GB_4400 = uuid.UUID("44444444-0000-0000-0000-000000004400")  # kosten
VENDOR = uuid.UUID("33333333-0000-0000-0000-000000000901")
TAXRATE = uuid.UUID("55555555-0000-0000-0000-000000000021")


@pytest.fixture
def stamgegevens(administratie_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        for ledger_id, code, naam, soort, is_activa in (
            (GB_0107, "0107", "Inventaris", 3, True),
            (GB_0108, "4708", "Afschrijving inventaris", 2, False),
            (GB_0170, "0170", "Computers en software", 3, True),
            (GB_4400, "4400", "Inhuur onderaannemers", 2, False),
        ):
            session.add(
                Grootboekrekening(
                    ledger_id=ledger_id,
                    administratie_id=administratie_id,
                    code=code,
                    naam=naam,
                    soort=soort,
                    is_totaalrekening=False,
                    is_activa=is_activa,
                )
            )
        session.add(
            VendorCache(id=VENDOR, administratie_id=administratie_id, naam="Kantoorinrichting B.V.", brondata={})
        )


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


@pytest.fixture
def rlz(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    client = FakeBoekClient()
    for module in (boekvoorstel, boeken, tegenboeken, activa_service):
        monkeypatch.setattr(module, "client_voor_rlz_admin_id", lambda rlz_admin_id, _c=client: _c)
    return client


def regel(ledger_id: uuid.UUID, netto: str, omschrijving: str) -> boekvoorstel.BoekvoorstelRegelData:
    n = Decimal(netto)
    return boekvoorstel.BoekvoorstelRegelData(
        ledger_id=ledger_id,
        taxrate_id=TAXRATE,
        project_id=None,
        netto_bedrag=n,
        btw_bedrag=(n * Decimal("0.21")).quantize(Decimal("0.01")),
        omschrijving=omschrijving,
    )


def maak_factuur(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    regels: list[boekvoorstel.BoekvoorstelRegelData] | None = None,
    referentie: str = "KI-2026-0042",
    factuurdatum: date = date(2026, 9, 1),
) -> uuid.UUID:
    """Inkoopfactuur mét opgeslagen boekvoorstel; default regel 1 = bureau € 1.250 op 0107, regel 2 = kosten € 100."""
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"{referentie}.pdf",
        inhoud=f"%PDF-1.4 {referentie}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    regels = (
        regels
        if regels is not None
        else [regel(GB_0107, "1250.00", "Bureau Hoogte-verstelbaar"), regel(GB_4400, "100.00", "Montage")]
    )
    totaal = sum(((r.netto_bedrag or 0) + (r.btw_bedrag or 0) for r in regels), Decimal(0))
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=VENDOR,
        referentie=referentie,
        factuurdatum=factuurdatum,
        totaalbedrag=totaal,
        regels=regels,
    )
    return resultaat.document_id


@pytest.fixture
def factuur(
    stamgegevens: None, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag
) -> uuid.UUID:
    return maak_factuur(administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag)


def koppelingen(admin_engine: Engine, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT regel_volgnummer, status, herkomst, reden, rlz_fixed_asset_id, rlz_receipt_number, "
                    "afschrijving_ledger_id, termijn_maanden, methode_naam, aanschafwaarde, categorie FROM "
                    "boekhouding.activum_koppeling WHERE document_id = :d ORDER BY regel_volgnummer"
                ),
                {"d": document_id},
            ).mappings()
        ]


def tijdlijn_teksten(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            d["activum"]["tekst"]
            for d in conn.execute(
                text("SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :d ORDER BY tijdstip"),
                {"d": document_id},
            ).scalars()
            if d and "activum" in d
        ]


def audit_acties(admin_engine: Engine, *, tabel: str = "activum_koppeling") -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE tabel = :t ORDER BY tijdstip"), {"t": tabel}
            )
        ]
