# ruff: noqa: F811 — pytest-fixtures als parameters
"""B3-poort in het factuur-autoboekpad (blok A bundel 10-09 roept, blok B bouwt): de AI-plausibiliteitstoets is een
extra POORT vlak vóór `boek_document` — 'plausibel'/'uit' → boeken, 'twijfel' → zichtbaar geweigerd (audit
`autoboeken_geweigerd` mét de reden, categoriseerbaar als twijfel). Blok 4 (10-09 avond, besluit Peter): 'overgeslagen'
(technische uitval) → WÉL boeken, mét `zonder_ai_toets` + oorzaak in het GEBOEKT-overgang-detail en audit
`automatisch_geboekt_zonder_ai_toets` — de uitgebreide uitval-tests staan in tests/aitoets/test_uitval_doorlopen.py."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.aitoets import plausibiliteit
from app.documenten import boeken
from app.documenten.storage import LokaleBestandsopslag
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_autoboeken import (  # noqa: F401
    _audit_redenen,
    _status,
    _upload,
    bevestigd_geheugen,
    boeken_aan,
    optin_aan,
    vendor_bouwmaat,
)


@pytest.mark.parametrize(
    "uitkomst,reden,verwacht_status",
    [
        ("twijfel", "omschrijving 'advies' past niet bij GB 4400 inhuur", "te_controleren"),
        ("overgeslagen", "api_key — ontbreekt", "geboekt"),
        ("overgeslagen", "avg_gate — intake-AI staat uit", "geboekt"),
        ("plausibel", "past bij 12 eerdere boekingen", "geboekt"),
        ("uit", "setting uit", "geboekt"),
    ],
)
def test_b3_poort_bepaalt_of_het_autoboekpad_boekt(
    monkeypatch: pytest.MonkeyPatch,
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
    boeken_aan: None,
    optin_aan: None,
    bevestigd_geheugen: None,
    uitkomst: str,
    reden: str,
    verwacht_status: str,
) -> None:
    aanroepen: list[dict] = []

    def stub(*, administratie_id, document_id, invoer_velden):  # noqa: ANN001
        aanroepen.append(invoer_velden)
        oorzaak = reden.split(" — ")[0] if uitkomst == "overgeslagen" else None
        return plausibiliteit.PlausibiliteitUitkomst(uitkomst, reden, oorzaak=oorzaak)

    monkeypatch.setattr(plausibiliteit, "toets_factuur_autoboeking", stub)
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
    assert _status(admin_engine, document_id) == verwacht_status
    assert len(aanroepen) == 1 and aanroepen[0]["regels"] and aanroepen[0]["regels"][0]["ledger_id"]
    redenen = _audit_redenen(admin_engine, document_id)
    if verwacht_status == "geboekt":
        assert redenen == []
        with admin_engine.connect() as conn:
            detail = conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND naar_status = 'geboekt'"
                ),
                {"id": document_id},
            ).scalar_one()
            zonder = conn.execute(
                text(
                    "SELECT nieuwe_waarde->>'oorzaak' FROM platform.audit_event "
                    "WHERE actie = 'automatisch_geboekt_zonder_ai_toets' AND record_id = :id"
                ),
                {"id": document_id},
            ).all()
        if uitkomst == "overgeslagen":
            assert detail["zonder_ai_toets"] is True and detail["ai_toets_oorzaak"] == reden.split(" — ")[0]
            assert [r[0] for r in zonder] == [reden.split(" — ")[0]]
        else:
            assert "zonder_ai_toets" not in detail and zonder == []
    else:
        assert redenen == [f"AI-plausibiliteitstoets: {uitkomst} — {reden}"]
        from app.reconciliatie import automatiseringen as auto

        assert auto.categoriseer_reden(redenen[0]) == auto.TWIJFEL
