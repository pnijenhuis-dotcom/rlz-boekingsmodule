# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Reconciliatieblok `intake` — postvak-bewaking "ontvangen vs verwerkt" (Peter 22-09, opdracht C): telling aan de
bron (INBOX + spam, gelezen én ongelezen) ↔ verwerkt-administratie; verschil = actie-bevinding mét Message-ID's en
"Nu verwerken"; verbinding stuk of kanaal-mét-job niet geconfigureerd = FOUT (systeemfout, nooit stil); declaraties@
(geen job) zichtbaar overgeslagen; uit Spam verwerkt = LET-OP per afzender; dagteller uit het audit
`intake_postvak_run`. Plus de route POST /reconciliatie/intake/{kanaal}/nu-verwerken."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import settings
from app.intake import bewaking, nu_verwerken, verwerkt
from app.intake.postvak import INBOX, PostvakFout, PostvakKop
from app.main import app
from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import soort_stand, teksten
from app.reconciliatie.run import Verzamelaar
from app.security.tokens import create_access_token
from tests.uren.conftest import maak_gebruiker

SPAM = "[Gmail]/Spam"
NU = datetime(2026, 9, 23, 4, 30, tzinfo=UTC)  # 06:30 NL
client = TestClient(app)


def _kop(mid: str, *, map: str = INBOX, uren_terug: int = 5, gelezen: bool = False, afzender: str = "lev@x.example") -> PostvakKop:
    return PostvakKop(
        uid=str(abs(hash(mid)) % 10000),
        map=map,
        message_id=mid,
        afzender=afzender,
        onderwerp=f"Factuur {mid[:8]}",
        datum=NU - timedelta(hours=uren_terug),
        gelezen=gelezen,
    )


@pytest.fixture
def alle_kanalen_geconfigureerd(monkeypatch: pytest.MonkeyPatch) -> None:
    for prefix, gebruiker in (("intake_imap", "facturen@ak-nijenhuis.nl"), ("intake_kempengroep_imap", "facturen@kempengroep.nl")):
        monkeypatch.setattr(settings, f"{prefix}_host", "imap.gmail.com")
        monkeypatch.setattr(settings, f"{prefix}_gebruiker", gebruiker)
        monkeypatch.setattr(settings, f"{prefix}_wachtwoord", "x")


class TestToetsPuur:
    def test_ontbrekend_is_kop_in_venster_zonder_bekende_sleutel(self) -> None:
        koppen = [_kop("<a@x>"), _kop("<b@x>", map=SPAM), _kop("<oud@x>", uren_terug=72), _kop("<c@x>", gelezen=True)]
        v = bewaking.toets("facturen", koppen, {"<a@x>"}, sinds=NU - timedelta(hours=28))
        assert (v.in_postvak, v.in_inbox, v.in_spam, v.bekend) == (3, 2, 1, 1)
        assert [k.sleutel for k in v.ontbrekend] == ["<b@x>", "<c@x>"]  # gelezen telt gewoon mee — dát was het gat

    def test_vingerafdruk_stabiel_per_set(self) -> None:
        assert bewaking.vingerafdruk("facturen", ["<b@x>", "<a@x>"]) == bewaking.vingerafdruk("facturen", ["<a@x>", "<b@x>"])
        assert bewaking.vingerafdruk("facturen", ["<a@x>"]) != bewaking.vingerafdruk("facturen_kempengroep", ["<a@x>"])

    def test_gisteren_begin_is_nl_kalenderdag(self) -> None:
        # 23-09 04:30 UTC = 06:30 NL → gisteren 00:00 NL = 21-09 22:00 UTC
        assert verwerkt.gisteren_begin_utc(NU) == datetime(2026, 9, 21, 22, 0, tzinfo=UTC)


