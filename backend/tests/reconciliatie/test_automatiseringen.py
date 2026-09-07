# ruff: noqa: F811 — pytest-fixtures als parameters
"""Tellers per automatisering in de reconciliatie (herstelrun 07-09 blok C, "geen stille no-op"): per
automatisering per etmaal verwacht / gedaan / overgeslagen mét reden (deterministisch uit audit-/run-sporen),
LET-OP bij een ontbrekende harde voorwaarde (mét deeplink) en bij zeven dagen stil, één regel "uit" voor een
uitgeschakelde automatisering, het compacte blok in de mail, en de opslag in `samenvatting` (geen migratie)."""

from __future__ import annotations

import argparse
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.berichten import mail
from app.crediteuren import afhandeling as crediteuren_afhandeling
from app.db.audit import record_audit_event
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import kantoorbreed, teksten
from app.reconciliatie import run as run_service
from app.reconciliatie.models import ReconciliatieRun
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

NU = datetime(2026, 9, 7, 4, 30, tzinfo=UTC)
ARGS = argparse.Namespace()
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _uur(n: float) -> datetime:
    return NU - timedelta(hours=n)


def _feiten(aid: uuid.UUID, **kw) -> auto.Feiten:
    f = auto.Feiten(administraties={aid: "Kempen Facilities B.V."})
    for k, v in kw.items():
        setattr(f, k, v)
    return f


def _teller(tellers: list[auto.Teller], sleutel: str) -> auto.Teller:
    return next(t for t in tellers if t.sleutel == sleutel)


