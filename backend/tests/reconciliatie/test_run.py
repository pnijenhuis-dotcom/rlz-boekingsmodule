# ruff: noqa: F811 — pytest-fixtures als parameters
"""Reconciliatie-melding (opdracht 06-09 blok A + B): elke reconciliatie-alles-run wordt vastgelegd
(run-rij + bevindingen, ook bij een blokcrash), de delta t.o.v. de vorige afgeronde run bepaalt of er
gemaild wordt (nieuw/ongewijzigd/verdwenen per soort; ongewijzigde LET-OP-set = géén mail; één nieuwe
afwijking = wél mail; verdwijnen = herstelmelding) en een mailfout maakt de job nooit rood."""

from __future__ import annotations

import argparse
import re
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app import cli
from app.berichten import mail
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.reconciliatie import run as run_service
from app.reconciliatie.models import ReconciliatieRun
from app.reconciliatie.run import Bevinding, Delta, bepaal_delta, bouw_mail
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

ARGS = argparse.Namespace()


def _b(
    soort: str, aid: uuid.UUID | None, vaf: str, tekst: str = "regel", blok: str = "documenten", **detail
) -> Bevinding:
    return Bevinding(
        blok=blok, soort=soort, administratie_id=aid, vingerafdruk=vaf, tekst=tekst, detail=detail or None
    )