class TestCliBlok:
    def test_verschil_is_actie_bevinding_met_message_ids_en_exit_1(self, alle_kanalen_geconfigureerd, admin_engine) -> None:
        verwerkt.registreer(kanaal="facturen", sleutel="<bekend@x>", uid="1", postvak_map=INBOX, uitkomst="verwerkt", intake_bericht_id=None)

        def lezer(kanaal: str, sinds: datetime) -> list[PostvakKop]:
            if kanaal == "facturen":
                return [_kop("<bekend@x>"), _kop("<mist@x>", gelezen=True), _kop("<spam@x>", map=SPAM)]
            return []

        v = Verzamelaar()
        v.start_blok(bewaking.BLOK)
        regels: list[str] = []
        code = bewaking.cli_blok(None, v, stdout=regels.append, lezer=lezer, nu=NU)
        assert code == 1
        afwijkingen = [b for b in v.bevindingen if b.soort == "afwijking"]
        assert len(afwijkingen) == 1
        b = afwijkingen[0]
        assert b.blok == "intake" and b.administratie_id is None
        assert b.detail["afwijking_soort"] == "intake_postvak_verschil" and b.detail["kanaal"] == "facturen"
        assert [x["message_id"] for x in b.detail["berichten"]] == ["<mist@x>", "<spam@x>"]
        assert b.detail["berichten"][0]["gelezen"] is True and b.detail["berichten"][1]["map"] == SPAM
        assert any("VERSCHIL 2" in r for r in regels)
        # De kempengroep-regel (leeg postvak) staat er ook: geen verschil, wél geteld.
        assert any("facturen@kempengroep.nl" in r and "VERSCHIL 0" in r for r in regels)
        assert v.blokken["intake"].gecontroleerd == 2
        # Leesbaar: titel/wat/doe zonder GUID's, mét de handeling.
        lees = teksten.leesbaar(b)
        assert "niet verwerkt" in lees.titel and "Nu verwerken" in lees.doe and not teksten.bevat_technische_sleutel(lees.wat)
        # De soort start DIRECT in actie (besluit Peter) — mét reden in de registry.
        assert soort_stand.code_default("intake_postvak_verschil") == "actie"

    def test_geen_verschil_is_ok_exit_0(self, alle_kanalen_geconfigureerd) -> None:
        verwerkt.registreer(kanaal="facturen", sleutel="<ok@x>", uid="1", postvak_map=INBOX, uitkomst="verwerkt", intake_bericht_id=None)
        v = Verzamelaar()
        v.start_blok(bewaking.BLOK)
        code = bewaking.cli_blok(None, v, stdout=lambda r: None, lezer=lambda k, s: [_kop("<ok@x>")] if k == "facturen" else [], nu=NU)
        assert code == 0 and [b for b in v.bevindingen if b.soort != "let_op"] == []

    def test_verbinding_stuk_is_fout_bevinding_nooit_stil(self, alle_kanalen_geconfigureerd) -> None:
        def lezer(kanaal: str, sinds: datetime) -> list[PostvakKop]:
            raise PostvakFout("IMAP-login geweigerd voor facturen@kempengroep.nl — controleer het app-wachtwoord")

        v = Verzamelaar()
        v.start_blok(bewaking.BLOK)
        regels: list[str] = []
        code = bewaking.cli_blok(None, v, stdout=regels.append, lezer=lezer, nu=NU)
        assert code == 1
        fouten = [b for b in v.bevindingen if b.soort == "fout"]
        assert {b.detail["kanaal"] for b in fouten} == {"facturen", "facturen_kempengroep"}
        assert all(b.detail["reden"] == "intake_postvak_verbinding" for b in fouten)
        lees = teksten.leesbaar(fouten[0])
        assert lees.titel.startswith("Postvak niet bereikbaar") and "app-wachtwoord" in lees.doe

    def test_kanaal_met_job_niet_geconfigureerd_is_fout_declaraties_overgeslagen(self, monkeypatch) -> None:
        # Code-defaults: niets geconfigureerd. facturen + facturen_kempengroep hebben een job → FOUT; declaraties → regel.
        v = Verzamelaar()
        v.start_blok(bewaking.BLOK)
        regels: list[str] = []
        code = bewaking.cli_blok(None, v, stdout=regels.append, lezer=lambda k, s: [], nu=NU)
        assert code == 1
        fouten = sorted(b.detail["kanaal"] for b in v.bevindingen if b.soort == "fout")
        assert fouten == ["facturen", "facturen_kempengroep"]
        assert all(b.detail["reden"] == "intake_postvak_niet_geconfigureerd" for b in v.bevindingen if b.soort == "fout")
        assert any(r.startswith("OVERGESLAGEN postvak declaraties@ak-nijenhuis.nl") for r in regels)
        lees = teksten.leesbaar([b for b in v.bevindingen if b.soort == "fout"][0])
        assert lees.titel.startswith("Postvak niet bewaakt") and "rlz-reconciliatie" in lees.doe

    def test_uit_spam_verwerkt_is_let_op_per_afzender_met_domein(self, alle_kanalen_geconfigureerd) -> None:
        treffers = [
            verwerkt.SpamTreffer("facturen", "<s1@x>", "Facturen@Strikt.example", "Factuur 1", NU, None, "verwerkt"),
            verwerkt.SpamTreffer("facturen", "<s2@x>", "facturen@strikt.example", "Factuur 2", NU, None, "verwerkt"),
            verwerkt.SpamTreffer("facturen_kempengroep", "<s3@x>", "ander@los.example", "Factuur 3", NU, None, "verwerkt"),
        ]
        let_ops = bewaking.spam_let_ops(nu=NU, treffers=treffers)
        assert [(lo["detail"]["kanaal"], lo["detail"]["afzender"], lo["detail"]["aantal"], lo["detail"]["domein"]) for lo in let_ops] == [
            ("facturen", "facturen@strikt.example", 2, "strikt.example"),
            ("facturen_kempengroep", "ander@los.example", 1, "los.example"),
        ]
        assert all(lo["soort"] == "let_op" and lo["blok"] == "intake" and lo["detail"]["reden"] == "intake_uit_spam" for lo in let_ops)
        v = Verzamelaar()
        v.start_blok(bewaking.BLOK)
        v.bevinding(**let_ops[0])
        lees = teksten.leesbaar(v.bevindingen[0])
        assert "Spam" in lees.titel and "strikt.example" in lees.doe and "Workspace" in lees.doe

    def test_spam_let_op_uit_de_tabel(self, alle_kanalen_geconfigureerd) -> None:
        verwerkt.registreer(
            kanaal="facturen", sleutel="<uit-spam@x>", uid="9", postvak_map=SPAM, uitkomst="verwerkt", intake_bericht_id=None,
            detail={"afzender": "boekhouding@dmarc-strikt.example", "onderwerp": "Factuur 77"},
        )
        v = Verzamelaar()
        v.start_blok(bewaking.BLOK)
        bewaking.cli_blok(None, v, stdout=lambda r: None, lezer=lambda k, s: [], nu=datetime.now(UTC))
        let_ops = [b for b in v.bevindingen if b.soort == "let_op"]
        assert len(let_ops) == 1 and let_ops[0].detail["afzender"] == "boekhouding@dmarc-strikt.example"

    def test_blok_staat_in_run_blokken_en_de_alleen_keuzelijst(self) -> None:
        from app.reconciliatie import run

        assert "intake" in run.BLOKKEN


