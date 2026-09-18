"""Aftrek-uitgesloten grootboekrekeningen (BUA, Peter 18-09, migratie 0163): Beheerder-only GET/PUT
`/administraties/{id}/btw-aftrek-uitgesloten`, deterministisch voorstel (naam + RLZ-default 0 %/geen), exacte set zetten
mét audit oud→nieuw, onbekende rekening = 422; niets wordt stil aangezet."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import btw_aftrek
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.main import app
from app.security.tokens import create_access_token
from app.sync.models import TaxRateCache

client = TestClient(app)
NUL_ID = uuid.UUID("55555555-0000-0000-0000-000000000010")
HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000002")
GB_4510 = uuid.UUID("44444444-0000-0000-0000-000000004510")
GB_4520 = uuid.UUID("44444444-0000-0000-0000-000000004520")
GB_4404 = uuid.UUID("44444444-0000-0000-0000-000000004404")
GB_0100 = uuid.UUID("44444444-0000-0000-0000-000000000100")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def rekeningen(administratie_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        session.add(
            TaxRateCache(
                id=NUL_ID, administratie_id=administratie_id, naam="NL, Nul", percentage=Decimal("0"), brondata={}
            )
        )
        session.add(
            TaxRateCache(
                id=HOOG_ID,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.21"),
                brondata={},
            )
        )
        for ledger_id, code, naam, soort, default in (
            (GB_4510, "4510", "Representatiekosten", 2, NUL_ID),  # voorstel: naam + default 0 %
            (GB_4520, "4520", "Relatiegeschenken", 2, None),  # voorstel: naam, geen default
            (GB_4404, "4404", "Kosten mobiele telefonie", 2, HOOG_ID),  # geen voorstel: naam past niet
            (GB_0100, "0100", "Kantine-inventaris", 3, None),  # geen voorstel: geen 4xxx-kostenrekening
        ):
            session.add(
                Grootboekrekening(
                    ledger_id=ledger_id,
                    administratie_id=administratie_id,
                    code=code,
                    naam=naam,
                    soort=soort,
                    is_totaalrekening=False,
                    standaard_taxrate_id=default,
                )
            )


def _audit(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple[dict, dict]]:
    with admin_engine.connect() as conn:
        return [
            (r.oude_waarde, r.nieuwe_waarde)
            for r in conn.execute(
                text(
                    "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE record_id = :id "
                    "AND actie = 'btw_aftrek_uitgesloten_gewijzigd' ORDER BY tijdstip"
                ),
                {"id": administratie_id},
            )
        ]


def test_is_voorstel_pure_regel() -> None:
    assert btw_aftrek.is_voorstel(
        code="4510", naam="Representatiekosten", soort=2, standaard_percentage=Decimal("0"), heeft_default=True
    )
    assert btw_aftrek.is_voorstel(
        code="4520", naam="Relatiegeschenken", soort=2, standaard_percentage=None, heeft_default=False
    )
    assert btw_aftrek.is_voorstel(
        code="4530", naam="Personeelsvoorzieningen", soort=2, standaard_percentage=None, heeft_default=False
    )
    assert not btw_aftrek.is_voorstel(
        code="4510", naam="Representatiekosten", soort=2, standaard_percentage=Decimal("0.21"), heeft_default=True
    )
    assert not btw_aftrek.is_voorstel(
        code="4404", naam="Kosten mobiele telefonie", soort=2, standaard_percentage=Decimal("0"), heeft_default=True
    )
    assert not btw_aftrek.is_voorstel(
        code="0100", naam="Kantine", soort=3, standaard_percentage=None, heeft_default=False
    )


class TestRoutes:
    def test_get_toont_kostenrekeningen_met_voorstel_niets_aangezet(
        self, rekeningen, administratie_id, beheerder_id
    ) -> None:
        resp = client.get(
            f"/administraties/{administratie_id}/btw-aftrek-uitgesloten", headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        per_code = {r["code"]: r for r in data["rekeningen"]}
        assert set(per_code) == {"4510", "4520", "4404"}  # 0100 is geen kostenrekening
        assert per_code["4510"]["voorstel"] is True and per_code["4510"]["uitgesloten"] is False
        assert per_code["4520"]["voorstel"] is True and per_code["4404"]["voorstel"] is False
        assert per_code["4510"]["standaard_naam"] == "NL, Nul"
        assert (data["aantal_uitgesloten"], data["aantal_voorstel"]) == (0, 2)

    def test_put_zet_exacte_set_met_audit(self, rekeningen, administratie_id, beheerder_id, admin_engine) -> None:
        hdr = _bearer(beheerder_id, rol="beheerder")
        resp = client.put(
            f"/administraties/{administratie_id}/btw-aftrek-uitgesloten",
            json={"ledger_ids": [str(GB_4510), str(GB_4404)]},
            headers=hdr,
        )
        assert resp.status_code == 200, resp.text
        per_code = {r["code"]: r for r in resp.json()["rekeningen"]}
        assert (
            per_code["4510"]["uitgesloten"] and per_code["4404"]["uitgesloten"] and not per_code["4520"]["uitgesloten"]
        )
        assert per_code["4510"]["gezet_op"] is not None
        # Tweede PUT: 4404 eruit, 4520 erin — oud→nieuw in het audit_event mét codes.
        resp = client.put(
            f"/administraties/{administratie_id}/btw-aftrek-uitgesloten",
            json={"ledger_ids": [str(GB_4510), str(GB_4520)]},
            headers=hdr,
        )
        assert resp.status_code == 200
        assert _audit(admin_engine, administratie_id) == [
            ({"codes": []}, {"codes": ["4404", "4510"]}),
            ({"codes": ["4404", "4510"]}, {"codes": ["4510", "4520"]}),
        ]
        # Idempotent: dezelfde set nog eens = geen nieuw audit-event.
        client.put(
            f"/administraties/{administratie_id}/btw-aftrek-uitgesloten",
            json={"ledger_ids": [str(GB_4520), str(GB_4510)]},
            headers=hdr,
        )
        assert len(_audit(admin_engine, administratie_id)) == 2
        with scoped_session(administratie_id) as session:
            assert session.get(Grootboekrekening, (GB_4404, administratie_id)).btw_aftrek_uitgesloten is False

    def test_onbekende_rekening_422_en_boekhouding_403(
        self, rekeningen, administratie_id, beheerder_id, gescoopte_gebruiker
    ) -> None:
        resp = client.put(
            f"/administraties/{administratie_id}/btw-aftrek-uitgesloten",
            json={"ledger_ids": [str(uuid.uuid4())]},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 422
        resp = client.get(
            f"/administraties/{administratie_id}/btw-aftrek-uitgesloten",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403
