# ruff: noqa: F811 — pytest-fixtures als parameters
"""SPOED 17-09 blok C — bevindingssoorten starten in stand `meten`; explosie-rem; actiemail begrensd per administratie;
blok A — verdwenen dubbele-betaling-bevindingen automatisch gesloten mét audit. Guard: elke afwijkingssoort met een
tekst in teksten.py staat in de registry; een soort van ná 17-09 start op `meten`."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.berichten import mail
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import kantoorbreed, soort_stand
from app.reconciliatie import run as run_service
from app.reconciliatie.models import ReconciliatieBevinding, ReconciliatieInstelling
from app.reconciliatie.run import Bevinding, Delta, actie_bevindingen, bouw_actiemail
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.reconciliatie.test_actiemail_guard import ARGS, DOC, NAMEN, _afwijking_kw, _blok, _laatste_run

TEKSTEN = Path(__file__).resolve().parents[2] / "app" / "reconciliatie" / "teksten.py"


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []

    def nep(*, naar: str, onderwerp: str, tekst: str, bijlagen=None) -> None:  # noqa: ANN001
        verzonden.append({"naar": naar, "onderwerp": onderwerp, "tekst": tekst})

    monkeypatch.setattr(mail, "verzend_mail", nep)
    monkeypatch.setattr(run_service.settings, "reconciliatie_beheer_ontvangers", "beheer@test.local")
    return verzonden


def _dubbel_kw(aid: uuid.UUID, vaf: str, soort: str = "dubbele_betaling_vermoed") -> dict:
    return {
        "soort": "afwijking",
        "administratie_id": aid,
        "vingerafdruk": vaf,
        "tekst": f"AFWIJKING  record={DOC} mutatie={DOC} soort={soort} [vaf:{vaf}]: Aan X is € 1,00 twee keer betaald",
        "detail": {
            "bron": "bank",
            "afwijking_soort": soort,
            "detail": "Aan X is € 1,00 twee keer betaald",
            "tegenpartij_naam": "Google Cloud",
            "dubbele_betaling_datums": ["2026-08-01", "2026-09-01"],
            "dubbele_betaling_aantal": 2,
            "dubbele_betaling_bedrag": "40.59",
        },
    }


class TestRegistry:
    def test_elke_afwijkingssoort_met_een_tekst_staat_in_de_registry(self) -> None:
        tekst = TEKSTEN.read_text(encoding="utf-8")
        gevonden = set(re.findall(r'(?:afwijking_)?soort == "([a-z][a-z0-9_]+)"', tekst))
        gevonden |= {s for groep in re.findall(r'(?:afwijking_)?soort in \(([^)]*)\)', tekst) for s in re.findall(r'"([a-z][a-z0-9_]+)"', groep)}
        gevonden -= {"afwijking", "let_op", "fout", "geaccepteerd", "uitgesloten", "gezien", "meten", "bank"}
        ontbrekend = {s for s in gevonden if "_" in s} - set(soort_stand.REGISTRY)
        assert not ontbrekend, f"afwijkingssoort(en) mét tekst maar zonder registry-entry (start dan stil in actie/meten?): {sorted(ontbrekend)}"

    def test_nieuwe_soorten_starten_in_meten_en_onbekend_is_meten(self) -> None:
        for d in soort_stand.REGISTRY.values():
            if d.sinds >= soort_stand.REGISTRY_SINDS or d.soort == "dubbele_betaling_vermoed":
                assert d.default == soort_stand.METEN, f"{d.soort} is nieuw maar start niet in meten"
        assert soort_stand.code_default("dubbele_betaling_vermoed") == "meten"
        assert soort_stand.code_default("bedrag_wijkt_af") == "actie"
        assert soort_stand.code_default("nog_nooit_gezien") == "meten"
        # Override wint; een onbekende override-waarde telt niet.
        assert soort_stand.stand_van("dubbele_betaling_vermoed", {"dubbele_betaling_vermoed": "actie"}) == "actie"
        assert soort_stand.stand_van("bedrag_wijkt_af", {"bedrag_wijkt_af": "meten"}) == "meten"
        assert soort_stand.stand_van("bedrag_wijkt_af", {"bedrag_wijkt_af": "onzin"}) == "actie"

    def test_in_meting_alleen_voor_afwijkingen_van_een_meten_soort(self) -> None:
        b = Bevinding("bank", "afwijking", None, "v", "t", {"afwijking_soort": "dubbele_betaling_vermoed"})
        assert soort_stand.in_meting(b, None)
        assert not soort_stand.in_meting(b, {"dubbele_betaling_vermoed": "actie"})
        assert not soort_stand.in_meting(Bevinding("bank", "let_op", None, "v", "t", {"afwijking_soort": "dubbele_betaling_vermoed"}), None)
        assert not soort_stand.in_meting(Bevinding("documenten", "afwijking", None, "v", "t", {"afwijking_soort": "bedrag_wijkt_af"}), None)

    def test_explosie_rem_alleen_boven_de_drempel_en_alleen_voor_actie_soorten(self) -> None:
        tellers = {"bedrag_wijkt_af": soort_stand.EXPLOSIE_DREMPEL + 1, "ontbreekt_in_rlz": soort_stand.EXPLOSIE_DREMPEL, "dubbele_betaling_vermoed": 1214}
        assert soort_stand.geexplodeerd(tellers, {}) == {"bedrag_wijkt_af": soort_stand.EXPLOSIE_DREMPEL + 1}
        assert soort_stand.geexplodeerd(tellers, {"dubbele_betaling_vermoed": "actie"}) == {
            "bedrag_wijkt_af": soort_stand.EXPLOSIE_DREMPEL + 1,
            "dubbele_betaling_vermoed": 1214,
        }
        assert auto.BEVINDINGSSOORT_EXPLODEERT == soort_stand.EXPLOSIE_CATEGORIE in auto.REGRESSIE_CATEGORIEEN


class TestActiemail:
    def test_meten_soort_niet_in_de_actiemail_wel_geteld(self) -> None:
        aid = uuid.UUID("aaaaaaaa-0000-0000-0000-00000000000a")
        meten = Bevinding("bank", "afwijking", aid, "m1", "t", {**_dubbel_kw(aid, "m1")["detail"], "stand": "meten"})
        actie = Bevinding("documenten", "afwijking", aid, "a1", "t", _afwijking_kw(aid, "a1")["detail"])
        delta = Delta(nieuwe_afwijkingen=[meten, actie])
        assert actie_bevindingen(delta) == [actie]
        assert actie_bevindingen(delta, soort_overrides={"dubbele_betaling_vermoed": "actie"}) == [meten, actie]

    def test_maximaal_drie_regels_per_administratie_en_teller_per_administratie_in_de_afkap(self) -> None:
        aid_a, aid_b = list(NAMEN)
        bev = [Bevinding("documenten", "afwijking", aid_a, f"a{i}", "t", _afwijking_kw(aid_a, f"a{i}")["detail"]) for i in range(30)]
        bev += [Bevinding("documenten", "afwijking", aid_b, f"b{i}", "t", _afwijking_kw(aid_b, f"b{i}")["detail"]) for i in range(5)]
        onderwerp, tekst = bouw_actiemail(bevindingen=bev, namen=NAMEN)
        regels = [r for r in tekst.splitlines() if r.startswith("- ")]
        assert sum(r.startswith(f"- {NAMEN[aid_a]} — ") for r in regels) == 3
        assert sum(r.startswith(f"- {NAMEN[aid_b]} — ") for r in regels) == 3
        assert f"- en 29 andere ({NAMEN[aid_a]} 27, {NAMEN[aid_b]} 2)" in regels
        assert onderwerp == "Boekhouding: 35 zaken vragen je aandacht"
        assert "1204 andere" not in tekst


class TestRunEndToEnd:
    def test_dubbele_betaling_telt_maar_mailt_niet_en_staat_onder_het_facet_meten(self, administratie_id, beheerder_id, mails) -> None:
        blokken = [("bank", _blok([_dubbel_kw(administratie_id, "d1"), _dubbel_kw(administratie_id, "d2")], exit_code=1))]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        assert mails == [], "een soort in stand meten mailt nooit — ook niet als systeemmail (geen LET-OP)"
        run = _laatste_run()
        assert run.samenvatting["bank"]["afwijkingen"] == 2
        with scoped_session(administratie_id) as session:
            rijen = list(session.scalars(select(ReconciliatieBevinding).where(ReconciliatieBevinding.run_id == run.id)))
        assert len(rijen) == 2 and all((r.detail or {}).get("stand") == "meten" for r in rijen)
        # Kantoorbrede lijst: facet "meten", niet in "aandacht"; KPI-teller telt ze niet.
        from app.db.models import GebruikerRol

        lijst = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, soort="meten")
        assert lijst.totaal == 2 and lijst.tellers.meten == 2 and lijst.tellers.afwijkingen == 0
        aandacht = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, soort="aandacht")
        assert aandacht.totaal == 0
        assert kantoorbreed.stand(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER).teller == 0

    def test_promotie_door_beheerder_brengt_de_soort_in_de_actiemail(self, administratie_id, beheerder_id, mails) -> None:
        standen = kantoorbreed.zet_soort_stand(soort="dubbele_betaling_vermoed", stand="actie", actor_id=beheerder_id, reden="nameting 17-09: 3 echte bevindingen")
        assert next(s for s in standen if s["soort"] == "dubbele_betaling_vermoed")["stand"] == "actie"
        with scoped_session(None) as session:
            rij = session.get(ReconciliatieInstelling, True)
            assert rij.soort_standen == {"dubbele_betaling_vermoed": "actie"}
            audit = session.scalars(select(AuditEvent).where(AuditEvent.actie == "bevindingssoort_naar_actie")).all()
        assert len(audit) == 1 and audit[0].nieuwe_waarde["reden"].startswith("nameting 17-09")
        blokken = [("bank", _blok([_dubbel_kw(administratie_id, "d1")], exit_code=1))]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        assert len(mails) == 1 and "Mogelijk dubbel betaald" in mails[0]["tekst"]
        with pytest.raises(kantoorbreed.ReconciliatieFout):
            kantoorbreed.zet_soort_stand(soort="bestaat_niet", stand="actie", actor_id=beheerder_id, reden="x")

    def test_explosie_rem_zet_soort_terug_naar_meten_met_systeemfout_let_op(self, administratie_id, beheerder_id, mails) -> None:
        kantoorbreed.zet_soort_stand(soort="dubbele_betaling_vermoed", stand="actie", actor_id=beheerder_id, reden="test")
        n = soort_stand.EXPLOSIE_DREMPEL + 1
        blokken = [("bank", _blok([_dubbel_kw(administratie_id, f"d{i}") for i in range(n)], exit_code=1))]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        # Geen actiemail (de soort is teruggezet vóór de mail); wél een systeemmail mét de LET-OP.
        systeem = [m for m in mails if m["onderwerp"].startswith("[systeem]")]
        assert len(systeem) == 1 and len(mails) == 1, [m["onderwerp"] for m in mails]
        assert "explodeert" in systeem[0]["tekst"] and "1204 andere" not in systeem[0]["tekst"]
        with scoped_session(None) as session:
            rij = session.get(ReconciliatieInstelling, True)
            assert rij.soort_standen["dubbele_betaling_vermoed"] == "meten"
            terug = session.scalars(select(AuditEvent).where(AuditEvent.actie == "bevindingssoort_naar_meten")).all()
            regressie = session.scalars(select(AuditEvent).where(AuditEvent.actie == "automatisering_regressie")).all()
        assert len(terug) == 1 and "explosie-rem" in terug[0].nieuwe_waarde["reden"]
        assert len(regressie) == 1, "de explosie is een systeemfout: audit voor de bewaking"
        run = _laatste_run()
        assert run.samenvatting[auto.BLOK]["let_op"] == 1

    def test_verdwenen_dubbele_betaling_bevindingen_automatisch_gesloten_met_audit(self, administratie_id, mails) -> None:
        # Run 1 (oude definitie: 3 valse bevindingen) → run 2 (herdefinitie: 1 blijft) → 2 automatisch gesloten.
        run_service.voer_uit(blokken=[("bank", _blok([_dubbel_kw(administratie_id, f"v{i}") for i in range(3)], exit_code=1))], args=ARGS, bron="cli", stdout=lambda t: None)
        run_service.voer_uit(blokken=[("bank", _blok([_dubbel_kw(administratie_id, "v0")], exit_code=1))], args=ARGS, bron="cli", stdout=lambda t: None)
        with scoped_session(None) as session:
            audit = session.scalars(select(AuditEvent).where(AuditEvent.actie == "reconciliatie_auto_gesloten")).all()
        assert len(audit) == 1
        nw = audit[0].nieuwe_waarde
        assert nw["aantal"] == 2 and sorted(nw["vingerafdrukken"]) == ["v1", "v2"] and "herdefinitie 17-09" in nw["reden"]
        assert mails == []


    def test_verdwenen_fout_en_afwijking_automatisch_gesloten_met_audit(self, administratie_id, mails) -> None:
        """Nameting 20-09 (174 × ic_spiegel_rood): tot 19-09 schreef alleen `dubbele_betaling_vermoed` een audit; een
        verdwenen FOUT of andere afwijking verdween stil. Nu één `reconciliatie_auto_gesloten` per soort × administratie,
        ook voor fouten."""
        fout_kw = {
            "soort": "fout",
            "administratie_id": None,
            "vingerafdruk": "spiegel-1",
            "tekst": "FOUT       doorbelastingspaar niet sluitend: verkoopfactuur niet gevonden [vaf:spiegel-1]",
            "detail": {"afwijking_soort": "ic_spiegel_rood", "fout": "verkoopfactuur niet gevonden"},
        }
        fout2_kw = {**fout_kw, "vingerafdruk": "spiegel-2", "tekst": fout_kw["tekst"].replace("spiegel-1", "spiegel-2")}
        run1 = [("intercompany", _blok([fout_kw, fout2_kw, _afwijking_kw(administratie_id, "a1")], exit_code=1))]
        run_service.voer_uit(blokken=run1, args=ARGS, bron="cli", stdout=lambda t: None)
        eerste = _laatste_run()
        leeg = [("intercompany", _blok([], exit_code=0))]
        run_service.voer_uit(blokken=leeg, args=ARGS, bron="cli", stdout=lambda t: None)
        with scoped_session(None) as session:
            audit = session.scalars(select(AuditEvent).where(AuditEvent.actie == "reconciliatie_auto_gesloten")).all()
        per_soort = {a.nieuwe_waarde["soort"]: a.nieuwe_waarde for a in audit}
        assert set(per_soort) == {"ic_spiegel_rood", "bedrag_wijkt_af"}, per_soort
        spiegel = per_soort["ic_spiegel_rood"]
        assert spiegel["aantal"] == 2 and sorted(spiegel["vingerafdrukken"]) == ["spiegel-1", "spiegel-2"]
        assert spiegel["bevinding_soort"] == "fout" and spiegel["blok"] == "intercompany"
        assert spiegel["administratie_id"] is None
        assert "niet meer geproduceerd door run" in spiegel["reden"] and str(eerste.id) not in spiegel["reden"]
        assert per_soort["bedrag_wijkt_af"]["aantal"] == 1
        assert per_soort["bedrag_wijkt_af"]["administratie_id"] == str(administratie_id)
        # De delta-tellers staan op de run-rij (meetbaar op de leesreplica, ook als de systeemmail uit staat).
        tweede = _laatste_run()
        assert tweede.samenvatting["delta"] == {
            "nieuwe_afwijkingen": 0, "nieuwe_let_op": 0, "nieuwe_geaccepteerd": 0, "nieuwe_fouten": 0,
            "verdwenen_afwijkingen": 1, "verdwenen_fouten": 2, "blokken_fout": [],
        }
        assert eerste.samenvatting["delta"]["nieuwe_fouten"] == 2
        assert eerste.samenvatting["delta"]["nieuwe_afwijkingen"] == 1
        # Een derde run zonder wijziging schrijft niets bij (idempotent: alleen de delta t.o.v. de vorige afgeronde run)
        run_service.voer_uit(blokken=leeg, args=ARGS, bron="cli", stdout=lambda t: None)
        with scoped_session(None) as session:
            q = select(AuditEvent).where(AuditEvent.actie == "reconciliatie_auto_gesloten")
            assert len(session.scalars(q).all()) == 2


class TestCli:
    def test_cli_overzicht_lees_only_en_zetten_met_reden(self, capsys, beheerder_id) -> None:
        from app import cli

        assert cli.main(["bevindingssoort-stand"]) == 0
        uit = capsys.readouterr().out
        assert "dubbele_betaling_vermoed" in uit and "meten" in uit
        assert cli.main(["bevindingssoort-stand", "dubbele_betaling_vermoed", "--stand", "actie"]) == 2  # zonder reden
        assert cli.main(["bevindingssoort-stand", "dubbele_betaling_vermoed", "--stand", "actie", "--reden", "nameting"]) == 0
        assert "→ actie" in capsys.readouterr().out
        assert cli.main(["bevindingssoort-stand", "onbekend", "--stand", "actie", "--reden", "x"]) == 2