class TestDagteller:
    def test_intake_postvak_run_audit_voedt_de_teller(self) -> None:
        nu = datetime.now(UTC)
        feiten = auto.Feiten(
            audit=[
                auto.AuditFeit(
                    "intake_postvak_run",
                    nu - timedelta(hours=2),
                    None,
                    {"kanaal": "facturen", "gezien": 12, "verwerkt": 3, "al_bekend": 1, "niet_verwerkbaar": 1, "uit_spam": 2, "dubbel_via_forward": 1},
                ),
                auto.AuditFeit(
                    "intake_postvak_run",
                    nu - timedelta(hours=1),
                    None,
                    {"kanaal": "facturen_kempengroep", "gezien": 4, "verwerkt": 2, "al_bekend": 0, "niet_verwerkbaar": 0, "uit_spam": 0, "dubbel_via_forward": 0},
                ),
            ]
        )
        tellers = {t.sleutel: t for t in auto.bereken(feiten, nu=nu)}
        t = tellers[auto.INTAKE_POSTVAK]
        assert (t.dag.gedaan, t.dag.verwacht) == (5, 10)
        assert t.dag.overgeslagen == {
            auto.POSTVAK_AL_BEKEND: 1,
            auto.POSTVAK_NIET_VERWERKBAAR: 1,
            auto.POSTVAK_UIT_SPAM: 2,
            auto.POSTVAK_DUBBEL_VIA_FORWARD: 1,
        }
        assert t.detail["per_kanaal"]["facturen"] == {"runs": 1, "gezien": 12, "verwerkt": 3}
        assert t.detail["per_kanaal"]["facturen_kempengroep"]["gezien"] == 4
        # Zachte redenen: geen harde-voorwaarde-LET-OP.
        assert not [b for b in auto.bevindingen([t]) if b.get("soort") == "let_op"]
        assert any("Intake-postvakken" in r for r in auto.regels([t]))


