# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok 3.2 vervolgrun 10-09 avond (besluit Peter): de platformbrede opt-out van de factuur-AI-toets
(`boeken_instelling.ai_toets_facturen_ingeschakeld` = UIT) is niet meer stil — (1) het GEBOEKT-overgang-detail draagt
`ai_toets_uit` (tijdlijn) en de lijst-DTO de chip "AI-toets uit (platform)", (2) het audit `automatisch_geboekt` draagt
`ai_toets_uit`, (3) teller `ai_toets_uit` in de automatiseringen met (4) een LET-OP "AI-toets staat platformbreed uit
sinds <datum>" mét deeplink naar de schakelaar — óók bij 0 boekingen. Schakelaar AAN = teller uit, geen LET-OP."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from app.aitoets import plausibiliteit as pl
from app.documenten import boeken, service
from app.documenten.storage import LokaleBestandsopslag
from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import teksten
from app.reconciliatie.run import Bevinding, is_beheer_signaal, is_regressie
from tests.aitoets.stub import StubPlausibiliteitClient, zet_ai_toets_stub, zet_intake_ai
from tests.aitoets.test_uitval_doorlopen import _automatisch_geboekt_audit, _geboekt_detail, _teller
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

NU = datetime(2026, 9, 10, 20, 0, tzinfo=UTC)
UIT_SINDS = datetime(2026, 9, 9, 8, 30, tzinfo=UTC)


def _zet_ai_toets_facturen(admin_engine: Engine, aan: bool) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE platform.boeken_instelling SET ai_toets_facturen_ingeschakeld = :aan, gewijzigd_op = :op "
                "WHERE singleton = true"
            ),
            {"aan": aan, "op": UIT_SINDS},
        )


@pytest.mark.afwezig_pad("boeken_instelling.ai_toets_facturen_ingeschakeld")
def test_factuur_autoboeken_met_toets_uit_boekt_door_en_is_zichtbaar(
    monkeypatch: pytest.MonkeyPatch,
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
    boeken_aan: None,
    optin_aan: None,
    bevestigd_geheugen: None,
) -> None:
    zet_intake_ai(admin_engine, True)
    _zet_ai_toets_facturen(admin_engine, False)
    stub = zet_ai_toets_stub(monkeypatch, StubPlausibiliteitClient(standaard=("twijfel", "zou blokkeren als hij liep")))
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())

    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)

    assert _status(admin_engine, document_id) == "geboekt"
    assert _audit_redenen(admin_engine, document_id) == []
    assert stub.aanroepen == []  # toets uit = geen AI-call
    detail = _geboekt_detail(admin_engine, document_id)
    assert detail["automatisch_geboekt"] is True and detail["ai_toets_uit"] is True
    assert "zonder_ai_toets" not in detail  # opt-out ≠ uitval
    geboekt = _automatisch_geboekt_audit(admin_engine, document_id)
    assert geboekt["ai_toets_uit"] is True and geboekt["zonder_ai_toets"] is False
    rij = next(
        i
        for i in service.lijst_documenten(administratie_id=administratie_id, toon_afgehandeld=True)
        if i.document.id == document_id
    )
    assert rij.automatisch_geboekt is True and rij.ai_toets_uit is True and rij.zonder_ai_toets is False


def test_uitkomst_uit_is_geen_zonder_ai_toets() -> None:
    uit = pl.PlausibiliteitUitkomst(pl.UITKOMST_UIT, "AI-toets facturen staat platformbreed uit")
    assert uit.ai_toets_uit and not uit.zonder_ai_toets and uit.boeken_toegestaan
    over = pl.PlausibiliteitUitkomst(pl.UITKOMST_OVERGESLAGEN, "api_key — geen sleutel", oorzaak="api_key")
    assert over.zonder_ai_toets and not over.ai_toets_uit


def _geboekt_feit(aid: uuid.UUID, uur: int, *, ai_toets_uit: bool) -> auto.AuditFeit:
    return auto.AuditFeit(
        "automatisch_geboekt",
        NU - timedelta(hours=uur),
        aid,
        {
            "bron": "leverancier_opt_in",
            "zonder_ai_toets": False,
            "ai_toets_oorzaak": None,
            "ai_toets_uit": ai_toets_uit,
        },
    )


