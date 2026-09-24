# ruff: noqa: F811 — pytest-fixtures als parameters
"""Data-stap `doorbelasting-bedragen-gelijktrekken` (opdracht 24-09, stap 3): alleen ONZE database, nooit een write in RLZ.
Legacy-rij (per-regel-afronding, 1 ct hoger dan RLZ) → dry-run telt en schrijft niets; --uitvoeren zet btw_bedrag op de
RLZ-waarde mét audit + tijdlijn (+ boekstand-event in een vastgoed-doel); tweede run = gelijk; > € 0,05 = AFWIJKING,
ongewijzigd; élke CLI-argumentvorm uit het meetrecept letterlijk."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select

from app import cli
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.documenten.models import DocumentGebeurtenis, WebhookUitgaand
from app.doorbelasting import bedragen_gelijktrekken as bg
from app.doorbelasting.models import DoorbelastingBoeking
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.doorbelasting.conftest import (  # noqa: F401
    DoorbelastingOpzet,
    FakeDoorbelastingClient,
    haal_boekingen,
    onboarded_opzet,
)
from tests.doorbelasting.test_boeken import _boek
from tests.doorbelasting.test_webhook_spiegel import _zet_vastgoed

D = Decimal


def _legacy_boeking(opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, *, plus_ct: str = "0.01") -> tuple[DoorbelastingBoeking, FakeDoorbelastingClient, FakeDoorbelastingClient]:
    """Boek (RLZ-vorm, fake speelt RLZ na) en zet daarna de registratie op de OUDE per-regel-som (RLZ + 1 ct) —
    exact de productiesituatie van de 55 legacy-rijen (Lusso: module 1.045,52, RLZ 1.045,51)."""
    bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
    _boek(opzet, beheerder_id, bron=bron, doel=doel)
    boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
    with scoped_session(opzet.administratie_id, actor_id=beheerder_id) as session:
        rij = session.get(DoorbelastingBoeking, boeking.id)
        rij.btw_bedrag = rij.btw_bedrag + D(plus_ct)
    return haal_boekingen(opzet.administratie_id, opzet.run.id)[0], bron, doel


def _factory(bron: FakeDoorbelastingClient, doel: FakeDoorbelastingClient, opzet: DoorbelastingOpzet):  # noqa: ANN202
    def f(aid: uuid.UUID):  # noqa: ANN202
        return bron if aid == opzet.administratie_id else doel

    return f


class TestDataStap:
    def test_dry_run_telt_en_schrijft_niets(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID) -> None:
        boeking, bron, doel = _legacy_boeking(onboarded_opzet, beheerder_id)
        puts = (len(bron.sales_invoices), len(doel.purchase_invoices))
        r = bg.verwerk(administratie=None, uitvoeren=False, actor_id=beheerder_id, client_factory=_factory(bron, doel, onboarded_opzet))
        assert r is not None and r.dry_run and [x.uitkomst for x in r.rijen] == [bg.UITKOMST_ZOU]
        rij = r.rijen[0]
        assert rij.verschil_ct == -1 and rij.nieuw_btw == "22.05" and rij.ons_btw == "22.06"
        assert rij.rlz_verkoop_incl == "127.05" and rij.rlz_spiegel_incl == "127.05"
        assert r.telling()[bg.UITKOMST_ZOU] == 1 and r.telling()["webhook_events"] == 0
        with scoped_session(onboarded_opzet.administratie_id) as session:
            assert session.get(DoorbelastingBoeking, boeking.id).btw_bedrag == D("22.06")  # niets geschreven
            assert session.scalar(select(AuditEvent).where(AuditEvent.actie == bg.AUDIT_GELIJKGETROKKEN)) is None
        assert (len(bron.sales_invoices), len(doel.purchase_invoices)) == puts  # alleen GET

    def test_uitvoeren_zet_de_rlz_waarde_met_audit_en_tijdlijn_en_is_daarna_gelijk(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        boeking, bron, doel = _legacy_boeking(onboarded_opzet, beheerder_id)
        factory = _factory(bron, doel, onboarded_opzet)
        r = bg.verwerk(administratie=str(onboarded_opzet.administratie_id), uitvoeren=True, actor_id=beheerder_id, client_factory=factory)
        assert r is not None and not r.dry_run and [x.uitkomst for x in r.rijen] == [bg.UITKOMST_GELIJKGETROKKEN]
        assert r.rijen[0].webhook_event is False  # doel is geen vastgoed-administratie → alleen audit
        with scoped_session(onboarded_opzet.administratie_id) as session:
            na = session.get(DoorbelastingBoeking, boeking.id)
            assert na.btw_bedrag == D("22.05") and na.netto_totaal == D("100.00") and na.provisie_bedrag == D("5.00")
            audit = session.scalars(select(AuditEvent).where(AuditEvent.actie == bg.AUDIT_GELIJKGETROKKEN)).all()
            assert len(audit) == 1 and audit[0].record_id == boeking.id
            assert audit[0].oude_waarde["btw_bedrag"] == "22.06" and audit[0].nieuwe_waarde["btw_bedrag"] == "22.05"
            assert audit[0].nieuwe_waarde["verkoop_rlz_id"] == str(boeking.verkoop_rlz_id)
            assert audit[0].nieuwe_waarde["spiegel_rlz_id"] == str(boeking.spiegel_rlz_id)
            tijdlijn = [
                g.detail
                for g in session.scalars(select(DocumentGebeurtenis).where(DocumentGebeurtenis.document_id == boeking.document_id))
                if (g.detail or {}).get("gebeurtenis") == bg.TIJDLIJN_GEBEURTENIS
            ]
            assert len(tijdlijn) == 1 and tijdlijn[0]["btw_oud"] == "22.06" and tijdlijn[0]["btw_nieuw"] == "22.05"
            assert "spiegel" in tijdlijn[0]["kanten"] and "verkoop" in tijdlijn[0]["kanten"]
            assert session.scalars(select(WebhookUitgaand).where(WebhookUitgaand.document_id == boeking.document_id)).all() == []
        # RLZ ongewijzigd: geen PUT, geen actie.
        assert bron.verkoop_correcties == [] and doel.spiegel_correcties == []
        # Tweede run: gelijk, geen tweede audit.
        r2 = bg.verwerk(administratie=None, uitvoeren=True, actor_id=beheerder_id, client_factory=factory)
        assert [x.uitkomst for x in r2.rijen] == [bg.UITKOMST_GELIJK]
        with scoped_session(onboarded_opzet.administratie_id) as session:
            assert len(session.scalars(select(AuditEvent).where(AuditEvent.actie == bg.AUDIT_GELIJKGETROKKEN)).all()) == 1

    def test_vastgoed_doel_krijgt_een_boekstand_event_met_gecorrigeerde_regels(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        assert onboarded_opzet.doel_administratie_id is not None
        _zet_vastgoed(admin_engine, onboarded_opzet.doel_administratie_id)
        boeking, bron, doel = _legacy_boeking(onboarded_opzet, beheerder_id)
        with scoped_session(onboarded_opzet.administratie_id) as session:
            voor = session.scalars(select(WebhookUitgaand).where(WebhookUitgaand.document_id == boeking.document_id)).all()
            assert len(voor) == 1 and voor[0].payload["data"]["volgnummer"] == 1
            # Simuleer de legacy-payload: regels mét de oude per-regel-btw (21,00 + 1,06 = 22,06).
            payload = dict(voor[0].payload)
            regels = [dict(r) for r in payload["data"]["regels"]]
            regels[-1]["btw_bedrag"] = "1.06"
            payload["data"] = {**payload["data"], "regels": regels}
            voor[0].payload = payload
        r = bg.verwerk(administratie=None, uitvoeren=True, actor_id=beheerder_id, client_factory=_factory(bron, doel, onboarded_opzet))
        assert [x.uitkomst for x in r.rijen] == [bg.UITKOMST_GELIJKGETROKKEN] and r.rijen[0].webhook_event is True
        with scoped_session(onboarded_opzet.administratie_id) as session:
            rijen = session.scalars(
                select(WebhookUitgaand).where(WebhookUitgaand.document_id == boeking.document_id).order_by(WebhookUitgaand.aangemaakt_op)
            ).all()
            assert len(rijen) == 2
            nieuw = rijen[-1]
            assert nieuw.event == "factuur_geboekt" and nieuw.administratie_id == onboarded_opzet.doel_administratie_id
            assert nieuw.payload["data"]["volgnummer"] == 2 and nieuw.payload["data"]["rlz_document_id"] == str(boeking.spiegel_rlz_id)
            assert [x["btw_bedrag"] for x in nieuw.payload["data"]["regels"]] == ["21.00", "1.05"]
            assert sum(D(x["btw_bedrag"]) for x in nieuw.payload["data"]["regels"]) == D("22.05")

    def test_groot_verschil_of_verkoop_ongelijk_spiegel_is_afwijking_en_blijft_ongewijzigd(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        boeking, bron, doel = _legacy_boeking(onboarded_opzet, beheerder_id, plus_ct="0.50")
        factory = _factory(bron, doel, onboarded_opzet)
        r = bg.verwerk(administratie=None, uitvoeren=True, actor_id=beheerder_id, client_factory=factory)
        assert [x.uitkomst for x in r.rijen] == [bg.UITKOMST_AFWIJKING]
        with scoped_session(onboarded_opzet.administratie_id) as session:
            assert session.get(DoorbelastingBoeking, boeking.id).btw_bedrag == D("22.55")  # niet aangepast
        # verkoop ≠ spiegel in RLZ (iemand wijzigde de spiegel in de RLZ-UI): ook afwijking, ook bij 1 ct.
        with scoped_session(onboarded_opzet.administratie_id, actor_id=beheerder_id) as session:
            session.get(DoorbelastingBoeking, boeking.id).btw_bedrag = D("22.06")
        doel.purchase_invoices[str(boeking.spiegel_rlz_id)]["TotalPayableAmount"] = 127.06
        r2 = bg.verwerk(administratie=None, uitvoeren=True, actor_id=beheerder_id, client_factory=factory)
        assert [x.uitkomst for x in r2.rijen] == [bg.UITKOMST_AFWIJKING] and "verkoop en spiegel verschillen" in r2.rijen[0].detail
        with scoped_session(onboarded_opzet.administratie_id) as session:
            assert session.get(DoorbelastingBoeking, boeking.id).btw_bedrag == D("22.06")

    def test_onleesbaar_record_is_zichtbaar_niet_leesbaar(self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID) -> None:
        boeking, bron, doel = _legacy_boeking(onboarded_opzet, beheerder_id)
        del bron.sales_invoices[str(boeking.verkoop_rlz_id)]  # 404 in RLZ
        r = bg.verwerk(administratie=None, uitvoeren=True, actor_id=beheerder_id, client_factory=_factory(bron, doel, onboarded_opzet))
        assert [x.uitkomst for x in r.rijen] == [bg.UITKOMST_NIET_LEESBAAR] and "404" in (r.rijen[0].fout or "")
        with scoped_session(onboarded_opzet.administratie_id) as session:
            assert session.get(DoorbelastingBoeking, boeking.id).btw_bedrag == D("22.06")

    @pytest.mark.parametrize(
        "argv",
        [
            ["doorbelasting-bedragen-gelijktrekken"],
            ["doorbelasting-bedragen-gelijktrekken", "--dry-run"],
            ["doorbelasting-bedragen-gelijktrekken", "--dry-run", "--json-uit"],
            ["doorbelasting-bedragen-gelijktrekken", "--administratie", "{adm}", "--dry-run"],
            ["doorbelasting-bedragen-gelijktrekken", "--administratie", "{adm}", "--uitvoeren", "--beheerder-id", "{beheerder}"],
        ],
    )
    def test_elke_cli_argumentvorm_uit_het_meetrecept(
        self,
        onboarded_opzet: DoorbelastingOpzet,
        beheerder_id: uuid.UUID,
        argv: list[str],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Regel 19-09 poging 2: élke argumentvorm uit het meetrecept letterlijk via `cli.main` (argparse + dispatcher)."""
        _boeking, bron, doel = _legacy_boeking(onboarded_opzet, beheerder_id)
        monkeypatch.setattr(bg, "_standaard_client", _factory(bron, doel, onboarded_opzet))
        argv = [a.replace("{adm}", str(onboarded_opzet.administratie_id)).replace("{beheerder}", str(beheerder_id)) for a in argv]
        assert cli.main(argv) == 0
        tekst = capsys.readouterr().out
        if "--json-uit" in argv:
            assert '"telling"' in tekst
        else:
            assert "TOTAAL: 1 doorbelasting(en)" in tekst
            assert ("GELIJKGETROKKEN" in tekst) == ("--uitvoeren" in argv)
            assert ("DRY-RUN" in tekst) == ("--uitvoeren" not in argv)

    def test_cli_main_kent_het_commando_en_onbekende_administratie_is_exit_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["doorbelasting-bedragen-gelijktrekken", "--administratie", "administratie-die-niet-bestaat-zzz", "--dry-run"]) == 2
        assert "onbekend of niet eenduidig" in capsys.readouterr().err