class TestNuVerwerkenRoute:
    def _headers(self, admin_engine: Engine) -> dict[str, str]:
        gid = maak_gebruiker(admin_engine, "boekhouding", "Boekhouder Postvak")
        return {"Authorization": f"Bearer {create_access_token(gid, rol='boekhouding')}"}

    def test_start_thread_in_dev_en_schrijft_audit(self, admin_engine: Engine, monkeypatch) -> None:
        gestart: list[list[str]] = []
        monkeypatch.setattr(nu_verwerken, "_thread", lambda argv: gestart.append(list(argv)))
        r = client.post("/reconciliatie/intake/facturen_kempengroep/nu-verwerken", headers=self._headers(admin_engine))
        assert r.status_code == 202, r.text
        assert r.json() == {"kanaal": "facturen_kempengroep", "postvak_adres": "facturen@kempengroep.nl", "voertuig": "thread", "job_resource": None}
        import time

        for _ in range(50):
            if gestart:
                break
            time.sleep(0.02)
        assert gestart == [["intake-postvak-kempengroep-verwerken"]]
        with admin_engine.connect() as conn:
            nw = conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'intake_postvak_nu_verwerken' ORDER BY tijdstip DESC LIMIT 1")
            ).scalar_one()
        assert (nw["kanaal"], nw["voertuig"], nw["uitkomst"]) == ("facturen_kempengroep", "thread", "gestart")

    def test_cloud_run_job_via_resource_en_502_bij_mislukte_trigger(self, admin_engine: Engine, monkeypatch) -> None:
        from app.projecten import cijfers_run

        monkeypatch.setattr(settings, "intake_imap_job_resource", "projects/p/locations/l/jobs/rlz-intake-imap")
        aangeroepen: list[str] = []
        monkeypatch.setattr(cijfers_run, "_trigger_cloud_run_job", lambda res: aangeroepen.append(res))
        r = client.post("/reconciliatie/intake/facturen/nu-verwerken", headers=self._headers(admin_engine))
        assert r.status_code == 202 and r.json()["voertuig"] == "cloud_run_job"
        assert aangeroepen == ["projects/p/locations/l/jobs/rlz-intake-imap"]

        def kapot(res: str) -> None:
            raise RuntimeError("403 run.jobs.run ontbreekt")

        monkeypatch.setattr(cijfers_run, "_trigger_cloud_run_job", kapot)
        r = client.post("/reconciliatie/intake/facturen/nu-verwerken", headers=self._headers(admin_engine))
        assert r.status_code == 502 and "403" in r.json()["detail"]
        with admin_engine.connect() as conn:
            nw = conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'intake_postvak_nu_verwerken' ORDER BY tijdstip DESC LIMIT 1")
            ).scalar_one()
        assert nw["uitkomst"] == "mislukt" and "403" in nw["fout"]

    def test_onbekend_kanaal_404_en_zonder_token_401(self, admin_engine: Engine) -> None:
        assert client.post("/reconciliatie/intake/declaraties/nu-verwerken", headers=self._headers(admin_engine)).status_code == 404
        assert client.post("/reconciliatie/intake/facturen/nu-verwerken").status_code == 401