class TestDelta:
    def test_eerste_run_ooit_is_alles_nieuw(self) -> None:
        aid = uuid.uuid4()
        huidig = [
            _b("afwijking", aid, "a1"),
            _b("let_op", aid, "l1"),
            _b("geaccepteerd", aid, "g1"),
            _b("fout", aid, "f1"),
        ]
        d = bepaal_delta(huidig=huidig, vorig=None, gezien=set(), samenvatting={"documenten": {"status": "actie"}})
        assert [b.vingerafdruk for b in d.nieuwe_afwijkingen] == ["a1"]
        assert [b.vingerafdruk for b in d.nieuwe_let_op] == ["l1"]
        assert [b.vingerafdruk for b in d.nieuwe_geaccepteerd] == ["g1"]
        assert [b.vingerafdruk for b in d.nieuwe_fouten] == ["f1"]
        assert d.verdwenen_afwijkingen == [] and d.blokken_fout == []
        assert not d.is_leeg and d.aantal_nieuwe_aandachtspunten == 4

    def test_ongewijzigde_let_op_set_is_leeg_geen_mail(self) -> None:
        aid = uuid.uuid4()
        vorig = [_b("let_op", aid, "l1"), _b("let_op", aid, "l2")]
        huidig = [_b("let_op", aid, "l1", tekst="andere tekst, zelfde concept"), _b("let_op", aid, "l2")]
        d = bepaal_delta(huidig=huidig, vorig=vorig, gezien=set(), samenvatting={"doorbelasting": {"status": "ok"}})
        assert d.is_leeg

    def test_een_nieuwe_afwijking_bij_ongewijzigde_rest(self) -> None:
        aid = uuid.uuid4()
        vorig = [_b("let_op", aid, "l1"), _b("afwijking", aid, "a1")]
        huidig = [*vorig, _b("afwijking", aid, "a2")]
        d = bepaal_delta(huidig=huidig, vorig=vorig, gezien=set(), samenvatting={})
        assert [b.vingerafdruk for b in d.nieuwe_afwijkingen] == ["a2"]
        assert d.nieuwe_let_op == [] and d.verdwenen_afwijkingen == []

    def test_verdwenen_afwijking_is_herstelmelding(self) -> None:
        aid = uuid.uuid4()
        vorig = [_b("afwijking", aid, "a1"), _b("afwijking", aid, "a2")]
        huidig = [_b("afwijking", aid, "a1")]
        d = bepaal_delta(huidig=huidig, vorig=vorig, gezien=set(), samenvatting={})
        assert [b.vingerafdruk for b in d.verdwenen_afwijkingen] == ["a2"]
        assert d.nieuwe_afwijkingen == [] and not d.is_leeg
        assert d.aantal_nieuwe_aandachtspunten == 0

    def test_afwijking_die_geaccepteerd_wordt_is_nieuw_geaccepteerd_geen_herstel(self) -> None:
        """Zelfde vingerafdruk, andere soort: de afwijking is niet 'verdwenen' maar beoordeeld."""
        aid = uuid.uuid4()
        vorig = [_b("afwijking", aid, "a1")]
        huidig = [_b("geaccepteerd", aid, "a1")]
        d = bepaal_delta(huidig=huidig, vorig=vorig, gezien=set(), samenvatting={})
        assert [b.vingerafdruk for b in d.nieuwe_geaccepteerd] == ["a1"]
        assert d.verdwenen_afwijkingen == []

    def test_geziene_let_op_telt_niet_als_nieuw(self) -> None:
        aid = uuid.uuid4()
        huidig = [_b("let_op", aid, "l1"), _b("let_op", aid, "l2")]
        d = bepaal_delta(huidig=huidig, vorig=[], gezien={(aid, "l1")}, samenvatting={})
        assert [b.vingerafdruk for b in d.nieuwe_let_op] == ["l2"]

    def test_zelfde_vingerafdruk_op_andere_administratie_is_nieuw(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        d = bepaal_delta(
            huidig=[_b("afwijking", b, "x")], vorig=[_b("afwijking", a, "x")], gezien=set(), samenvatting={}
        )
        assert len(d.nieuwe_afwijkingen) == 1 and len(d.verdwenen_afwijkingen) == 1

    def test_omgevallen_blok_maakt_delta_niet_leeg(self) -> None:
        d = bepaal_delta(
            huidig=[], vorig=[], gezien=set(), samenvatting={"bank": {"status": "fout"}, "omzet": {"status": "ok"}}
        )
        assert d.blokken_fout == ["bank"] and not d.is_leeg


class TestBouwMail:
    def test_onderwerp_body_leesbare_tekst_en_technische_regel(self) -> None:
        """Blok A8 (07-09): de mail draagt per bevinding DEZELFDE leesbare tekst als de UI ("[administratie]
        titel — wat" + "→ doe"); de CLI-regel mét GUID's en de vingerafdruk (sleutel voor de CLI-acceptatie)
        staan als technische regel erónder — nooit meer als hoofdregel."""
        aid = uuid.uuid4()
        doc = uuid.uuid4()
        delta = Delta(
            nieuwe_afwijkingen=[
                _b(
                    "afwijking",
                    aid,
                    "a1",
                    tekst=f"AFWIJKING  {aid} boeking={doc} soort=half_geboekt [vaf:a1]: Periode 2026-08-01 t/m "
                    "2026-08-31: verkoopfactuur staat (mogelijk) geboekt zonder kostprijsmemoriaal — x",
                    blok="omzet",
                    bron="omzet",
                    afwijking_soort="half_geboekt",
                    detail="Periode 2026-08-01 t/m 2026-08-31: verkoopfactuur staat (mogelijk) geboekt zonder "
                    "kostprijsmemoriaal — x",
                    totaal_omzet="15230.10",
                ),
                _b(
                    "afwijking",
                    aid,
                    "a2",
                    tekst=f"document={doc} rlz_document={uuid.uuid4()} soort=bedrag_wijkt_af [vaf:a2]: "
                    "eigen=€274.89 rlz=€279.51",
                    bron="documenten",
                    afwijking_soort="bedrag_wijkt_af",
                    detail="eigen=€274.89 rlz=€279.51",
                    leverancier_naam="Kader Consultancy",
                    factuurnummer="F212604921",
                    rlz_boekstuk="RLZ-01-00000241",
                    bedrag_lokaal="274.89",
                    bedrag_extern="279.51",
                ),
            ],
            nieuwe_let_op=[
                _b(
                    "let_op",
                    aid,
                    "l1",
                    tekst=f"LET-OP     opruim-kandidaat [gestorneerd] verkoop_bron {uuid.uuid4()} "
                    f"in administratie {aid}",
                    kant="verkoop_bron",
                    reden="gestorneerd",
                    referentie="24713188",
                )
            ],
            nieuwe_geaccepteerd=[
                _b(
                    "geaccepteerd",
                    aid,
                    "g1",
                    tekst="GEACCEPTEERD regel",
                    bron="documenten",
                    afwijking_soort="ontbreekt_in_rlz",
                    detail="404",
                    leverancier_naam="Labo Derva",
                    factuurnummer="2026-118",
                )
            ],
            nieuwe_fouten=[_b("fout", None, "f1", tekst="FOUT       bank-reconciliatie viel om: boem", blok="bank")],
            verdwenen_afwijkingen=[
                _b(
                    "afwijking", aid, "oud", tekst="oude afwijking", bron="documenten",
                    afwijking_soort="bedrag_wijkt_af", detail="eigen=€1 rlz=€2", leverancier_naam="Oud BV",
                )
            ],
            blokken_fout=["bank"],
        )
        samenvatting = {
            "bank": {
                "status": "fout",
                "gecontroleerd": 0,
                "afwijkingen": 0,
                "geaccepteerd": 0,
                "let_op": 0,
                "fouten": 1,
                "foutmelding": "RuntimeError: boem",
            },
            "documenten": {
                "status": "actie",
                "gecontroleerd": 12,
                "afwijkingen": 2,
                "geaccepteerd": 1,
                "let_op": 0,
                "fouten": 0,
            },
        }
        onderwerp, tekst = bouw_mail(
            run_id=uuid.uuid4(),
            bron="scheduler",
            afgerond_op=datetime(2026, 9, 6, 4, 31, tzinfo=UTC),
            exit_code=1,
            samenvatting=samenvatting,
            delta=delta,
            open_afwijkingen=2,
            namen={aid: "Kempen Facilities B.V."},
        )
        assert onderwerp == "RLZ reconciliatie 06-09-2026: 2 afwijking(en) · 6 nieuwe aandachtspunt(en)"
        assert "FOUT  bank" in tekst and "RuntimeError: boem" in tekst
        assert "ACTIE documenten" in tekst and "12 gecontroleerd, 2 afwijking(en), 1 geaccepteerd" in tekst
        assert "omzet          niet gedraaid" in tekst

        regels = tekst.splitlines()
        hoofdregels = [r for r in regels if r.startswith("  - ")]
        # Hoofdregels = leesbaar, met administratienaam, ZONDER GUID/vingerafdruk.
        assert (
            "  - [Kempen Facilities B.V.] Bedrag afwijkt in RLZ — Kader Consultancy F212604921 — "
            "Wij boekten € 274,89, RLZ toont € 279,51." in hoofdregels
        )
        assert any("Omzet half geboekt — 01-08-2026 t/m 31-08-2026 — De verkoopfactuur" in r for r in hoofdregels)
        assert any("Achtergebleven concept in RLZ" in r and "(ref 24713188)" in r for r in hoofdregels)
        assert any("RLZ-document verdwenen — Labo Derva 2026-118" in r for r in hoofdregels)
        assert any("Controle bank viel om — Het blok bank is niet gedraaid: boem." in r for r in hoofdregels)
        assert any("Hersteld — 1 afwijking(en)" in r for r in regels)
        assert any("Bedrag afwijkt in RLZ — Oud BV — Wij boekten € 1,00, RLZ toont € 2,00." in r for r in hoofdregels)
        guid = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        for r in hoofdregels:
            assert not guid.search(r) and "[vaf:" not in r, r
        # Doe-zin per bevinding (dezelfde als in de UI) …
        assert "    → Controleer de wijziging in RLZ; klopt die, accepteer met reden." in tekst
        assert "    → Herstel via de half-geboekt-route (omzet-reconciliatie) — nooit laten staan." in tekst
        assert "klikwerk in Reeleezee" in tekst  # let-op: nooit de app
        assert "intrekken kan via de actie op deze rij" in tekst  # geaccepteerd
        # … en de vingerafdruk + ruwe CLI-regel als technische regel erónder (CLI-acceptatie blijft mogelijk).
        assert "    technisch: vaf:a2 · document=" in tekst and "[vaf:a2]: eigen=€274.89 rlz=€279.51" in tekst
        assert "    technisch: vaf:oud" in tekst
        assert "Omgevallen blok(ken): bank" in tekst
        assert "/reconciliatie" in tekst



class TestBouwMailAutomatiseringen:
    """Blok 5 (08-09, feedback Peter "wat moet ik hiermee"): het blok "Automatiseringen (laatste 24 u):" staat alleen
    nog in de mail als er iets afwijkt (≥ 1 LET-OP: harde voorwaarde in het etmaal of zeven dagen stil); anders één
    regel "Automatiseringen: alles gelopen (N aan)". CLI-uitvoer en mail-drempel ongewijzigd."""

    @staticmethod
    def _teller(sleutel: str, stand: str = "aan", **extra) -> dict:
        t = {
            "sleutel": sleutel,
            "label": sleutel.replace("_", " ").capitalize(),
            "stand": stand,
            "stand_detail": None,
            "bron": "audit",
            "dag": {"verwacht": 3, "gedaan": 3, "overgeslagen": {}},
            "week": {"verwacht": 9, "gedaan": 9, "overgeslagen": {}},
            "harde_voorwaarden": [],
            "stil": False,
        }
        t.update(extra)
        return t

    def _mail(self, tellers: list[dict]) -> str:
        _, tekst = bouw_mail(
            run_id=uuid.uuid4(),
            bron="scheduler",
            afgerond_op=datetime(2026, 9, 9, 4, 31, tzinfo=UTC),
            exit_code=0,
            samenvatting={
                "documenten": {"status": "ok", "gecontroleerd": 1, "afwijkingen": 0, "geaccepteerd": 0, "let_op": 0, "fouten": 0},
                "automatiseringen": {"venster_uren": 24, "stil_dagen": 7, "berekend_op": "2026-09-09T04:31:00+00:00", "tellers": tellers},
            },
            delta=Delta(nieuwe_afwijkingen=[_b("afwijking", uuid.uuid4(), "x1")]),
            open_afwijkingen=1,
            namen={},
        )
        return tekst

    def test_alles_gelopen_is_een_regel_zonder_blok_en_zonder_uit_regels(self) -> None:
        tekst = self._mail(
            [
                self._teller("autoboeken_inkoop"),
                self._teller("autoboeken_omzet", stand="uit"),
                self._teller("bank_autoboeken", stand="deels"),
                self._teller("terugkerend", stand="altijd"),
                self._teller("bank_sync", stand="altijd"),  # onbekende/nieuwe sleutel (blok 1) — telt gewoon mee
            ]
        )
        assert "Automatiseringen: alles gelopen (4 aan)" in tekst
        assert "Automatiseringen (laatste 24 u):" not in tekst
        assert "Autoboeken omzet" not in tekst and "uit (" not in tekst

    def test_let_op_harde_voorwaarde_geeft_het_volledige_blok(self) -> None:
        aid = str(uuid.uuid4())
        tekst = self._mail(
            [
                self._teller("autoboeken_inkoop"),
                self._teller(
                    "duplicaat_afvoer",
                    dag={"verwacht": 5, "gedaan": 4, "overgeslagen": {"volumerem": 1}},
                    harde_voorwaarden=[{"categorie": "volumerem", "aantal": 1, "administratie_id": aid, "voorbeeld": "limiet"}],
                ),
            ]
        )
        assert "Automatiseringen (laatste 24 u):" in tekst
        assert "alles gelopen" not in tekst
        assert re.search(r"Duplicaat afvoer\s+aan\s+verwacht 5, gedaan 4, overgeslagen 1 \(volumerem bereikt: 1\) — LET-OP: 1× volumerem bereikt", tekst)

    def test_zeven_dagen_stil_geeft_het_volledige_blok(self) -> None:
        tekst = self._mail(
            [
                self._teller("terugkerend", stand="altijd", dag={"verwacht": 12, "gedaan": 0, "overgeslagen": {}}, week={"verwacht": 84, "gedaan": 0, "overgeslagen": {}}, stil=True),
            ]
        )
        assert "Automatiseringen (laatste 24 u):" in tekst
        assert "LET-OP: 7 dagen stil bij 84 kandidaten" in tekst

    def test_alles_uit_is_nul_aan(self) -> None:
        tekst = self._mail([self._teller("autoboeken_omzet", stand="uit")])
        assert "Automatiseringen: alles gelopen (0 aan)" in tekst

    def test_let_op_op_een_uit_teller_geeft_toch_het_volledige_blok(self) -> None:
        """07-09-uitzondering: noodrem UIT + gesignaleerde duplicaten in het etmaal = LET-OP op een teller met stand uit —
        een signaal mét handeling verdwijnt nooit achter "alles gelopen"."""
        aid = str(uuid.uuid4())
        tekst = self._mail(
            [
                self._teller("autoboeken_inkoop"),
                self._teller(
                    "duplicaat_afvoer",
                    stand="uit",
                    stand_detail="platformbrede noodrem UIT",
                    dag={"verwacht": 1, "gedaan": 0, "overgeslagen": {"noodrem": 1}},
                    harde_voorwaarden=[{"categorie": "noodrem", "aantal": 1, "administratie_id": aid, "voorbeeld": "zelfde_referentie"}],
                ),
            ]
        )
        assert "Automatiseringen (laatste 24 u):" in tekst and "alles gelopen" not in tekst
        assert re.search(r"Duplicaat afvoer\s+uit \(platformbrede noodrem UIT\)", tekst)

    def test_cli_regels_blijven_volledig(self) -> None:
        """De CLI-uitvoer (`automatiseringen.regels`) is ongewijzigd: álle regels, ook uit — alleen de mail is compact."""
        from app.reconciliatie import automatiseringen

        tellers = automatiseringen.uit_samenvatting(
            {"tellers": [self._teller("autoboeken_inkoop"), self._teller("autoboeken_omzet", stand="uit")]}
        )
        regels = automatiseringen.regels(tellers)
        assert regels[0] == "Automatiseringen (laatste 24 u):" and len(regels) == 3
        assert any("Autoboeken omzet" in r and "uit" in r for r in regels)


# ---- voer_uit end-to-end -------------------------------------------------------------------------


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []

    def nep(*, naar: str, onderwerp: str, tekst: str, bijlagen=None) -> None:  # noqa: ANN001
        verzonden.append({"naar": naar, "onderwerp": onderwerp, "tekst": tekst})

    monkeypatch.setattr(mail, "verzend_mail", nep)
    return verzonden


def _blok(bevindingen: list[tuple[str, uuid.UUID | None, str, str]], *, exit_code: int = 0, gecontroleerd: int = 3):
    """Stub-blokfunctie in de vorm van de CLI-blokken: (args, verzamelaar=None) -> int."""

    def functie(args, verzamelaar=None) -> int:  # noqa: ANN001
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(gecontroleerd)
            for soort, aid, vaf, tekst in bevindingen:
                verzamelaar.bevinding(
                    soort=soort,
                    administratie_id=aid,
                    vingerafdruk=vaf,
                    tekst=tekst,
                    detail={"bron": "documenten", "reden": "gestorneerd"}
                    if soort == "let_op"
                    else {"bron": "documenten"},
                )
        return exit_code

    return functie


def _crash(args, verzamelaar=None) -> int:  # noqa: ANN001
    raise RuntimeError("RLZ onbereikbaar (test)")


def _laatste_run() -> ReconciliatieRun:
    with scoped_session(None) as session:
        rij = session.scalars(select(ReconciliatieRun).order_by(ReconciliatieRun.aangevraagd_op.desc()).limit(1)).one()
        session.expunge(rij)
        return rij


class TestVoerUit:
    def test_run_rij_bevindingen_en_mail_bij_nieuwe_afwijking(self, administratie_id, mails) -> None:
        uit: list[str] = []
        blokken = [("documenten", _blok([("afwijking", administratie_id, "vafA", "AFWIJKING  regel A")], exit_code=1))]
        code = run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=uit.append, stderr=uit.append)
        assert code == 1  # exit 1 blijft exit 1
        rij = _laatste_run()
        assert rij.status == "klaar" and rij.exit_code == 1 and rij.bron == "cli" and rij.afgerond_op is not None
        assert rij.samenvatting["documenten"] == {
            "status": "actie",
            "exit_code": 1,
            "gecontroleerd": 3,
            "afwijkingen": 1,
            "geaccepteerd": 0,
            "uitgesloten": 0,
            "let_op": 0,
            "fouten": 0,
            "foutmelding": None,
        }
        assert rij.mail_status == "verzonden" and rij.mail_verzonden_op is not None
        assert len(mails) == 1 and "1 afwijking(en) · 1 nieuwe aandachtspunt(en)" in mails[0]["onderwerp"]
        assert "AFWIJKING  regel A" in mails[0]["tekst"]
        bevindingen = run_service.lees_bevindingen(rij.id, administratie_ids=[administratie_id])
        assert [(b.soort, b.vingerafdruk) for b in bevindingen] == [("afwijking", "vafA")]
        # CLI-uitvoer: bestaande regels + de nieuwe RUN-slotregel
        assert "\n=== documenten-reconciliatie ===" in uit and "ACTIE     documenten-reconciliatie (exit 1)" in uit
        assert any(t.startswith(f"RUN        {rij.id} vastgelegd (1 bevinding(en); mail: verzonden") for t in uit)

    def test_ongewijzigde_let_op_set_geeft_geen_tweede_mail(self, administratie_id, mails) -> None:
        blokken = [("doorbelasting", _blok([("let_op", administratie_id, "concept1", "LET-OP     opruim-kandidaat")]))]
        assert run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None) == 0
        assert len(mails) == 1  # eerste run ooit: één keer melden
        assert run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None) == 0
        assert len(mails) == 1  # zelfde concept → géén mail
        assert _laatste_run().mail_status == "niet_nodig"

    def test_verdwenen_afwijking_geeft_herstelmelding(self, administratie_id, mails) -> None:
        met = [("documenten", _blok([("afwijking", administratie_id, "weg", "AFWIJKING  tijdelijk")], exit_code=1))]
        zonder = [("documenten", _blok([]))]
        run_service.voer_uit(blokken=met, args=ARGS, bron="cli", stdout=lambda t: None)
        assert run_service.voer_uit(blokken=zonder, args=ARGS, bron="cli", stdout=lambda t: None) == 0
        assert len(mails) == 2
        assert "0 afwijking(en) · 0 nieuwe aandachtspunt(en)" in mails[1]["onderwerp"]
        assert "Hersteld — 1 afwijking(en)" in mails[1]["tekst"] and "AFWIJKING  tijdelijk" in mails[1]["tekst"]

    def test_blokcrash_wordt_vastgelegd_en_stopt_de_rest_niet(self, administratie_id, mails) -> None:
        uit: list[str] = []
        blokken = [("bank", _crash), ("documenten", _blok([]))]
        code = run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=uit.append, stderr=uit.append)
        assert code == 1
        rij = _laatste_run()
        assert rij.status == "klaar"  # de run zelf is afgerond; het blok staat op fout
        assert (
            rij.samenvatting["bank"]["status"] == "fout"
            and "RLZ onbereikbaar" in rij.samenvatting["bank"]["foutmelding"]
        )
        assert rij.samenvatting["documenten"]["status"] == "ok"
        assert rij.fout_reden and "bank:" in rij.fout_reden
        bevindingen = run_service.lees_bevindingen(rij.id, administratie_ids=[administratie_id])
        assert [(b.blok, b.soort, b.administratie_id) for b in bevindingen] == [("bank", "fout", None)]
        assert "FOUT       bank-reconciliatie viel om: RLZ onbereikbaar (test)" in uit
        assert len(mails) == 1 and "Omgevallen blok(ken): bank" in mails[0]["tekst"]

    def test_mailfout_maakt_de_job_niet_rood_maar_is_zichtbaar_en_geauditeerd(
        self, administratie_id, monkeypatch
    ) -> None:
        def kapot(**kw) -> None:
            raise mail.MailVerzendFout("SMTP 535 auth failed (test)")

        monkeypatch.setattr(mail, "verzend_mail", kapot)
        blokken = [("documenten", _blok([("let_op", administratie_id, "c", "LET-OP     x")]))]
        code = run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        assert code == 0
        rij = _laatste_run()
        assert rij.status == "klaar" and rij.mail_status == "mislukt" and "535" in rij.mail_detail
        with scoped_session(None) as session:
            audit = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.actie == "reconciliatie_mail_mislukt", AuditEvent.record_id == rij.id
                )
            ).all()
        assert len(audit) == 1
        # bewaking pikt 'm op als storing 'reconciliatie_mail'
        from app.bewaking.service import _probe_reconciliatie_mail

        uitkomst = _probe_reconciliatie_mail()
        assert uitkomst.status == "fout" and str(rij.id) in (uitkomst.detail or "")

    def test_zonder_mailconfig_geen_storing(self, administratie_id, monkeypatch) -> None:
        def niet_geconfigureerd(**kw) -> None:
            raise mail.MailNietGeconfigureerd("geen SMTP")

        monkeypatch.setattr(mail, "verzend_mail", niet_geconfigureerd)
        blokken = [("documenten", _blok([("afwijking", administratie_id, "z", "AFWIJKING  z")], exit_code=1))]
        run_service.voer_uit(blokken=blokken, args=ARGS, bron="cli", stdout=lambda t: None)
        assert _laatste_run().mail_status == "niet_geconfigureerd"
        from app.bewaking.service import _probe_reconciliatie_mail

        assert _probe_reconciliatie_mail().status == "ok"

    def test_bron_volgt_omgeving(self, monkeypatch) -> None:
        monkeypatch.setattr(run_service.settings, "environment", "production")
        assert run_service.bepaal_bron() == "scheduler"
        monkeypatch.setattr(run_service.settings, "environment", "dev")
        assert run_service.bepaal_bron() == "cli"

    def test_nu_draaien_wachtrij_wordt_door_de_job_geclaimd(
        self, beheerder_id, administratie_id, mails, monkeypatch
    ) -> None:
        monkeypatch.setattr(run_service, "_start_voertuig", lambda: None)
        info = run_service.start_handmatig(actor_id=beheerder_id)
        assert info.status == "wachtend" and info.bron == "handmatig"
        # dubbelklik = dezelfde run
        assert run_service.start_handmatig(actor_id=beheerder_id).run_id == info.run_id
        run_service.voer_uit(blokken=[("documenten", _blok([]))], args=ARGS, bron="scheduler", stdout=lambda t: None)
        status = run_service.status_van(info.run_id)
        assert status.status == "klaar" and status.bron == "handmatig" and status.exit_code == 0
        assert run_service.laatste_run().run_id == info.run_id

    def test_voertuigfout_staat_zichtbaar_op_de_run(self, beheerder_id, monkeypatch) -> None:
        def boem() -> None:
            raise RuntimeError("job-trigger 403")

        monkeypatch.setattr(run_service, "_start_voertuig", boem)
        with pytest.raises(run_service.RunStartFout):
            run_service.start_handmatig(actor_id=beheerder_id)
        rij = _laatste_run()
        assert rij.status == "fout" and "job-trigger 403" in rij.fout_reden


