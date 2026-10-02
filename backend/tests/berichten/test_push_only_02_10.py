"""Run A 02-10 punt 14 — accordeur-meldingen PUSH-ONLY (besluit Peter 02-10 "zet die mail uit over hoeveel facturen
er klaar staan, wordt je echt gek van. Geen mails meer").

Guards op het afwezig-pad voor BEIDE automatische paden (nieuwe-facturen-bundel ~10 min + 09:00-herinnering):
geen push-inschrijving → géén e-mail, teller `overgeslagen_geen_push`, run-audit `accordeur_melding_run`;
push mislukt → géén e-mail; push ok → teller 0; de HANDMATIGE herinnering per document (kantoorknop) blijft
push-anders-mail; reconciliatie-dagteller "Accordeur-meldingen" leest het run-audit; CLI-regels tonen de teller."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, text

from app.accordering import herinnering as handmatig
from app.berichten import herinneringen, mail, nieuwe_facturen, push
from app.berichten import service as berichten_service
from app.berichten.models import PushSubscriptie
from app.reconciliatie import automatiseringen as auto
from tests.berichten.conftest import maak_apparaat

VANDAAG = date(2026, 10, 2)
DAG = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)  # 14:00 NL — buiten de stille uren


@pytest.fixture
def mail_log(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))
    return verzonden


@pytest.fixture
def push_log(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []
    monkeypatch.setattr(push, "is_geconfigureerd", lambda soort="webpush": True)

    def _fake(subscriptie: PushSubscriptie, *, payload: dict) -> None:
        verzonden.append({"endpoint": subscriptie.endpoint, "payload": payload})

    monkeypatch.setattr(push, "verzend_push", _fake)
    return verzonden


def _met_push(admin_engine: Engine, gebruiker_id: uuid.UUID) -> None:
    apparaat = maak_apparaat(admin_engine, gebruiker_id)
    berichten_service.registreer_subscriptie(
        gebruiker_id=gebruiker_id, apparaat_id=apparaat, endpoint=f"https://push.example/{apparaat}", p256dh="p",
        auth="a",
    )


def _run_audits(admin_engine: Engine, soort: str) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'accordeur_melding_run' "
                "AND nieuwe_waarde ->> 'soort' = :soort ORDER BY tijdstip"
            ),
            {"soort": soort},
        ).all()
    return [r[0] for r in rijen]


class TestAfwezigPadGeenPush:
    """Geen push-inschrijving: beide jobs slaan over mét teller — nooit e-mail."""

    def test_nieuwe_facturen_zonder_push_geen_mail(
        self, ter_accordering_bij_1: uuid.UUID, mail_log: list[dict], push_log: list[dict], admin_engine: Engine
    ) -> None:
        rapport = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)
        assert rapport.overgeslagen_geen_push == 1 and rapport.verzonden_push == 0 and not rapport.is_fout
        assert mail_log == [] and push_log == []
        assert not hasattr(rapport, "verzonden_mail")  # het mailkanaal bestaat in dit rapport niet meer
        audits = _run_audits(admin_engine, "nieuwe_facturen")
        assert audits and audits[-1]["overgeslagen_geen_push"] == 1 and audits[-1]["verzonden_push"] == 0

    def test_dag_herinnering_zonder_push_geen_mail(
        self,
        ter_accordering_bij_1: uuid.UUID,
        accordeur_1: uuid.UUID,
        mail_log: list[dict],
        push_log: list[dict],
        admin_engine: Engine,
    ) -> None:
        rapport = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert rapport.overgeslagen_geen_push == 1 and rapport.verzonden_push == 0 and not rapport.is_fout
        assert mail_log == [] and push_log == []
        assert not hasattr(rapport, "verzonden_mail")
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT status, kanaal, detail FROM platform.accordeur_herinnering "
                    "WHERE gebruiker_id = :g AND datum = :d"
                ),
                {"g": accordeur_1, "d": VANDAAG},
            ).one()
        assert rij.status == "overgeslagen" and rij.kanaal is None and rij.detail["reden"] == "geen_push"
        audits = _run_audits(admin_engine, "dag_herinnering")
        assert audits and audits[-1]["overgeslagen_geen_push"] == 1 and audits[-1]["datum"] == VANDAAG.isoformat()

    def test_push_fout_geen_mail(
        self,
        ter_accordering_bij_1: uuid.UUID,
        accordeur_1: uuid.UUID,
        mail_log: list[dict],
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _met_push(admin_engine, accordeur_1)
        monkeypatch.setattr(push, "is_geconfigureerd", lambda soort="webpush": True)

        def _faal(subscriptie: PushSubscriptie, *, payload: dict) -> None:
            raise push.PushFout("503 pushdienst")

        monkeypatch.setattr(push, "verzend_push", _faal)
        r1 = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)
        r2 = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert r1.overgeslagen_geen_push == 1 and r2.overgeslagen_geen_push == 1
        assert r1.mislukt == 0 and r2.mislukt == 0 and mail_log == []
        with admin_engine.connect() as conn:
            detail = conn.execute(
                text("SELECT detail FROM platform.accordeur_nieuw_gemeld WHERE document_id = :d"),
                {"d": ter_accordering_bij_1},
            ).scalar_one()
        assert detail["reden"] == "geen_push" and "503" in detail["push_fouten"][0]

    def test_push_ok_teller_nul(
        self,
        ter_accordering_bij_1: uuid.UUID,
        accordeur_1: uuid.UUID,
        mail_log: list[dict],
        push_log: list[dict],
        admin_engine: Engine,
    ) -> None:
        _met_push(admin_engine, accordeur_1)
        r1 = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)
        r2 = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert (r1.verzonden_push, r1.overgeslagen_geen_push) == (1, 0)
        assert (r2.verzonden_push, r2.overgeslagen_geen_push) == (1, 0)
        assert len(push_log) == 2 and mail_log == []
        assert _run_audits(admin_engine, "nieuwe_facturen")[-1]["verzonden_push"] == 1
        assert _run_audits(admin_engine, "dag_herinnering")[-1]["verzonden_push"] == 1


class TestHandmatigBlijftPushAndersMail:
    def test_kantoorknop_zonder_push_stuurt_mail(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        ter_accordering_bij_1: uuid.UUID,
        mail_log: list[dict],
        push_log: list[dict],
    ) -> None:
        """Bewuste mensactie: de handmatige herinnering per document houdt push-anders-mail (opdracht 02-10)."""
        resultaat = handmatig.stuur_handmatige_herinnering(
            administratie_id=administratie_id,
            document_id=ter_accordering_bij_1,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        assert resultaat.kanaal == "e-mail" and len(mail_log) == 1 and push_log == []
        assert f"/accordeur?document={ter_accordering_bij_1}" in mail_log[0]["tekst"]


class TestReconciliatieTeller:
    def test_teller_leest_run_audits(self) -> None:
        nu = datetime(2026, 10, 2, 18, 0, tzinfo=UTC)
        feiten = auto.Feiten(administraties={uuid.uuid4(): "X"})
        feiten.audit = [
            auto.AuditFeit(
                "accordeur_melding_run",
                datetime(2026, 10, 2, 7, 0, tzinfo=UTC),
                None,
                {"soort": "dag_herinnering", "verzonden_push": 3, "overgeslagen_geen_push": 2, "mislukt": 0},
            ),
            auto.AuditFeit(
                "accordeur_melding_run",
                datetime(2026, 10, 2, 10, 0, tzinfo=UTC),
                None,
                {"soort": "nieuwe_facturen", "verzonden_push": 1, "overgeslagen_geen_push": 1, "mislukt": 1},
            ),
        ]
        tellers = auto.bereken(feiten, nu=nu)
        t = next(t for t in tellers if t.sleutel == auto.ACCORDEUR_MELDINGEN)
        assert (t.dag.verwacht, t.dag.gedaan) == (8, 4)
        assert t.dag.overgeslagen[auto.GEEN_PUSH] == 3 and t.dag.overgeslagen[auto.FOUT] == 1
        assert t.harde_voorwaarden == []  # geen push = de bedoeling (geen mail), geen LET-OP
        assert t.detail["geen_push_per_soort"] == {"dag_herinnering": 2, "nieuwe_facturen": 1}
        assert auto.ACCORDEUR_MELDINGEN in auto.VOLGORDE and auto.ACCORDEUR_MELDINGEN in auto.LABEL
        assert auto.VASTE_CATEGORIEEN[auto.ACCORDEUR_MELDINGEN] == (auto.GEEN_PUSH,)
        regel = next(r for r in auto.regels(tellers) if "Accordeur-meldingen" in r)
        assert "verwacht 8, gedaan 4, overgeslagen 4" in regel and "geen push-inschrijving" in regel

    def test_teller_zonder_runs_is_nul_en_zichtbaar(self) -> None:
        tellers = auto.bereken(auto.Feiten(administraties={}), nu=datetime(2026, 10, 2, 18, 0, tzinfo=UTC))
        t = next(t for t in tellers if t.sleutel == auto.ACCORDEUR_MELDINGEN)
        assert t.dag.verwacht == 0 and t.stand == "altijd"
        assert any("Accordeur-meldingen" in r for r in auto.regels(tellers))


class TestCli:
    def test_cli_regels_tonen_de_teller(
        self, ter_accordering_bij_1: uuid.UUID, mail_log: list[dict], monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        from app import cli

        monkeypatch.setattr(nieuwe_facturen, "in_stille_uren", lambda moment=None: False)
        assert cli.main(["nieuwe-facturen-melden"]) == 0
        assert cli.main(["accordeur-herinneringen"]) == 0
        uit = capsys.readouterr().out
        assert "push-only, besluit 02-10" in uit
        assert "1 overgeslagen_geen_push" in uit
        assert "e-mail," not in uit.split("Nieuwe-facturen-meldingen")[1].split("\n")[0]
        assert mail_log == []
