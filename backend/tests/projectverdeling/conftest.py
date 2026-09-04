"""Fixtures projectverdeling (blok C 04-09): hergebruik van de documenten-/auth-fixtures (administratie,
Beheerder, gescoopte boekhouder, tmp-opslag) + seeds voor project_cache / project_regel_cache (verkoopomzet) en
een klaar boekvoorstel zónder projecten op de regels (de Floorbeheer-casus: € 2.000 excl.)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.documenten import boekvoorstel, service
from app.documenten.storage import LokaleBestandsopslag
from tests.documenten.conftest import (  # noqa: F401 — fixtures her-exporteren
    _opslag_naar_tmp,
    actieve_gebruiker,
    administratie_id,
    beheerder_id,
    gescoopte_gebruiker,
    opslag,
)

PERIODE = date(2026, 7, 1)  # omzetmaand juli 2026 (mockup-casus)


def maak_project(admin_engine: Engine, aid: uuid.UUID, naam: str, *, actief: bool = True) -> uuid.UUID:
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


def seed_omzet(
    admin_engine: Engine,
    aid: uuid.UUID,
    project_id: uuid.UUID,
    netto: str,
    datum: date,
    *,
    soort: str = "verkoop",
    verdwenen: bool = False,
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_regel_cache "
                "(id, administratie_id, rlz_document_id, soort, project_id, netto_bedrag, datum, "
                "verdwenen_uit_bron_op) "
                "VALUES (:id, :aid, :doc, :soort, :pid, :netto, :datum, CASE WHEN :verdwenen THEN now() ELSE NULL END)"
            ),
            {
                "id": uuid.uuid4(),
                "aid": aid,
                "doc": uuid.uuid4(),
                "soort": soort,
                "pid": project_id,
                "netto": netto,
                "datum": datum,
                "verdwenen": verdwenen,
            },
        )


@pytest.fixture
def projecten(admin_engine: Engine, administratie_id: uuid.UUID) -> dict[str, uuid.UUID]:  # noqa: F811
    """Drie projecten mét juli-omzet (60/25/15 %), één zonder omzet, één OVH mét omzet, één inactief mét omzet."""
    p = {
        "eindhoven": maak_project(admin_engine, administratie_id, "26120 Eindhoven (BAM)"),
        "tilburg": maak_project(admin_engine, administratie_id, "26127 Tilburg (Heijmans)"),
        "venlo": maak_project(admin_engine, administratie_id, "26131 Venlo (Dura)"),
        "omzetloos": maak_project(admin_engine, administratie_id, "26140 Weert (nieuw)"),
        "ovh": maak_project(admin_engine, administratie_id, "OVH · Overhead / algemene kosten"),
        "inactief": maak_project(admin_engine, administratie_id, "25099 Oud project", actief=False),
    }
    seed_omzet(admin_engine, administratie_id, p["eindhoven"], "6000.00", date(2026, 7, 3))
    seed_omzet(admin_engine, administratie_id, p["tilburg"], "2500.00", date(2026, 7, 15))
    seed_omzet(admin_engine, administratie_id, p["venlo"], "1500.00", date(2026, 7, 31))
    seed_omzet(admin_engine, administratie_id, p["ovh"], "900.00", date(2026, 7, 10))
    seed_omzet(admin_engine, administratie_id, p["inactief"], "800.00", date(2026, 7, 10))
    # Buiten de periode + verdwenen + inkoop-regel: mogen nooit meetellen.
    seed_omzet(admin_engine, administratie_id, p["eindhoven"], "99999.00", date(2026, 8, 1))
    seed_omzet(admin_engine, administratie_id, p["eindhoven"], "99999.00", date(2026, 6, 30))
    seed_omzet(admin_engine, administratie_id, p["tilburg"], "5000.00", date(2026, 7, 5), verdwenen=True)
    seed_omzet(admin_engine, administratie_id, p["venlo"], "7000.00", date(2026, 7, 5), soort="inkoop")
    return p


def regel(**overrides) -> boekvoorstel.BoekvoorstelRegelData:
    basis = dict(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("2000.00"),
        btw_bedrag=Decimal("420.00"),
        omschrijving="Vloeronderhoud kantoor",
    )
    basis.update(overrides)
    return boekvoorstel.BoekvoorstelRegelData(**basis)


@pytest.fixture
def vendor_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def document_zonder_project(
    gescoopte_gebruiker: uuid.UUID,  # noqa: F811
    administratie_id: uuid.UUID,  # noqa: F811
    opslag: LokaleBestandsopslag,  # noqa: F811
    vendor_id: uuid.UUID,
) -> uuid.UUID:
    """Floorbeheer-casus: één regel € 2.000 excl. zonder project."""
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="floorbeheer-2026-07.pdf",
        inhoud=b"%PDF-1.4 testfactuur",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=vendor_id,
        referentie="FB-2026-0731",
        factuurdatum=date(2026, 7, 31),
        totaalbedrag=Decimal("2420.00"),
        regels=[regel()],
    )
    return resultaat.document_id
