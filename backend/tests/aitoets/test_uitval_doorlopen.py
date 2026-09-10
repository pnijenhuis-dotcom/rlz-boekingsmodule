# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok 4 vervolgrun 10-09 avond (besluit Peter 10-09): AI-plausibiliteitstoets — uitval = doorlopen, zichtbaar.

Vóór blok 4 betekende `overgeslagen` (AVG-gate uit, geen API-key, kostengrens bereikt, AI-fout/timeout) "niet boeken",
waardoor élke automatische factuur- én bankboeking stilviel op een technische storing. Nu: de deterministische poorten
blijven de eis; valt de AI-toets technisch uit, dan boekt het systeem WÉL — mét (1) chip/veld "zonder AI-toets",
(2) audit `ai_plausibiliteitstoets` mét oorzaak + `automatisch_geboekt_zonder_ai_toets` ná de geslaagde boeking,
(3) teller `ai_toets_overgeslagen` (per dag, per oorzaak) en (4) een LET-OP "controleer steekproefsgewijs" mét deeplink.
`twijfel` blijft NIET boeken; `plausibel` onveranderd. Bank-kant: tests/bank/test_boeken.py; hier de factuur-kant
(echte `toets_factuur_autoboeking` mét stub-client), de reconciliatie-teller/LET-OP en de leesbare tekst."""

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
from tests.aitoets.stub import (
    StubPlausibiliteitClient,
    audit_toetsen,
    zet_ai_toets_geen_key,
    zet_ai_toets_stub,
    zet_intake_ai,
)
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


def _uur(n: int) -> datetime:
    return NU - timedelta(hours=n)


# --- factuur-autoboekpad: echte toets, uitval = geboekt zonder AI-toets --------------------------------------------


def _geboekt_detail(admin_engine: Engine, document_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT detail FROM boekhouding.document_gebeurtenis "
                "WHERE document_id = :id AND naar_status = 'geboekt'"
            ),
            {"id": document_id},
        ).scalar_one()


def _zonder_toets_audit(admin_engine: Engine, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event "
                    "WHERE actie = 'automatisch_geboekt_zonder_ai_toets' AND tabel = 'document' AND record_id = :id"
                ),
                {"id": document_id},
            ).all()
        ]


def _automatisch_geboekt_audit(admin_engine: Engine, document_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'automatisch_geboekt' AND record_id = :id"
            ),
            {"id": document_id},
        ).scalar_one()


@pytest.mark.afwezig_pad("intake_instelling.ai_ingeschakeld")
@pytest.mark.parametrize(
    "uitval,oorzaak",
    [("avg_gate", "avg_gate"), ("geen_key", "api_key"), ("kostengrens", "kostengrens"), ("ai_fout", "ai_fout")],
)
def test_factuur_autoboeken_boekt_door_bij_technische_uitval_van_de_toets(
    monkeypatch: pytest.MonkeyPatch,
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
    boeken_aan: None,
    optin_aan: None,
    bevestigd_geheugen: None,
    uitval: str,
    oorzaak: str,
) -> None:
    """Alle vier uitvalpaden: het document wordt GEBOEKT (harde checks + geheugen waren groen), het GEBOEKT-overgang-
    detail draagt `zonder_ai_toets` + oorzaak (tijdlijn), de lijst-DTO draagt de chip, en er staan twee audit-sporen:
    `ai_plausibiliteitstoets` (uitkomst overgeslagen, oorzaak) en `automatisch_geboekt_zonder_ai_toets`."""
    if uitval == "avg_gate":
        zet_intake_ai(admin_engine, False)
        stub = zet_ai_toets_stub(monkeypatch)
    else:
        zet_intake_ai(admin_engine, True)
        stub = None
        if uitval == "geen_key":
            zet_ai_toets_geen_key(monkeypatch)
        elif uitval == "kostengrens":
            stub = zet_ai_toets_stub(
                monkeypatch, StubPlausibiliteitClient(kostenfout="AI-maandlimiet bereikt (€ 100,00 van € 100,00)")
            )
        else:
            stub = zet_ai_toets_stub(monkeypatch, StubPlausibiliteitClient(fout="Claude API-timeout na 120s"))
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())

    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)

    assert _status(admin_engine, document_id) == "geboekt"
    assert _audit_redenen(admin_engine, document_id) == []
    if uitval == "avg_gate":
        assert stub is not None and stub.aanroepen == []  # geen byte naar de API bij AVG-gate uit
    detail = _geboekt_detail(admin_engine, document_id)
    assert detail["automatisch_geboekt"] is True and detail["zonder_ai_toets"] is True
    assert detail["ai_toets_oorzaak"] == oorzaak and str(detail["ai_toets_reden"]).startswith(oorzaak)
    toetsen = audit_toetsen(admin_engine, document_id)
    assert len(toetsen) == 1 and toetsen[0]["uitkomst"] == "overgeslagen" and toetsen[0]["oorzaak"] == oorzaak
    assert toetsen[0]["tabel"] == "document" and toetsen[0]["zonder_ai_toets"] is True
    zonder = _zonder_toets_audit(admin_engine, document_id)
    assert len(zonder) == 1 and zonder[0]["oorzaak"] == oorzaak and zonder[0]["soort"] == "factuur_autoboeking"
    assert zonder[0]["bron"] == "leverancier_opt_in"
    geboekt = _automatisch_geboekt_audit(admin_engine, document_id)
    assert geboekt["zonder_ai_toets"] is True and geboekt["ai_toets_oorzaak"] == oorzaak
    # Lijst-DTO: chip "zonder AI-toets" naast "automatisch", oorzaak als tooltip.
    rij = next(
        i
        for i in service.lijst_documenten(administratie_id=administratie_id, toon_afgehandeld=True)
        if i.document.id == document_id
    )
    assert rij.automatisch_geboekt is True and rij.zonder_ai_toets is True and rij.ai_toets_oorzaak == oorzaak


def test_factuur_twijfel_boekt_nog_steeds_niet(
    monkeypatch: pytest.MonkeyPatch,
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
    boeken_aan: None,
    optin_aan: None,
    bevestigd_geheugen: None,
) -> None:
    """Regressie: 'twijfel' is een inhoudelijk AI-oordeel, geen uitval — het document blijft te_controleren mét de
    reden in `autoboeken_geweigerd`; géén 'zonder AI-toets'-spoor."""
    zet_intake_ai(admin_engine, True)
    zet_ai_toets_stub(monkeypatch, StubPlausibiliteitClient(standaard=("twijfel", "advies op een inhuurrekening?")))
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())

    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)

    assert _status(admin_engine, document_id) == "te_controleren"
    assert _audit_redenen(admin_engine, document_id) == [
        "AI-plausibiliteitstoets: twijfel — advies op een inhuurrekening?"
    ]
    assert _zonder_toets_audit(admin_engine, document_id) == []
    rij = next(i for i in service.lijst_documenten(administratie_id=administratie_id) if i.document.id == document_id)
    assert rij.automatisch_geboekt is False and rij.zonder_ai_toets is False and rij.ai_toets_oorzaak is None


def test_factuur_plausibel_boekt_zonder_zonder_toets_spoor(
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
    zet_ai_toets_stub(monkeypatch)
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())

    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)

    assert _status(admin_engine, document_id) == "geboekt"
    detail = _geboekt_detail(admin_engine, document_id)
    assert detail["automatisch_geboekt"] is True and "zonder_ai_toets" not in detail
    assert _zonder_toets_audit(admin_engine, document_id) == []
    assert _automatisch_geboekt_audit(admin_engine, document_id)["zonder_ai_toets"] is False


# --- reconciliatie: teller `ai_toets_overgeslagen` + LET-OP ---------------------------------------------------------


def _feit(aid: uuid.UUID, uur: int, *, soort: str, oorzaak: str, reden: str | None = None) -> auto.AuditFeit:
    return auto.AuditFeit(
        "automatisch_geboekt_zonder_ai_toets",
        _uur(uur),
        aid,
        {"soort": soort, "oorzaak": oorzaak, "reden": reden or f"{oorzaak} — detail", "bron": "x"},
    )


def _teller(tellers, sleutel):  # noqa: ANN001
    return next(t for t in tellers if t.sleutel == sleutel)


class TestTeller:
    def test_teller_telt_per_oorzaak_en_soort_en_zet_let_op_met_deeplink(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        f = auto.Feiten(
            administraties={a: "Universal Steigerbouw", b: "BLOW"},
            audit=[
                _feit(a, 1, soort="bank_vaste_regel", oorzaak="avg_gate"),
                _feit(a, 2, soort="bank_historie", oorzaak="avg_gate"),
                _feit(a, 3, soort="factuur_autoboeking", oorzaak="kostengrens"),
                _feit(b, 4, soort="factuur_autoboeking", oorzaak="api_key"),
                _feit(b, 30, soort="bank_vaste_regel", oorzaak="ai_fout"),  # buiten het etmaal, binnen de week
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        t = _teller(tellers, auto.AI_TOETS_OVERGESLAGEN)
        assert t.stand == "aan" and "vangnet" in (t.stand_detail or "")
        assert (t.dag.verwacht, t.dag.gedaan) == (4, 4)
        assert {k: v for k, v in t.dag.overgeslagen.items() if v} == {"avg_gate": 2, "kostengrens": 1, "api_key": 1}
        assert (t.week.gedaan, t.week.overgeslagen["ai_fout"]) == (5, 1)
        assert t.detail == {
            "bank_24u": 2,
            "factuur_24u": 2,
            "per_oorzaak_24u": {"avg_gate": 2, "kostengrens": 1, "api_key": 1},
        }
        # LET-OP-groepen: per (administratie, soort, oorzaak) — alleen het etmaal.
        groepen = {(h.administratie_id, h.soort, h.categorie): (h.aantal, h.doel_pad) for h in t.harde_voorwaarden}
        assert groepen == {
            (a, "bank_vaste_regel", "avg_gate"): (1, f"/bank/{a}"),
            (a, "bank_historie", "avg_gate"): (1, f"/bank/{a}"),
            (a, "factuur_autoboeking", "kostengrens"): (1, f"/?administratie={a}&status=__automatisch_geboekt"),
            (b, "factuur_autoboeking", "api_key"): (1, f"/?administratie={b}&status=__automatisch_geboekt"),
        }
        bev = [
            x for x in auto.bevindingen(tellers, namen=f.administraties) if x["detail"]["automatisering"] == t.sleutel
        ]
        assert len(bev) == 4 and all(x["soort"] == "let_op" for x in bev)
        factuur_b = next(x for x in bev if x["administratie_id"] == b)
        assert factuur_b["tekst"] == (
            f"LET-OP     automatisering ai_toets_overgeslagen: 1 automatische factuurboekingen zonder AI-toets "
            f"(oorzaak api_key) in administratie {b} — controleer steekproefsgewijs"
        )
        assert factuur_b["detail"]["reden"] == auto.ZONDER_AI_TOETS and factuur_b["detail"]["oorzaak"] == "api_key"
        assert factuur_b["detail"]["doel_pad"] == f"/?administratie={b}&status=__automatisch_geboekt"
        assert factuur_b["detail"]["administratie_naam"] == "BLOW"
        # Vingerafdruk stabiel én verschillend per soort/oorzaak (de delta-motor mailt één keer per situatie).
        assert len({x["vingerafdruk"] for x in bev}) == 4
        # De bestaande poort-teller telt de toets-uitkomst niet dubbel (die komt uit `ai_plausibiliteitstoets`).
        assert _teller(tellers, auto.AI_PLAUSIBILITEIT).dag.verwacht == 0

    def test_zonder_boekingen_geen_let_op_en_teller_uit(self) -> None:
        a = uuid.uuid4()
        tellers = auto.bereken(auto.Feiten(administraties={a: "A"}), nu=NU)
        t = _teller(tellers, auto.AI_TOETS_OVERGESLAGEN)
        assert t.is_uit and t.harde_voorwaarden == [] and not t.stil
        assert t.detail == {"bank_24u": 0, "factuur_24u": 0, "per_oorzaak_24u": {}}
        assert [x for x in auto.bevindingen(tellers) if x["detail"]["automatisering"] == t.sleutel] == []
        # Een boeking van gisteren (buiten 24 u) houdt de teller aan, zonder LET-OP.
        tellers = auto.bereken(
            auto.Feiten(administraties={a: "A"}, audit=[_feit(a, 30, soort="bank_historie", oorzaak="ai_fout")]), nu=NU
        )
        t = _teller(tellers, auto.AI_TOETS_OVERGESLAGEN)
        assert t.stand == "aan" and t.harde_voorwaarden == [] and t.dag.gedaan == 0 and t.week.gedaan == 1

    def test_json_roundtrip_en_regels(self) -> None:
        a = uuid.uuid4()
        f = auto.Feiten(administraties={a: "A"}, audit=[_feit(a, 1, soort="bank_historie", oorzaak="kostengrens")])
        tellers = auto.bereken(f, nu=NU)
        json_ = auto.als_samenvatting(tellers, nu=NU)
        import json

        json.dumps(json_)
        terug = auto.uit_samenvatting(json_)
        h = _teller(terug, auto.AI_TOETS_OVERGESLAGEN).harde_voorwaarden[0]
        assert (h.soort, h.doel_pad, h.categorie, h.aantal) == ("bank_historie", f"/bank/{a}", "kostengrens", 1)
        regels = auto.regels(tellers)
        regel = next(r for r in regels if "zonder AI-toets" in r)
        assert "verwacht 1, gedaan 1, overgeslagen 1 (AI-kostengrens bereikt: 1)" in regel
        assert "LET-OP: 1× geboekt zonder AI-toets (AI-kostengrens bereikt) — controleer steekproefsgewijs" in regel
        assert auto.regels_uit_samenvatting(json_) == regels
        assert len(regels) == 1 + len(auto.VOLGORDE)

    def test_let_op_is_actiemail_niet_beheer_en_leesbaar(self) -> None:
        a = uuid.uuid4()
        f = auto.Feiten(
            administraties={a: "Universal Steigerbouw"},
            audit=[_feit(a, 1, soort="factuur_autoboeking", oorzaak="avg_gate")],
        )
        kw = next(
            x
            for x in auto.bevindingen(auto.bereken(f, nu=NU), namen=f.administraties)
            if x["detail"]["automatisering"] == auto.AI_TOETS_OVERGESLAGEN
        )
        b = Bevinding(
            blok=kw["blok"],
            soort=kw["soort"],
            administratie_id=kw["administratie_id"],
            vingerafdruk=kw["vingerafdruk"],
            tekst=kw["tekst"],
            detail=kw["detail"],
        )
        assert not is_regressie(b) and not is_beheer_signaal(b)  # kantoor-handeling → actiemail
        lees = teksten.leesbaar(b, administratie_naam="Universal Steigerbouw")
        assert lees.titel.startswith("Automatisch geboekt zonder AI-toets")
        assert (
            "1 automatische factuurboeking(en) in Universal Steigerbouw liepen door zonder AI-plausibiliteitstoets"
            in lees.wat
        )
        assert "AI staat uit (AVG-gate intake-AI)" in lees.wat and "deterministische controles waren groen" in lees.wat
        assert lees.doe.startswith("Controleer steekproefsgewijs") and "documentenlijst" in lees.doe
        assert not teksten.bevat_technische_sleutel(lees.titel + lees.wat + lees.doe)

    def test_leesbaar_bankvariant_verwijst_naar_het_bankscherm(self) -> None:
        a = uuid.uuid4()
        f = auto.Feiten(administraties={a: "BLOW"}, audit=[_feit(a, 1, soort="bank_vaste_regel", oorzaak="ai_fout")])
        kw = next(
            x
            for x in auto.bevindingen(auto.bereken(f, nu=NU), namen=f.administraties)
            if x["detail"]["automatisering"] == auto.AI_TOETS_OVERGESLAGEN
        )
        b = Bevinding(
            blok=kw["blok"],
            soort=kw["soort"],
            administratie_id=a,
            vingerafdruk=kw["vingerafdruk"],
            tekst=kw["tekst"],
            detail=kw["detail"],
        )
        lees = teksten.leesbaar(b, administratie_naam="BLOW")
        assert "bankboeking(en)" in lees.wat and "AI-fout/timeout" in lees.wat and "het bankscherm" in lees.doe

    def test_label_en_volgorde_geregistreerd(self) -> None:
        assert auto.AI_TOETS_OVERGESLAGEN in auto.VOLGORDE and auto.AI_TOETS_OVERGESLAGEN in auto.LABEL
        assert auto.VOLGORDE.index(auto.AI_PLAUSIBILITEIT) < auto.VOLGORDE.index(auto.AI_TOETS_OVERGESLAGEN)
        assert "automatisch_geboekt_zonder_ai_toets" in auto._ACTIES
        assert auto.ZONDER_AI_TOETS in auto.REDEN_LABEL and "ai_fout" in auto.REDEN_LABEL
        for oorzaak in pl.OORZAKEN_OVERGESLAGEN:
            assert oorzaak in auto.REDEN_LABEL


class TestVerzamel:
    def test_leest_het_audit_spoor_uit_de_database(self, administratie_id: uuid.UUID) -> None:
        rid = uuid.uuid4()
        pl.registreer_geboekt_zonder_ai_toets(
            administratie_id=administratie_id,
            soort=pl.SOORT_BANK_HISTORIE,
            referentie_id=rid,
            uitkomst=pl.PlausibiliteitUitkomst("overgeslagen", "kostengrens — € 100 bereikt", oorzaak="kostengrens"),
            bron="bank_autoboeken",
        )
        # Geen rij voor plausibel/twijfel/uit — alleen een échte 'zonder toets'-boeking.
        pl.registreer_geboekt_zonder_ai_toets(
            administratie_id=administratie_id,
            soort=pl.SOORT_BANK_HISTORIE,
            referentie_id=uuid.uuid4(),
            uitkomst=pl.PlausibiliteitUitkomst("plausibel", "ok"),
        )
        feiten = auto.verzamel_feiten(nu=datetime.now(UTC), administratie_ids=[administratie_id])
        rijen = [f for f in feiten.audit if f.actie == "automatisch_geboekt_zonder_ai_toets"]
        assert len(rijen) == 1 and rijen[0].nieuwe_waarde["oorzaak"] == "kostengrens"
        t = _teller(auto.bereken(feiten, nu=datetime.now(UTC)), auto.AI_TOETS_OVERGESLAGEN)
        assert t.dag.gedaan == 1 and t.harde_voorwaarden[0].doel_pad == f"/bank/{administratie_id}"
