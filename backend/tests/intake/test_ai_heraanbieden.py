# ruff: noqa: E501 — lange assert-/stub-regels bewust (patroon tests/keten)
"""AI-heraanbieding ná een limietverhoging (BUG Peter 24-09; `app/aikosten/heraanbieden.py`) — de guard-tests uit de
opdracht: (D5) poort dicht = overgeslagen mét teller, geen exception; (D2) de run stopt zichtbaar zodra de poort tijdens
de run dichtgaat en laat de rest staan; (D3) een verzamelbak-rij `ai_limiet_bereikt` wordt ná heraanbieding toegewezen
mét hetzelfde intake-bericht; plus: documenten mét overgeslagen extractie (limiet) lopen door de opnieuw-route, de
dubbelencheck vóór de AI-stap geldt óók hier, dry-run schrijft niets, de dagteller in de reconciliatiemail leest de
run-audit, en de CLI-vorm uit het meetrecept (`ai-heraanbieden --dry-run`) draait letterlijk."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import cli as app_cli
from app.aikosten import heraanbieden
from app.aikosten.service import AiKostenLimietBereikt
from app.config import settings
from app.extractie import splitsing as splitsing_extractie
from app.extractie.splitsing import FactuurSegment
from app.intake import verwerking
from app.main import app
from app.reconciliatie import automatiseringen
from app.security.tokens import create_access_token
from tests.aikosten.test_geldlogica import _zet_limiet
from tests.documenten.test_ai_extractie import _fake_extractie
from tests.intake.conftest import bouw_eml, bouw_pdf

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, rol: str = "boekhouding") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _limiet(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
    raise AiKostenLimietBereikt("AI-maandlimiet bereikt (test)")


def _segment_blow(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
    return [FactuurSegment(1, paginas, "BLOW B.V.", "Bouwmaat", "F-1", 0.95, documentsoort="factuur")]


def _rij(admin_engine: Engine, document_id: uuid.UUID):
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT administratie_id, status, intake_bericht_id, samengevoegd_in_id FROM boekhouding.document "
                "WHERE id = :id"
            ),
            {"id": document_id},
        ).one()


def _redenen(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r[0] or ""
            for r in conn.execute(
                text(
                    "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis WHERE document_id = :d "
                    "ORDER BY tijdstip, id"
                ),
                {"d": document_id},
            )
        ]


def _audits(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT nieuwe_waarde, administratie_id FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"
                ),
                {"a": actie},
            )
        ]


@pytest.fixture
def ai_aan(intake_ai_aan: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


@pytest.fixture
def limiet_rij(ai_aan: None, gescoopte_gebruiker: uuid.UUID, monkeypatch: pytest.MonkeyPatch):
    """Maakt een verzamelbak-rij mét reden `ai_limiet_bereikt` (zoals de herstelrun van 23-09 er 202 maakte)."""

    def maak(pdf: bytes, *, naam: str = "factuur.pdf", message_id: str | None = None):
        monkeypatch.setattr(splitsing_extractie, "detecteer_facturen", _limiet)
        eml = bouw_eml(bijlagen=[(naam, pdf, "application", "pdf")], message_id=message_id)
        r = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        assert r.bijlagen[0].uitkomst == "verzamelbak" and r.bijlagen[0].detail == "ai_limiet_bereikt", r.bijlagen
        return r.bijlagen[0].document_id, r.bericht_id

    return maak


@pytest.fixture
def veldextractie_blow(administratie_heet_blow: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    from app.beheer import service as beheer_service

    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_heet_blow, ingeschakeld=True
    )
    return administratie_heet_blow


class TestSelectie:
    def test_alleen_rijen_met_reden_ai_limiet_zijn_kandidaat(
        self, limiet_rij, gescoopte_gebruiker: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doc_limiet, _ = limiet_rij(bouw_pdf(1))
        # Een gewone verzamelbak-rij (tenaamstelling niet eenduidig) is géén kandidaat.
        monkeypatch.setattr(
            splitsing_extractie,
            "detecteer_facturen",
            lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
                FactuurSegment(1, paginas, "Onbekende Partij", None, None, 0.9, documentsoort="factuur")
            ],
        )
        r = verwerking.verwerk_eml(
            bouw_eml(bijlagen=[("ander.pdf", bouw_pdf(2), "application", "pdf")]), actor_id=gescoopte_gebruiker
        )
        assert r.bijlagen[0].uitkomst == "verzamelbak" and r.bijlagen[0].detail != "ai_limiet_bereikt"
        kandidaten = heraanbieden.vind_kandidaten_verzamelbak()
        assert [k.document_id for k in kandidaten] == [doc_limiet]
        assert heraanbieden.tel_kandidaten() == (1, 0)

    def test_dry_run_telt_en_schrijft_niets(
        self, limiet_rij, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        limiet_rij(bouw_pdf(1))
        monkeypatch.setattr(splitsing_extractie, "detecteer_facturen", _segment_blow)
        r = heraanbieden.draai(bron=heraanbieden.BRON_CLI, dry_run=True)
        assert r.kandidaten == 1 and r.dry_run and [u.uitkomst for u in r.uitkomsten] == ["kandidaat"]
        assert _audits(admin_engine, heraanbieden.AUDIT_RUN) == []
        assert heraanbieden.tel_kandidaten() == (1, 0)


class TestPoort:
    def test_geblokkeerd_is_overgeslagen_met_teller_geen_exception(
        self, limiet_rij, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(D5) poort dicht bij de start: niets aangeboden, alles overgeslagen `kostengrens`, run-audit + gestopt-reden —
        nooit een exception, nooit stil."""
        doc, _ = limiet_rij(bouw_pdf(1))
        _zet_limiet(admin_engine, Decimal("0"))
        aanroepen: list[bytes] = []
        monkeypatch.setattr(
            splitsing_extractie,
            "detecteer_facturen",
            lambda inhoud, paginas, **kw: aanroepen.append(inhoud) or _segment_blow(inhoud, paginas),
        )
        r = heraanbieden.draai(bron=heraanbieden.BRON_INTAKE_JOB)
        assert r.geblokkeerd and r.gedaan == 0 and r.overgeslagen == {"kostengrens": 1}
        assert "AI-maandlimiet bereikt" in (r.gestopt_reden or "")
        assert aanroepen == []
        assert _rij(admin_engine, doc).status == "niet_toegewezen"
        runs = _audits(admin_engine, heraanbieden.AUDIT_RUN)
        assert [a["nieuwe_waarde"]["status"] for a in runs] == ["bezig", "klaar"]
        assert (
            runs[-1]["nieuwe_waarde"]["overgeslagen"] == {"kostengrens": 1} and runs[-1]["nieuwe_waarde"]["rest"] == 1
        )

    def test_stopt_zichtbaar_zodra_de_poort_tijdens_de_run_dichtgaat(
        self, limiet_rij, veldextractie_blow: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(D2) oud → nieuw: de eerste rij wordt toegewezen, bij de tweede gaat de poort dicht → die rij 'wacht op
        AI-budget' (tijdlijn) en de derde blijft ongemoeid staan (overgeslagen kostengrens, geen tijdlijnruis)."""
        d1, _ = limiet_rij(bouw_pdf(1), naam="een.pdf")
        d2, _ = limiet_rij(bouw_pdf(2), naam="twee.pdf")
        d3, _ = limiet_rij(bouw_pdf(3), naam="drie.pdf")
        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", lambda pdf, **kw: _fake_extractie())
        teller = {"n": 0}

        def poort_dicht_na_een(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
            teller["n"] += 1
            if teller["n"] >= 2:
                raise AiKostenLimietBereikt("AI-maandlimiet bereikt (tijdens de run)")
            return _segment_blow(inhoud, paginas)

        monkeypatch.setattr(splitsing_extractie, "detecteer_facturen", poort_dicht_na_een)
        r = heraanbieden.draai(bron=heraanbieden.BRON_INTAKE_JOB)
        per_doc = {u.document_id: u.uitkomst for u in r.uitkomsten}
        assert per_doc == {d1: "toegewezen", d2: "wacht_op_budget"}
        assert r.overgeslagen == {"kostengrens": 2} and "wachten op AI-budget" in (r.gestopt_reden or "")
        assert _rij(admin_engine, d1).administratie_id == veldextractie_blow
        assert _rij(admin_engine, d2).status == "niet_toegewezen" and _rij(admin_engine, d3).status == "niet_toegewezen"
        assert any("wacht op AI-budget" in x for x in _redenen(admin_engine, d2))
        assert not any("wacht op AI-budget" in x for x in _redenen(admin_engine, d3))
        # Bij de volgende run (poort open) zijn d2 én d3 gewoon weer kandidaat — niets is verloren.
        assert {k.document_id for k in heraanbieden.vind_kandidaten_verzamelbak()} == {d2, d3}


class TestHeraanbieding:
    def test_verzamelbak_rij_wordt_toegewezen_met_zelfde_intake_bericht(
        self, limiet_rij, veldextractie_blow: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(D3) dezelfde rij (geen tweede document), toegewezen op tenaamstelling, hetzelfde intake-bericht, extractie
        ná toewijzing gestart; tijdlijn + audit `ai_heraanbieding` (oude reden → uitkomst)."""
        doc, bericht_id = limiet_rij(bouw_pdf(1))
        extracties: list[bytes] = []
        monkeypatch.setattr(
            "app.extractie.service.extraheer_inkoopfactuur",
            lambda pdf, **kw: extracties.append(pdf) or _fake_extractie(),
        )
        monkeypatch.setattr(splitsing_extractie, "detecteer_facturen", _segment_blow)
        r = heraanbieden.draai(bron=heraanbieden.BRON_INTAKE_JOB)
        assert [(u.document_id, u.uitkomst) for u in r.uitkomsten] == [(doc, "toegewezen")]
        assert r.gedaan == 1 and r.overgeslagen == {}
        rij = _rij(admin_engine, doc)
        assert rij.administratie_id == veldextractie_blow and rij.intake_bericht_id == bericht_id
        assert rij.status == "te_controleren" and len(extracties) == 1
        with admin_engine.connect() as conn:
            n = conn.execute(text("SELECT count(*) FROM boekhouding.document")).scalar_one()
        assert n == 1, "geen tweede document — de bestaande rij is heraangeboden"
        redenen = _redenen(admin_engine, doc)
        assert any("opnieuw aangeboden ná AI-limiet" in x for x in redenen)
        assert any(x.startswith("ai_heraanbieding: toegewezen") for x in redenen)
        audits = _audits(admin_engine, heraanbieden.AUDIT_DOCUMENT)
        assert len(audits) == 1 and audits[0]["nieuwe_waarde"]["uitkomst"] == "toegewezen"
        assert audits[0]["administratie_id"] == veldextractie_blow
        # En daarna geen kandidaat meer.
        assert heraanbieden.tel_kandidaten() == (0, 0)

    def test_document_met_overgeslagen_extractie_loopt_door_de_opnieuw_route(
        self,
        ai_aan: None,
        veldextractie_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """(b) een document mét administratie waarvan de extractie op de limiet strandde (te_controleren, tijdlijn
        `ai_extractie_overgeslagen: ai_limiet_bereikt`) krijgt bij open poort alsnog zijn voorstel."""

        def limiet(pdf, **kw):
            raise AiKostenLimietBereikt("maandlimiet bereikt")

        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", limiet)
        resp = client.post(
            f"/administraties/{veldextractie_blow}/documenten",
            files={"bestand": ("scan.pdf", bouw_pdf(1), "application/pdf")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201, resp.text
        doc = uuid.UUID(resp.json()["document_id"])
        assert heraanbieden.tel_kandidaten() == (0, 1)

        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", lambda pdf, **kw: _fake_extractie())
        r = heraanbieden.draai(bron=heraanbieden.BRON_DAGELIJKS)
        assert [(u.document_id, u.uitkomst) for u in r.uitkomsten] == [(doc, "geextraheerd")]
        assert _rij(admin_engine, doc).status == "te_controleren"
        assert heraanbieden.tel_kandidaten() == (0, 0)
        with admin_engine.connect() as conn:
            laatste = conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :d AND detail ? 'veldvoorstel' "
                    "ORDER BY tijdstip DESC LIMIT 1"
                ),
                {"d": doc},
            ).scalar_one()
        assert laatste is not None

    def test_document_waar_een_mens_aan_werkt_wordt_overgeslagen_met_reden(
        self,
        ai_aan: None,
        veldextractie_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def limiet(pdf, **kw):
            raise AiKostenLimietBereikt("maandlimiet bereikt")

        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", limiet)
        resp = client.post(
            f"/administraties/{veldextractie_blow}/documenten",
            files={"bestand": ("scan.pdf", bouw_pdf(1), "application/pdf")},
            headers=_bearer(gescoopte_gebruiker),
        )
        doc = uuid.UUID(resp.json()["document_id"])
        # Een mens-gebeurtenis ná de limiet-uitkomst (bv. een opgeslagen boekvoorstel) — nooit overschrijven.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.document_gebeurtenis (id, document_id, van_status, naar_status, actor_id, detail, tijdstip) "
                    "VALUES (:i, :d, 'te_controleren', 'te_controleren', :a, '{\"reden\": \"boekvoorstel opgeslagen\"}'::jsonb, now() + interval '1 second')"
                ),
                {"i": uuid.uuid4(), "d": doc, "a": gescoopte_gebruiker},
            )
        aanroepen: list[bytes] = []
        monkeypatch.setattr(
            "app.extractie.service.extraheer_inkoopfactuur",
            lambda pdf, **kw: aanroepen.append(pdf) or _fake_extractie(),
        )
        r = heraanbieden.draai(bron=heraanbieden.BRON_DAGELIJKS)
        assert r.overgeslagen == {"mens_bezig": 1} and aanroepen == []
        assert r.uitkomsten[0].uitkomst == "overgeslagen" and "mens" in (r.uitkomsten[0].detail or "")

    def test_byte_identiek_exemplaar_in_de_bak_wordt_huls_zonder_ai_call(
        self,
        limiet_rij,
        veldextractie_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dubbelencheck vóór de AI-stap geldt óók in de heraanbieding: dezelfde bytes staan al als document in een
        administratie → de bak-rij wordt daar als duplicaat afgevoerd (kruisverwijzing), 0 AI-calls."""
        pdf = bouw_pdf(1)
        bak, _ = limiet_rij(pdf, message_id="<eerst@x>")
        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", lambda p, **kw: _fake_extractie())
        resp = client.post(
            f"/administraties/{veldextractie_blow}/documenten",
            files={"bestand": ("scan.pdf", pdf, "application/pdf")},
            headers=_bearer(gescoopte_gebruiker),
        )
        origineel = uuid.UUID(resp.json()["document_id"])
        aanroepen: list[bytes] = []
        monkeypatch.setattr(
            splitsing_extractie,
            "detecteer_facturen",
            lambda inhoud, paginas, **kw: aanroepen.append(inhoud) or _segment_blow(inhoud, paginas),
        )
        r = heraanbieden.draai(bron=heraanbieden.BRON_INTAKE_JOB)
        assert [(u.document_id, u.uitkomst) for u in r.uitkomsten] == [(bak, "dubbel")] and aanroepen == []
        rij = _rij(admin_engine, bak)
        assert rij.status == "afgevoerd_duplicaat" and rij.administratie_id == veldextractie_blow
        with admin_engine.connect() as conn:
            dup = conn.execute(
                text("SELECT duplicaat_van_document_id FROM boekhouding.afwijzing WHERE document_id = :d"), {"d": bak}
            ).scalar_one()
        assert dup == origineel
        assert any("dubbel vóór extractie herkend (bespaard)" in x for x in _redenen(admin_engine, origineel))
        assert len(_audits(admin_engine, "ai_dubbel_voor_extractie")) == 1


class TestDagtellerEnCli:
    def test_run_audit_wordt_dagteller_met_let_op_bij_kostengrens(self) -> None:
        nu = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
        feiten = automatiseringen.Feiten(
            administraties={},
            audit=[
                automatiseringen.AuditFeit(
                    actie="ai_heraanbieding_run",
                    tijdstip=nu,
                    administratie_id=None,
                    nieuwe_waarde={
                        "status": "klaar",
                        "dry_run": False,
                        "gedaan": 3,
                        "overgeslagen": {"kostengrens": 202, "tijdbudget": 5},
                        "gestopt_reden": "AI-maandlimiet bereikt (€ 150,00 van € 150,00 in 2026-09)",
                    },
                ),
                automatiseringen.AuditFeit(
                    actie="ai_dubbel_voor_extractie", tijdstip=nu, administratie_id=None, nieuwe_waarde={}
                ),
                automatiseringen.AuditFeit(
                    actie="ai_dubbel_voor_extractie", tijdstip=nu, administratie_id=None, nieuwe_waarde={}
                ),
            ],
        )
        tellers = {t.sleutel: t for t in automatiseringen.bereken(feiten, nu=nu)}
        h = tellers[automatiseringen.AI_HERAANBIEDING]
        assert (h.dag.verwacht, h.dag.gedaan, h.dag.overgeslagen) == (210, 3, {"kostengrens": 202, "tijdbudget": 5})
        assert [(hv.categorie, hv.aantal) for hv in h.harde_voorwaarden] == [("kostengrens", 202)]
        let_ops = [
            b
            for b in automatiseringen.bevindingen(list(tellers.values()))
            if b["detail"].get("automatisering") == automatiseringen.AI_HERAANBIEDING
        ]
        assert len(let_ops) == 1 and let_ops[0]["detail"]["reden"] == "kostengrens"
        b = tellers[automatiseringen.AI_BESPAARD_DUBBEL]
        assert (b.dag.gedaan, b.dag.verwacht) == (2, 2)
        regels = "\n".join(automatiseringen.regels(list(tellers.values())))
        assert "AI-heraanbieding ná limiet" in regels and "AI bespaard" in regels

    def test_cli_dry_run_vorm_uit_het_meetrecept(self, limiet_rij, capsys: pytest.CaptureFixture[str]) -> None:
        doc, _ = limiet_rij(bouw_pdf(1))
        assert app_cli.main(["ai-heraanbieden", "--dry-run"]) == 0
        uit = capsys.readouterr().out
        assert "kandidaten 1 (verzamelbak 1, documenten 0)" in uit and "[dry-run]" in uit and str(doc) in uit
        assert app_cli.main(["ai-heraanbieden", "--dry-run", "--max", "5"]) == 0

    def test_intake_postvak_job_run_draait_de_heraanbieding_ook_zonder_postvak(
        self,
        limiet_rij,
        veldextractie_blow: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """De job-entrypoint (beide postvakken) eindigt met de heraanbieding — ook als het postvak niet geconfigureerd is
        (dev/test): geen stille no-op."""
        doc, _ = limiet_rij(bouw_pdf(1))
        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", lambda p, **kw: _fake_extractie())
        monkeypatch.setattr(splitsing_extractie, "detecteer_facturen", _segment_blow)
        code = app_cli.main(["intake-postvak-verwerken"])
        uit = capsys.readouterr()
        assert code == 1  # postvak niet geconfigureerd in de suite — de exit-code van de postvak-pas blijft
        assert "AI-heraanbieding ná limiet (intake_job:facturen)" in uit.out
        assert _rij(admin_engine, doc).administratie_id == veldextractie_blow


class TestRoutes:
    def test_knop_202_start_via_de_intake_job_en_stand_toont_de_uitkomst(
        self,
        limiet_rij,
        gescoopte_gebruiker: uuid.UUID,
        veldextractie_blow: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.intake import nu_verwerken

        doc, _ = limiet_rij(bouw_pdf(1))
        gestart: list[str] = []
        monkeypatch.setattr(
            nu_verwerken,
            "start",
            lambda *, kanaal, actor_id: (
                gestart.append(kanaal)
                or nu_verwerken.StartResultaat(kanaal=kanaal, voertuig="thread", job_resource=None)
            ),
        )
        resp = client.post("/verzamelbak/ai-heraanbieden", headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 202, resp.text
        assert resp.json() == {"voertuig": "thread", "kandidaten_verzamelbak": 1, "kandidaten_documenten": 0}
        assert gestart == ["facturen"]
        stand = client.get("/verzamelbak/ai-heraanbieden/stand", headers=_bearer(gescoopte_gebruiker)).json()
        assert stand["bezig"] is True, (stand, _audits(admin_engine, heraanbieden.AUDIT_AANGEVRAAGD))
        assert stand["kandidaten_verzamelbak"] == 1 and stand["laatste_run"] is None
        # De job draait (hier direct): daarna toont de stand de uitkomst per rij, bulk-upload-patroon.
        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", lambda p, **kw: _fake_extractie())
        monkeypatch.setattr(splitsing_extractie, "detecteer_facturen", _segment_blow)
        heraanbieden.draai(bron=heraanbieden.BRON_INTAKE_JOB)
        stand = client.get("/verzamelbak/ai-heraanbieden/stand", headers=_bearer(gescoopte_gebruiker)).json()
        assert stand["bezig"] is False and stand["kandidaten_verzamelbak"] == 0 and stand["wachten"] == 0
        run = stand["laatste_run"]
        assert run["status"] == "klaar" and run["tellers"] == {"toegewezen": 1}
        assert [(u["document_id"], u["uitkomst"]) for u in run["uitkomsten"]] == [(str(doc), "toegewezen")]

    def test_knop_409_bij_gesloten_poort(
        self, limiet_rij, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.intake import nu_verwerken

        limiet_rij(bouw_pdf(1))
        monkeypatch.setattr(nu_verwerken, "start", lambda **kw: pytest.fail("poort dicht — nooit starten"))
        _zet_limiet(admin_engine, Decimal("0"))
        resp = client.post("/verzamelbak/ai-heraanbieden", headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 409 and "AI-maandlimiet bereikt" in resp.json()["detail"]
        # De rolpoort (403 voor app-rollen) dekt de fail-closed sweep tests/security/test_rol_endpoint_gates.py.

    def test_ai_kosten_status_banner_feiten(
        self, gescoopte_gebruiker: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, limiet_rij
    ) -> None:
        """(D1, server-kant) `limiet_bereikt` blijft een historisch feit, `geblokkeerd` de live stand; ná een verhoging
        draagt de status `weer_actief_sinds` + de limiet van het bereik-moment + het aantal wachtende documenten."""
        from app.aikosten.service import registreer_verbruik
        from app.beheer import service as beheer_service

        limiet_rij(bouw_pdf(1))
        _zet_limiet(admin_engine, Decimal("0.01"))
        registreer_verbruik(
            model="claude-sonnet-5", input_tokens=20000, output_tokens=0
        )  # € 0,06 ≥ € 0,01 → limiet bereikt
        st = client.get("/instellingen/ai-kosten", headers=_bearer(beheerder_id, rol="beheerder")).json()
        assert st["limiet_bereikt"] is True and st["geblokkeerd"] is True and st["weer_actief_sinds"] is None
        beheer_service.zet_ai_kosten_maandlimiet(actor_id=beheerder_id, maandlimiet_eur=Decimal("150"))
        st = client.get("/instellingen/ai-kosten", headers=_bearer(beheerder_id, rol="beheerder")).json()
        assert st["limiet_bereikt"] is True and st["geblokkeerd"] is False
        assert st["weer_actief_sinds"] is not None and st["limiet_bij_bereiken_eur"] == "0.01"
        assert st["limiet_eur"] == "150.00" and st["wachten_op_heraanbieding"] == 1