class TestCliReconciliatieAlles:
    def test_cli_uitvoer_identiek_plus_run_slotregel(self, administratie_id, mails, monkeypatch, capsys) -> None:
        """De vier echte CLI-blokken via reconciliatie-alles, motoren gestubd: de bekende regels staan er
        nog letterlijk, de run is vastgelegd mét bevindingen per soort (afwijking + geaccepteerd + let-op).
        Het vijfde blok `rlz_dubbel` (blok 6, 08-09) is hier leeg gestubd — eigen dekking in test_rlz_dubbel.py."""
        from app.bank.reconciliatie import BankReconciliatieRapport
        from app.reconciliatie import rlz_dubbel

        monkeypatch.setattr(rlz_dubbel, "toets_alle", lambda **kw: rlz_dubbel.RlzDubbelResultaat())
        from app.documenten.reconciliatie import ReconciliatieAfwijking, ReconciliatieRapport
        from app.doorbelasting.reconciliatie import (
            DoorbelastingReconciliatieResultaat,
            OpruimKandidaat,
            OpruimlijstResultaat,
        )
        from app.omzet.reconciliatie import OmzetReconciliatieResultaat
        from app.reconciliatie.service import AcceptatieInfo, Beoordeeld

        doc_id = uuid.uuid4()
        rapport = ReconciliatieRapport(
            administratie_id=administratie_id,
            aantal_gecontroleerd=2,
            afwijkingen=(
                ReconciliatieAfwijking(
                    document_id=doc_id, rlz_document_id=uuid.uuid4(), soort="ontbreekt_in_rlz", detail="404"
                ),
                ReconciliatieAfwijking(
                    document_id=uuid.uuid4(), rlz_document_id=uuid.uuid4(), soort="bedrag_wijkt_af", detail="100 vs 90"
                ),
            ),
        )
        monkeypatch.setattr(cli.reconciliatie, "reconcilieer_alle_administraties", lambda: {administratie_id: rapport})
        monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
        monkeypatch.setattr(
            cli.bank_reconciliatie,
            "reconcilieer_bank_alle_administraties",
            lambda: {
                administratie_id: BankReconciliatieRapport(
                    administratie_id=administratie_id,
                    boekingen_gecontroleerd=1,
                    afletteringen_gecontroleerd=0,
                    afwijkingen=(),
                )
            },
        )
        monkeypatch.setattr(
            cli.omzet_reconciliatie,
            "reconcilieer_alle_omzet",
            lambda: OmzetReconciliatieResultaat(afwijkingen=[], fouten={}),
        )
        monkeypatch.setattr(
            cli.doorbelasting_reconciliatie,
            "reconcilieer_alle_doorbelasting",
            lambda: DoorbelastingReconciliatieResultaat(afwijkingen=[], fouten={}),
        )
        concept = uuid.uuid4()
        monkeypatch.setattr(
            cli.doorbelasting_reconciliatie,
            "verzamel_alle_opruimlijsten",
            lambda: OpruimlijstResultaat(
                kandidaten=[
                    OpruimKandidaat(
                        administratie_id=administratie_id,
                        concept_administratie_id=administratie_id,
                        kant="verkoop_bron",
                        rlz_id=concept,
                        document_id=doc_id,
                        referentie="24713188, 24713193",
                        reden="gestorneerd",
                        detail="gestorneerd (test)",
                    )
                ],
                fouten=[],
            ),
        )
        acc = AcceptatieInfo(
            id=uuid.uuid4(),
            reden="bekend, beoordeeld",
            geaccepteerd_door=uuid.uuid4(),
            geaccepteerd_op=datetime(2026, 9, 1, tzinfo=UTC),
        )
        monkeypatch.setattr(
            cli.acceptatie_service,
            "beoordeel",
            lambda **kw: [
                Beoordeeld(
                    record_id=r,
                    soort=s,
                    detail=d,
                    vingerafdruk=f"vaf-{s}",
                    acceptatie=acc if s == "bedrag_wijkt_af" else None,
                )
                for r, s, d in kw["afwijkingen"]
            ],
        )
        monkeypatch.setattr(cli.acceptatie_service, "uitgesloten_administraties", lambda: {})

        exit_code = cli.main(["reconciliatie-alles"])

        out = capsys.readouterr().out
        assert exit_code == 1
        assert f"AFWIJKING  {administratie_id}: 2 gecontroleerd, 1 afwijking(en), 1 geaccepteerd" in out
        assert f"    - document={doc_id}" in out and "GEACCEPTEERD document=" in out
        assert (
            f"LET-OP     opruim-kandidaat [gestorneerd] verkoop_bron {concept} in administratie {administratie_id} (document {doc_id}, ref 24713188, 24713193)"
            in out
        )
        assert (
            "=== samenvatting ===" in out
            and "ACTIE     documenten-reconciliatie (exit 1)" in out
            and "OK        bank-reconciliatie (exit 0)" in out
        )
        assert "RUN        " in out and "vastgelegd (3 bevinding(en); mail: verzonden)" in out
        rij = _laatste_run()
        soorten = sorted(b.soort for b in run_service.lees_bevindingen(rij.id, administratie_ids=[administratie_id]))
        assert soorten == ["afwijking", "geaccepteerd", "let_op"]
        assert rij.samenvatting["documenten"]["gecontroleerd"] == 2 and rij.samenvatting["bank"]["gecontroleerd"] == 1
        assert rij.samenvatting["doorbelasting"]["let_op"] == 1
        assert len(mails) == 1 and "1 afwijking(en) · 3 nieuwe aandachtspunt(en)" in mails[0]["onderwerp"]
        # leesbare hoofdregel mét administratienaam (blok A8); de CLI-regel staat als technische regel eronder
        with scoped_session(None) as session:
            naam = session.execute(
                text("SELECT naam FROM platform.administratie WHERE id = :id"), {"id": administratie_id}
            ).scalar_one()
        assert f"  - [{naam}] Achtergebleven concept in RLZ — {naam}" in mails[0]["tekst"]
        assert f"[{naam}] LET-OP" not in mails[0]["tekst"]
        assert "    technisch: vaf:" in mails[0]["tekst"]
        assert "LET-OP     opruim-kandidaat [gestorneerd]" in mails[0]["tekst"]