class TestWebhookPayload:
    def test_gecorrigeerde_payload_rlz_vorm_en_volgnummer(self) -> None:
        vorige = {
            "schema_version": "1.2",
            "event": "factuur_geboekt",
            "data": {
                "rlz_document_id": "x",
                "volgnummer": 1,
                "regels": [
                    {"ledger_id": "a", "netto_bedrag": "4741.55", "btw_bedrag": "995.73"},
                    {"ledger_id": "b", "netto_bedrag": "237.08", "btw_bedrag": "49.79"},
                ],
            },
        }
        nieuw = bg._gecorrigeerde_webhook_payload(vorige, nieuw_volgnummer=2, btw_pct=D("21.00"))
        assert nieuw is not None and nieuw["data"]["volgnummer"] == 2
        assert [r["btw_bedrag"] for r in nieuw["data"]["regels"]] == ["995.72", "49.79"]
        assert vorige["data"]["regels"][0]["btw_bedrag"] == "995.73"  # bron ongewijzigd (deepcopy)

    def test_al_in_rlz_vorm_of_bruto_zonder_btw_geeft_geen_event(self) -> None:
        al_goed = {"event": "factuur_geboekt", "data": {"volgnummer": 1, "regels": [{"netto_bedrag": "4741.55", "btw_bedrag": "995.72"}, {"netto_bedrag": "237.08", "btw_bedrag": "49.79"}]}}
        assert bg._gecorrigeerde_webhook_payload(al_goed, nieuw_volgnummer=2, btw_pct=D("21.00")) is None
        bruto = {"event": "factuur_geboekt", "data": {"volgnummer": 1, "regels": [{"netto_bedrag": "121.00", "btw_bedrag": "0.00"}]}}
        assert bg._gecorrigeerde_webhook_payload(bruto, nieuw_volgnummer=2, btw_pct=D("21.00")) is None