class TestBereken:
    def test_autoboeken_inkoop_verwacht_gedaan_overgeslagen_per_dag_en_week(self) -> None:
        aid = uuid.uuid4()
        f = _feiten(
            aid,
            leverancier_optins={aid: 2},
            audit=[
                auto.AuditFeit("automatisch_geboekt", _uur(2), aid, {"bron": "leverancier_opt_in"}),
                auto.AuditFeit("automatisch_geboekt", _uur(72), aid, {"bron": "veldwerker_opt_in"}),
                auto.AuditFeit(
                    "autoboeken_geweigerd", _uur(3), aid, {"reden": "harde checks blokkeren — Vervaldatum; Btw"}
                ),
                auto.AuditFeit(
                    "autoboeken_geweigerd", _uur(5), aid, {"reden": "urenmatch niet groen (uitkomst: rood) — mens"}
                ),
                auto.AuditFeit("automatisch_geboekt", _uur(24 * 8), aid, {"bron": "leverancier_opt_in"}),  # buiten week
            ],
        )
        t = _teller(auto.bereken(f, nu=NU), auto.AUTOBOEK_INKOOP)
        assert t.stand == "aan" and "2 leverancier(s)" in (t.stand_detail or "")
        assert (t.dag.verwacht, t.dag.gedaan, t.dag.overgeslagen_totaal) == (3, 1, 2)
        assert t.dag.overgeslagen == {auto.GEEN_EIGENAAR: 0, auto.HARDE_CHECKS: 1, auto.URENMATCH: 1}
        assert (t.week.verwacht, t.week.gedaan) == (4, 2)
        assert t.harde_voorwaarden == [] and not t.stil
        # De categorie "geen eigenaar" blijft zichtbaar als 0 (kernprincipe 7-cross-check ná blok B).
        assert auto.GEEN_EIGENAAR in t.dag.overgeslagen and t.dag.overgeslagen[auto.GEEN_EIGENAAR] == 0

    def test_uitgeschakelde_automatisering_is_een_regel_uit_zonder_bevinding(self) -> None:
        aid = uuid.uuid4()
        tellers = auto.bereken(_feiten(aid), nu=NU)
        omzet = _teller(tellers, auto.AUTOBOEK_OMZET)
        assert omzet.stand == "uit" and omzet.stand_detail == "0 van 1 administraties"
        regels = auto.regels(tellers)
        assert any(r.startswith("  Autoboeken omzet") and " uit (0 van 1 administraties)" in r for r in regels)
        assert auto.bevindingen(tellers) == []

    def test_geldpoort_kill_switch_is_harde_voorwaarde_met_deeplink(self) -> None:
        aid = uuid.uuid4()
        f = _feiten(
            aid,
            omzet_aan={aid},
            audit=[
                auto.AuditFeit(
                    "autoboeken_geweigerd",
                    _uur(1),
                    aid,
                    {
                        "reden": "Boeken staat uit voor deze administratie of via de globale kill switch",
                        "bron": "omzet_opt_in",
                    },
                ),
                auto.AuditFeit(
                    "autoboeken_geweigerd",
                    _uur(30),  # gisteren: telt in de week, niet als LET-OP van vandaag
                    aid,
                    {
                        "reden": "Boeken staat uit voor deze administratie of via de globale kill switch",
                        "bron": "omzet_opt_in",
                    },
                ),
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        omzet = _teller(tellers, auto.AUTOBOEK_OMZET)
        assert (
            omzet.stand == "aan"
            and omzet.dag.overgeslagen[auto.GELDPOORT] == 1
            and omzet.week.overgeslagen[auto.GELDPOORT] == 2
        )
        assert [(h.categorie, h.aantal, h.administratie_id) for h in omzet.harde_voorwaarden] == [
            (auto.GELDPOORT, 1, aid)
        ]
        bev = auto.bevindingen(tellers, namen={aid: "Kempen Facilities B.V."})
        assert len(bev) == 1
        b = bev[0]
        assert b["soort"] == "let_op" and b["blok"] == "automatisering" and b["administratie_id"] == aid
        assert b["detail"]["reden"] == auto.GELDPOORT and b["detail"]["doel_pad"] == "/instellingen/boeken"
        assert b["detail"]["administratie_naam"] == "Kempen Facilities B.V."
        # stabiele vingerafdruk zolang de situatie gelijk is → de delta-motor mailt 'm één keer
        assert b["vingerafdruk"] == auto.vingerafdruk_automatisering(
            sleutel=auto.AUTOBOEK_OMZET, categorie=auto.GELDPOORT, administratie_id=aid
        )
        assert auto.bevindingen(auto.bereken(f, nu=NU))[0]["vingerafdruk"] == b["vingerafdruk"]

    def test_credential_deeplink_naar_de_administratie(self) -> None:
        aid = uuid.uuid4()
        f = _feiten(
            aid,
            bank_aan={aid},
            bank_runs=[
                auto.BankRunFeit(
                    aid,
                    _uur(1),
                    {"automatisch_afgeletterd": 2, "automatisch_geboekt": 1, "fouten": ["credential ongeldig (401)"]},
                )
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        bank = _teller(tellers, auto.BANK)
        assert (bank.dag.verwacht, bank.dag.gedaan, bank.dag.overgeslagen[auto.CREDENTIAL]) == (4, 3, 1)
        assert bank.dag.overgeslagen[auto.VOLUMEREM] == 0  # vaste categorie zichtbaar
        b = auto.bevindingen(tellers)[0]
        assert b["detail"]["doel_pad"] == f"/instellingen/administraties/{aid}"

    def test_volumerem_bank_is_harde_voorwaarde(self) -> None:
        aid = uuid.uuid4()
        f = _feiten(
            aid,
            bank_aan={aid},
            bank_runs=[
                auto.BankRunFeit(
                    aid,
                    _uur(2),
                    {
                        "automatisch_afgeletterd": 25,
                        "fouten": ["volumerem: dagelijkse limiet van 25 automatische afletteringen bereikt"],
                    },
                )
            ],
        )
        bank = _teller(auto.bereken(f, nu=NU), auto.BANK)
        assert bank.harde_voorwaarden[0].categorie == auto.VOLUMEREM and bank.dag.gedaan == 25

    def test_duplicaat_noodrem_uit_met_signalen_is_let_op_zonder_signalen_alleen_uit(self) -> None:
        aid = uuid.uuid4()
        signaal = auto.AuditFeit("duplicaat_module_gesignaleerd", _uur(1), aid, {"categorie": "zelfde_referentie"})
        # noodrem AAN: het signaal is een zacht signaal (mens beoordeelt), geen bevinding
        aan = _teller(auto.bereken(_feiten(aid, audit=[signaal]), nu=NU), auto.DUPLICAAT_AFVOER)
        assert aan.stand == "aan" and aan.dag.overgeslagen[auto.ZACHT_SIGNAAL] == 1 and aan.harde_voorwaarden == []
        # noodrem UIT + kandidaten: de automatisering wacht op een menselijke instelling → LET-OP mét handeling
        tellers = auto.bereken(_feiten(aid, audit=[signaal], duplicaat_noodrem_aan=False), nu=NU)
        uit = _teller(tellers, auto.DUPLICAAT_AFVOER)
        assert uit.stand == "uit" and uit.dag.overgeslagen[auto.NOODREM] == 1
        bev = auto.bevindingen(tellers)
        assert len(bev) == 1 and bev[0]["detail"]["reden"] == auto.NOODREM
        assert bev[0]["detail"]["doel_pad"] == "/instellingen/boeken"
        # noodrem UIT zonder kandidaten: één regel "uit", geen bevinding
        stil_uit = auto.bereken(_feiten(aid, duplicaat_noodrem_aan=False), nu=NU)
        assert auto.bevindingen(stil_uit) == []
        assert any(
            r.startswith("  Duplicaat-afvoer") and " uit (platformbrede noodrem UIT)" in r
            for r in auto.regels(stil_uit)
        )

    def test_geen_eigenaar_is_regressie_en_dus_let_op_met_deeplink(self) -> None:
        """Kernprincipe 7 / blok B (07-09): een ontbrekende eigenaar is geen poort meer. Komt de reden tóch
        voor (dev-DB 07-09: 6× op duplicaat_afvoer), dan is dat zichtbaar mét handeling, niet alleen een teller."""
        aid = uuid.uuid4()
        f = _feiten(
            aid,
            audit=[
                auto.AuditFeit(
                    "duplicaat_afvoer_geweigerd",
                    _uur(2),
                    aid,
                    {
                        "reden": "Deze administratie heeft geen eigenaar — wijs de controle expliciet toe of stel een "
                        "eigenaar in"
                    },
                )
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        dup = _teller(tellers, auto.DUPLICAAT_AFVOER)
        assert dup.dag.overgeslagen[auto.GEEN_EIGENAAR] == 1
        bev = auto.bevindingen(tellers)
        assert len(bev) == 1 and bev[0]["detail"]["reden"] == auto.GEEN_EIGENAAR
        assert bev[0]["detail"]["doel_pad"] == f"/instellingen/administraties/{aid}"
        lees = teksten.leesbaar(
            run_service.Bevinding(
                blok="automatisering",
                soort="let_op",
                administratie_id=aid,
                vingerafdruk="v",
                tekst="t",
                detail=bev[0]["detail"],
            )
        )
        assert "geen poort" in lees.doe and "regressie" in lees.doe

    def test_duplicaat_afvoer_telt_alleen_automatische_afvoer_als_gedaan(self) -> None:
        aid = uuid.uuid4()
        f = _feiten(
            aid,
            audit=[
                auto.AuditFeit("duplicaat_afgevoerd", _uur(1), aid, {"reden": "Duplicaat van F1", "automatisch": True}),
                auto.AuditFeit("duplicaat_afgevoerd", _uur(1), aid, {"reden": "x", "bulk": True, "automatisch": False}),
                auto.AuditFeit(
                    "duplicaat_afvoer_geweigerd",
                    _uur(1),
                    aid,
                    {
                        "reden": "Volumerem: dagelijkse limiet van 20 automatische duplicaat-afvoeren bereikt — "
                        "document blijft"
                    },
                ),
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        dup = _teller(tellers, auto.DUPLICAAT_AFVOER)
        assert (dup.dag.gedaan, dup.dag.overgeslagen[auto.VOLUMEREM]) == (1, 1)
        assert auto.bevindingen(tellers)[0]["detail"]["reden"] == auto.VOLUMEREM

    def test_crediteuren_run_event_draagt_gedaan_en_twijfel(self) -> None:
        aid = uuid.uuid4()
        f = _feiten(
            aid,
            audit=[
                auto.AuditFeit(
                    "crediteur_dubbel_auto_run",
                    _uur(1),
                    None,
                    {"afgehandeld": 2, "twijfel": 3, "fouten": 1, "administraties": 4},
                )
            ],
        )
        cred = _teller(auto.bereken(f, nu=NU), auto.CREDITEUREN)
        assert cred.stand == "altijd"
        assert (cred.dag.verwacht, cred.dag.gedaan, cred.dag.overgeslagen) == (6, 2, {auto.TWIJFEL: 3, auto.FOUT: 1})

    def test_zeven_dagen_stil_bij_kandidaten_is_let_op(self) -> None:
        aid = uuid.uuid4()
        runs = [
            auto.TerugkerendRunFeit(_uur(24 * d + 1), aantal_administraties=5, aantal_verwerkt=0, aantal_fouten=0)
            for d in range(6)
        ]
        tellers = auto.bereken(_feiten(aid, terugkerend_runs=runs), nu=NU)
        terug = _teller(tellers, auto.TERUGKEREND)
        assert terug.stil and terug.week.verwacht == 30 and terug.week.gedaan == 0
        bev = auto.bevindingen(tellers)
        assert [b["detail"]["reden"] for b in bev] == [auto.STIL_7_DAGEN]
        assert bev[0]["administratie_id"] is None and bev[0]["blok"] == "automatisering"
        # wél verwerkt → niet stil
        ok = [auto.TerugkerendRunFeit(_uur(1), aantal_administraties=5, aantal_verwerkt=5, aantal_fouten=0)]
        assert not _teller(auto.bereken(_feiten(aid, terugkerend_runs=ok), nu=NU), auto.TERUGKEREND).stil
        # fouten geregistreerd = niet stil (er is een reden), wél zichtbaar
        met_fout = [auto.TerugkerendRunFeit(_uur(1), aantal_administraties=5, aantal_verwerkt=0, aantal_fouten=5)]
        t = _teller(auto.bereken(_feiten(aid, terugkerend_runs=met_fout), nu=NU), auto.TERUGKEREND)
        assert not t.stil and t.dag.overgeslagen[auto.FOUT] == 5

    def test_uit_staande_automatisering_is_nooit_stil(self) -> None:
        aid = uuid.uuid4()
        # omzet-opt-in uit maar wél (oude) geweigerd-events zonder gedaan: geen stil-vlag
        f = _feiten(
            aid, audit=[auto.AuditFeit("autoboeken_geweigerd", _uur(50), aid, {"reden": "x", "bron": "omzet_opt_in"})]
        )
        assert not _teller(auto.bereken(f, nu=NU), auto.AUTOBOEK_OMZET).stil

    def test_autoboek_kandidaten_een_run_per_etmaal(self) -> None:
        aid = uuid.uuid4()
        vers = _teller(
            auto.bereken(_feiten(aid, autoboek_kandidaten_laatste_run=_uur(3)), nu=NU), auto.AUTOBOEK_KANDIDATEN
        )
        assert (vers.dag.verwacht, vers.dag.gedaan) == (1, 1) and not vers.stil
        oud = _teller(
            auto.bereken(_feiten(aid, autoboek_kandidaten_laatste_run=_uur(24 * 9)), nu=NU), auto.AUTOBOEK_KANDIDATEN
        )
        assert (oud.dag.gedaan, oud.week.gedaan) == (0, 0) and oud.stil

    def test_mini_voorraad_en_nabundel(self) -> None:
        aid = uuid.uuid4()
        f = _feiten(
            aid,
            mini_voorraad_aan={aid},
            audit=[
                auto.AuditFeit(
                    "mini_voorraad_instroom",
                    _uur(1),
                    aid,
                    {"regels": 3, "overgeslagen": ["regel 2 'Transport' — transportregel"]},
                ),
                auto.AuditFeit("document_nagebundeld", _uur(1), aid, {}),
                auto.AuditFeit("document_dubbel_samengevouwen", _uur(2), aid, {}),
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        mini = _teller(tellers, auto.MINI_VOORRAAD)
        assert (mini.dag.gedaan, mini.dag.overgeslagen[auto.REGEL_OVERGESLAGEN]) == (1, 1)
        nab = _teller(tellers, auto.NABUNDEL)
        assert nab.stand == "op_aanvraag" and nab.dag.gedaan == 2

    @pytest.mark.parametrize(
        ("reden", "categorie"),
        [
            ("Volumerem: dagelijkse limiet van 20 …", auto.VOLUMEREM),
            ("volumerem: dagelijkse limiet van 25 automatische afletteringen bereikt", auto.VOLUMEREM),
            ("Boeken staat uit voor deze administratie of via de globale kill switch", auto.GELDPOORT),
            ("geen bewaarde RLZ-credential", auto.CREDENTIAL),
            ("Anthropic API-key ontbreekt", auto.API_KEY),
            ("harde checks blokkeren — Vervaldatum", auto.HARDE_CHECKS),
            (
                "mogelijk-duplicaat-signaal op het document (zelfde bestandsinhoud) — mens beoordeelt",
                auto.DUPLICAATSIGNAAL,
            ),
            ("urenmatch zonder getekende weekstaten — niets te verrekenen, mens beoordeelt", auto.URENMATCH),
            ("geheugen-voorstel voor grootboek is niet app-bevestigd/groen (oranje)", auto.GEHEUGEN_ORANJE),
            ("extractie leverde geen volledige kopgegevens (referentie/datum/totaal)", auto.EXTRACTIE_ONVOLLEDIG),
            ("de UBL leverde geen volledige kopgegevens", auto.EXTRACTIE_ONVOLLEDIG),
            ("RLZ-boekfout tijdens autoboeken (document staat op boeken_mislukt): 500", auto.BOEKFOUT),
            ("HALF GEBOEKT tijdens autoboeken", auto.HALF_GEBOEKT),
            ("geen eigenaar voor deze administratie", auto.GEEN_EIGENAAR),
            ("Deze administratie heeft geen eigenaar — wijs de controle expliciet toe", auto.GEEN_EIGENAAR),
            ("Geen harde duplicaat-match (meer): crediteur, referentie en totaalbedrag …", auto.MENS_BEOORDEELT),
            ("er is al een door een mens opgeslagen voorstel", auto.MENS_BEOORDEELT),
            ("", auto.MENS_BEOORDEELT),
            (None, auto.MENS_BEOORDEELT),
        ],
    )
    def test_categoriseer_reden(self, reden: str | None, categorie: str) -> None:
        assert auto.categoriseer_reden(reden) == categorie

    def test_regels_en_json_roundtrip(self) -> None:
        aid = uuid.uuid4()
        f = _feiten(
            aid,
            leverancier_optins={aid: 1},
            audit=[
                auto.AuditFeit("automatisch_geboekt", _uur(1), aid, {"bron": "leverancier_opt_in"}),
                auto.AuditFeit("autoboeken_geweigerd", _uur(1), aid, {"reden": "harde checks blokkeren — Btw"}),
            ],
        )
        tellers = auto.bereken(f, nu=NU)
        regels = auto.regels(tellers)
        assert regels[0] == "Automatiseringen (laatste 24 u):"
        inkoop = next(r for r in regels if r.startswith("  Autoboeken inkoop"))
        assert "verwacht 2, gedaan 1, overgeslagen 1" in inkoop
        assert "geen eigenaar/toewijzing: 0" in inkoop and "harde checks blokkeren: 1" in inkoop
        assert len(regels) == 1 + len(auto.VOLGORDE)
        # JSON-vorm voor samenvatting → terug → identieke regels (de mail wordt ná opslag opgebouwd)
        json_ = auto.als_samenvatting(tellers, nu=NU)
        assert json_["venster_uren"] == 24 and json_["stil_dagen"] == 7 and len(json_["tellers"]) == len(auto.VOLGORDE)
        assert auto.regels_uit_samenvatting(json_) == regels
        import json

        json.dumps(json_)  # JSONB-veilig (UUID's als str)


class TestTeksten:
    def test_harde_voorwaarde_leesbaar_met_deeplink_handeling(self) -> None:
        aid = uuid.uuid4()
        f = _feiten(
            aid,
            omzet_aan={aid},
            audit=[
                auto.AuditFeit(
                    "autoboeken_geweigerd",
                    _uur(1),
                    aid,
                    {
                        "reden": "Boeken staat uit voor deze administratie of via de globale kill switch",
                        "bron": "omzet_opt_in",
                    },
                )
            ],
        )
        kw = auto.bevindingen(auto.bereken(f, nu=NU), namen={aid: "Kempen Facilities B.V."})[0]
        b = run_service.Bevinding(
            blok=kw["blok"],
            soort=kw["soort"],
            administratie_id=kw["administratie_id"],
            vingerafdruk=kw["vingerafdruk"],
            tekst=kw["tekst"],
            detail=kw["detail"],
        )
        lees = teksten.leesbaar(b, administratie_naam="Kempen Facilities B.V.")
        assert lees.titel == "Automatisering wacht op voorwaarde — Autoboeken omzet"
        assert lees.wat.startswith("Autoboeken omzet sloeg 1 stuk(s) over in Kempen Facilities B.V.: boeken staat uit")
        assert "Instellingen › Boeken" in lees.doe
        for zin in (lees.titel, lees.wat, lees.doe):
            assert not GUID.search(zin) and len(lees.titel) <= 60

    def test_stil_leesbaar(self) -> None:
        aid = uuid.uuid4()
        runs = [auto.TerugkerendRunFeit(_uur(1), aantal_administraties=5, aantal_verwerkt=0, aantal_fouten=0)]
        kw = auto.bevindingen(auto.bereken(_feiten(aid, terugkerend_runs=runs), nu=NU))[0]
        b = run_service.Bevinding(
            blok="automatisering",
            soort="let_op",
            administratie_id=None,
            vingerafdruk="x",
            tekst=kw["tekst"],
            detail=kw["detail"],
        )
        lees = teksten.leesbaar(b)
        assert lees.titel.startswith("Automatisering stil — Terugkerende facturen")
        assert "7 dagen niets bij 5 kandidaat" in lees.wat and "storing" in lees.doe


# ---- DB-integratie --------------------------------------------------------------------------------


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []
    monkeypatch.setattr(
        mail,
        "verzend_mail",
        lambda *, naar, onderwerp, tekst, bijlagen=None: verzonden.append({"onderwerp": onderwerp, "tekst": tekst}),
    )
    return verzonden


def _leeg_blok(args, verzamelaar=None) -> int:  # noqa: ANN001
    return 0


def _audit(aid: uuid.UUID | None, actie: str, nieuwe_waarde: dict) -> None:
    with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=uuid.uuid4(),
            actie=actie,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=nieuwe_waarde,
            administratie_id=aid,
        )


class TestVerzamelEnRun:
    def test_verzamel_feiten_leest_per_administratie_onder_rls(self, administratie_id, admin_engine) -> None:
        _audit(administratie_id, "automatisch_geboekt", {"bron": "leverancier_opt_in"})
        _audit(administratie_id, "autoboeken_geweigerd", {"reden": "harde checks blokkeren — Btw"})
        _audit(None, "crediteur_dubbel_auto_run", {"afgehandeld": 1, "twijfel": 2, "fouten": 0})
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.leverancier_voorkeur (administratie_id, vendor_id, regels_samenvoegen, "
                    "autoboeken_ingeschakeld) VALUES (:a, :v, false, true)"
                ),
                {"a": administratie_id, "v": uuid.uuid4()},
            )
        feiten = auto.verzamel_feiten(nu=datetime.now(UTC))
        assert administratie_id in feiten.administraties
        acties = sorted(f.actie for f in feiten.audit)
        assert acties == ["autoboeken_geweigerd", "automatisch_geboekt", "crediteur_dubbel_auto_run"]
        assert feiten.leverancier_optins[administratie_id] == 1 and feiten.duplicaat_noodrem_aan is True
        tellers = auto.bereken(feiten, nu=datetime.now(UTC))
        inkoop = _teller(tellers, auto.AUTOBOEK_INKOOP)
        assert (inkoop.dag.verwacht, inkoop.dag.gedaan, inkoop.dag.overgeslagen[auto.HARDE_CHECKS]) == (2, 1, 1)
        assert _teller(tellers, auto.CREDITEUREN).dag.overgeslagen[auto.TWIJFEL] == 2

    def test_run_slaat_tellers_op_in_samenvatting_mailt_het_blok_en_maakt_let_op_bevinding(
        self, administratie_id, beheerder_id, mails, admin_engine
    ) -> None:
        # noodrem UIT + een gesignaleerd duplicaat = kandidaat die wacht op een menselijke instelling
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.duplicaat_afvoer_instelling SET platformbreed_ingeschakeld = false"))
        _audit(administratie_id, "duplicaat_module_gesignaleerd", {"categorie": "zelfde_referentie"})
        uit: list[str] = []
        code = run_service.voer_uit(blokken=[("documenten", _leeg_blok)], args=ARGS, bron="cli", stdout=uit.append)
        assert code == 0  # het vangnet raakt de exit-code nooit
        with scoped_session(None) as session:
            rij = session.scalars(
                select(ReconciliatieRun).order_by(ReconciliatieRun.aangevraagd_op.desc()).limit(1)
            ).one()
            samenvatting = rij.samenvatting
        tellers = samenvatting["automatiseringen"]["tellers"]
        dup = next(t for t in tellers if t["sleutel"] == "duplicaat_afvoer")
        assert dup["stand"] == "uit" and dup["dag"]["overgeslagen"]["noodrem"] == 1
        assert dup["harde_voorwaarden"][0]["administratie_id"] == str(administratie_id)
        assert samenvatting["documenten"]["status"] == "ok"  # blokstanden onaangeroerd
        # bevinding op blok `automatisering`, RLS-gescoopt op de administratie
        bev = run_service.lees_bevindingen(rij.id, administratie_ids=[administratie_id])
        assert [(b.blok, b.soort) for b in bev] == [("automatisering", "let_op")]
        assert bev[0].detail["reden"] == "noodrem" and bev[0].detail["doel_pad"] == "/instellingen/boeken"
        # CLI-uitvoer én mail dragen het compacte blok
        assert "Automatiseringen (laatste 24 u):" in uit
        assert len(mails) == 1
        tekst = mails[0]["tekst"]
        assert "Automatiseringen (laatste 24 u):" in tekst
        assert re.search(r"Duplicaat-afvoer\s+uit \(platformbrede noodrem UIT\)", tekst)
        assert re.search(r"Autoboeken inkoop\s+uit", tekst)
        assert "Automatisering wacht op voorwaarde — Duplicaat-afvoer" in tekst and "Instellingen › Boeken" in tekst
        # Inzicht › Reconciliatie: rij mét deeplink-handeling (kantoorbreed, Beheerder)
        from app.db.models import GebruikerRol

        lijst = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER)
        rijen = [r for r in lijst.rijen if r.blok == "automatisering"]
        assert len(rijen) == 1 and rijen[0].doel_pad == "/instellingen/boeken" and rijen[0].soort == "let_op"
        assert rijen[0].titel.startswith("Automatisering wacht op voorwaarde")
        # tweede run met ongewijzigde situatie: zelfde vingerafdruk → geen tweede mail (delta leeg)
        run_service.voer_uit(blokken=[("documenten", _leeg_blok)], args=ARGS, bron="cli", stdout=lambda t: None)
        assert len(mails) == 1

    def test_zonder_activiteit_geen_bevinding_maar_wel_het_blok(self, administratie_id, mails) -> None:
        uit: list[str] = []
        run_service.voer_uit(blokken=[("documenten", _leeg_blok)], args=ARGS, bron="cli", stdout=uit.append)
        with scoped_session(None) as session:
            rij = session.scalars(
                select(ReconciliatieRun).order_by(ReconciliatieRun.aangevraagd_op.desc()).limit(1)
            ).one()
        assert "automatiseringen" in rij.samenvatting and "automatisering" not in rij.samenvatting
        assert run_service.lees_bevindingen(rij.id, administratie_ids=[administratie_id]) == []
        assert mails == []  # niets te melden = géén mail (ongewijzigd gedrag)

    def test_crediteuren_auto_run_schrijft_run_event(self, administratie_id) -> None:
        uitkomst = crediteuren_afhandeling.auto_afhandelen(None, dry_run=False)
        with scoped_session(None) as session:
            events = session.scalars(select(AuditEvent).where(AuditEvent.actie == "crediteur_dubbel_auto_run")).all()
        assert len(events) == 1 and events[0].record_id == uitkomst.run_id and events[0].administratie_id is None
        assert events[0].nieuwe_waarde["afgehandeld"] == 0 and "reden" in events[0].nieuwe_waarde
        # dry-run schrijft niets
        crediteuren_afhandeling.auto_afhandelen(None, dry_run=True)
        with scoped_session(None) as session:
            assert (
                len(session.scalars(select(AuditEvent).where(AuditEvent.actie == "crediteur_dubbel_auto_run")).all())
                == 1
            )