class TestTeller:
    def test_opt_out_actief_telt_boekingen_en_zet_platformbrede_let_op(self) -> None:
        a = uuid.uuid4()
        f = auto.Feiten(
            administraties={a: "BLOW"},
            ai_toets_facturen_aan=False,
            ai_toets_facturen_gewijzigd_op=UIT_SINDS,
            audit=[
                _geboekt_feit(a, 1, ai_toets_uit=True),
                _geboekt_feit(a, 2, ai_toets_uit=True),
                _geboekt_feit(a, 3, ai_toets_uit=False),  # gewone automatische boeking (toets liep) telt niet
                _geboekt_feit(a, 40, ai_toets_uit=True),  # buiten het etmaal, binnen de week
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        t = _teller(tellers, auto.AI_TOETS_UIT)
        assert t.stand == "aan" and "sinds 09-09-2026" in (t.stand_detail or "")
        assert (t.dag.gedaan, t.week.gedaan) == (2, 3)
        assert t.detail == {"uit_sinds": UIT_SINDS.isoformat(), "factuur_24u": 2}
        [hv] = t.harde_voorwaarden
        assert (hv.categorie, hv.aantal, hv.administratie_id, hv.doel_pad) == (
            auto.TOETS_UIT,
            2,
            None,
            "/instellingen/boeken",
        )
        # De gewone inkoop-teller telt alle drie de boekingen van het etmaal (geen dubbeltelling elders).
        assert _teller(tellers, auto.AUTOBOEK_INKOOP).dag.gedaan == 3
        [bev] = [
            x for x in auto.bevindingen(tellers, namen=f.administraties) if x["detail"]["automatisering"] == t.sleutel
        ]
        assert bev["soort"] == "let_op" and bev["administratie_id"] is None
        assert bev["tekst"] == (
            "LET-OP     automatisering ai_toets_uit: AI-toets staat platformbreed uit sinds 09-09-2026 — "
            "2 automatische factuurboekingen zonder toets in het etmaal"
        )
        assert bev["detail"]["reden"] == auto.TOETS_UIT and bev["detail"]["doel_pad"] == "/instellingen/boeken"
        assert bev["detail"]["uit_sinds"] == UIT_SINDS.isoformat()
        # Vingerafdruk stabiel over dagen: de delta-motor mailt de keuze één keer, niet elke dag opnieuw.
        assert bev["vingerafdruk"] == auto.vingerafdruk_automatisering(
            sleutel=auto.AI_TOETS_UIT, categorie=auto.TOETS_UIT, administratie_id=None
        )

    def test_opt_out_zonder_boekingen_geeft_toch_de_let_op(self) -> None:
        a = uuid.uuid4()
        tellers = auto.bereken(
            auto.Feiten(administraties={a: "A"}, ai_toets_facturen_aan=False, ai_toets_facturen_gewijzigd_op=None),
            nu=NU,
        )
        t = _teller(tellers, auto.AI_TOETS_UIT)
        assert t.stand == "aan" and t.dag.gedaan == 0 and not t.stil
        [hv] = t.harde_voorwaarden
        assert hv.aantal == 0 and hv.voorbeeld == "sinds onbekend moment"
        [bev] = [x for x in auto.bevindingen(tellers) if x["detail"]["automatisering"] == t.sleutel]
        assert "sinds onbekend moment — 0 automatische factuurboekingen" in bev["tekst"]

    def test_schakelaar_aan_is_teller_uit_zonder_let_op(self) -> None:
        a = uuid.uuid4()
        f = auto.Feiten(administraties={a: "A"}, audit=[_geboekt_feit(a, 1, ai_toets_uit=False)])
        tellers = auto.bereken(f, nu=NU)
        t = _teller(tellers, auto.AI_TOETS_UIT)
        assert t.is_uit and t.harde_voorwaarden == [] and t.dag.gedaan == 0
        assert t.stand_detail == "AI-toets facturen staat aan"
        assert [x for x in auto.bevindingen(tellers) if x["detail"]["automatisering"] == t.sleutel] == []

    def test_json_roundtrip_regels_en_leesbare_tekst(self) -> None:
        a = uuid.uuid4()
        f = auto.Feiten(
            administraties={a: "A"},
            ai_toets_facturen_aan=False,
            ai_toets_facturen_gewijzigd_op=UIT_SINDS,
            audit=[_geboekt_feit(a, 1, ai_toets_uit=True)],
        )
        tellers = auto.bereken(f, nu=NU)
        json_ = auto.als_samenvatting(tellers, nu=NU)
        terug = auto.uit_samenvatting(json_)
        [h] = _teller(terug, auto.AI_TOETS_UIT).harde_voorwaarden
        assert (h.categorie, h.aantal, h.doel_pad) == (auto.TOETS_UIT, 1, "/instellingen/boeken")
        regel = next(r for r in auto.regels(tellers) if "AI-toets facturen uit (platform-opt-out)" in r)
        assert "LET-OP: AI-toets staat platformbreed uit sinds 09-09-2026 (1 factuurboeking(en) zonder toets)" in regel
        assert auto.regels_uit_samenvatting(json_) == auto.regels(tellers)
        # Leesbare bevinding (actiemail, kantoor — geen beheer-signaal, geen regressie).
        [bev] = [x for x in auto.bevindingen(tellers) if x["detail"]["automatisering"] == auto.AI_TOETS_UIT]
        b = Bevinding(
            blok=bev["blok"],
            soort=bev["soort"],
            administratie_id=bev["administratie_id"],
            vingerafdruk=bev["vingerafdruk"],
            tekst=bev["tekst"],
            detail=bev["detail"],
        )
        assert not is_regressie(b) and not is_beheer_signaal(b)
        lees = teksten.leesbaar(b, administratie_naam=None)
        assert "AI-toets facturen staat uit" in lees.titel
        assert "sinds 09-09-2026" in lees.wat and "1 automatische factuurboeking(en)" in lees.wat
        assert "Instellingen › Boeken" in lees.doe
        assert not teksten.bevat_technische_sleutel(lees.titel + lees.wat + lees.doe)
        assert auto.AI_TOETS_UIT in auto.VOLGORDE and auto.AI_TOETS_UIT in auto.LABEL


class TestVerzamel:
    def test_leest_de_schakelaar_uit_boeken_instelling(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        _zet_ai_toets_facturen(admin_engine, False)
        f = auto.verzamel_feiten(nu=NU, administratie_ids=[administratie_id])
        assert f.ai_toets_facturen_aan is False and f.ai_toets_facturen_gewijzigd_op == UIT_SINDS
        _zet_ai_toets_facturen(admin_engine, True)
        f = auto.verzamel_feiten(nu=NU, administratie_ids=[administratie_id])
        assert f.ai_toets_facturen_aan is True
