"""Fixtures voor de VASTLY-WAARBORG-route (§2d-waarborgroute DEFINITIEF v1.11, blok E)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.omzet.conftest import FakeOmzetClient, boeken_aan  # noqa: F401

WAARBORG_LEDGER_ID = uuid.UUID("55555555-5555-5555-5555-555555550204")
TEGENREKENING_LEDGER_ID = uuid.UUID("55555555-5555-5555-5555-555555552050")
BERICHT_ID = uuid.UUID("7d444840-9dc0-11d1-b245-5ffdce74fad2")


def bouw_waarborg_xml(
    *,
    bericht_id: uuid.UUID | str | None = BERICHT_ID,
    verhuurder: str | None = "Rubicon Investments B.V.",
    rlz_admin_id: str | None = "be5e66b3-b38c-4927-85c1-670490f16e3a",
    contract_referentie: str | None = "CT-2026-0042",
    huurder: str | None = "J. de Tester",
    bedrag: str | None = "1500.00",
    richting: str | None = "ontvangst",
    datum: str | None = "2026-08-01",
    balans_gb_code: str | None = "0204",
    versie: str = "1.0",
) -> bytes:
    """Bericht exact in de v1.11-elementvorm (app/documenten/waarborg_xml.py). Elk veld is
    weglaatbaar (None) voor de failsafe-tests."""

    def _el(naam: str, waarde: str | None, attrs: str = "") -> str:
        return f"<{naam}{attrs}>{waarde}</{naam}>" if waarde is not None else ""

    admin_attr = f' rlzAdminId="{rlz_admin_id}"' if rlz_admin_id else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<VastlyWaarborg versie="{versie}">
  {_el("BerichtId", str(bericht_id) if bericht_id else None)}
  {_el("VerhuurderEntiteit", verhuurder, admin_attr)}
  {_el("ContractReferentie", contract_referentie)}
  {_el("Huurder", huurder)}
  {_el("Bedrag", bedrag)}
  {_el("Richting", richting)}
  {_el("Datum", datum)}
  {_el("BalansGbCode", balans_gb_code)}
</VastlyWaarborg>"""
    return xml.encode()


@pytest.fixture
def administratie_heet_rubicon(administratie_id: uuid.UUID, admin_engine: Engine) -> uuid.UUID:  # noqa: F811
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET naam = 'Rubicon Investments B.V.' WHERE id = :id"),
            {"id": administratie_id},
        )
    return administratie_id


@pytest.fixture
def waarborg_rekeningschema(administratie_id: uuid.UUID) -> None:  # noqa: F811
    """0204 (waarborg-balansrekening, §6.4) + een tegenrekening (kruisposten-achtig)."""
    with scoped_session(administratie_id) as session:
        session.add(
            Grootboekrekening(
                ledger_id=WAARBORG_LEDGER_ID, administratie_id=administratie_id,
                code="0204", naam="Waarborgsommen", soort=3, is_totaalrekening=False,
            )
        )
        session.add(
            Grootboekrekening(
                ledger_id=TEGENREKENING_LEDGER_ID, administratie_id=administratie_id,
                code="2050", naam="Kruisposten", soort=3, is_totaalrekening=False,
            )
        )
