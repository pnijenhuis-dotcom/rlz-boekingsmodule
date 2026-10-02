"""Run A 02-10 punt 17 (Peter 02-10): een 409 `niet_koppelbaar` van Vastly ("nog niet koppelbaar", koppelcontract §3c)
is géén dead-letter ná 8 pogingen maar status `wacht_op_ontvanger` mét oplopende cadans vanaf de eerste 409 (1 u → 6 u
→ 24 u → dagelijks), max 14 dagen, daarna pas `mislukt` mét de reden uit de body; zichtbaar in het reconciliatieblok
`webhooks` mét handeling "Nu opnieuw" (route + motor). 2xx ná het wachten = afgeleverd.

02-10 avond (besluit Peter "Ik volg jouw advies", besluiten run A punt 17a): élke ANDERE niet-2xx (5xx, 429, timeout,
02-10 avond (besluit Peter "Ik volg jouw advies", besluiten run A punt 17a): élke ANDERE niet-2xx (5xx, 429, timeout,
nonce- replay-409) volgt dezelfde cadans als storing, hooguit 7 dagen (`STORING_MAX`), daarna `mislukt` mét de laatste
fout als reden + bevinding `webhook_aflevering_mislukt` direct in `actie`; een 4xx ≠ 409/429 is direct `mislukt`
(payloadfout). 409-pogingen tellen niet mee voor de storingsgrens. Zie `TestStoringscadans7Dagen` onderaan en
`test_webhook_afleveraar.py::TestRetryEnDeadLetter`."""

# ruff: noqa: F811 — de fixtures uit test_webhook_afleveraar worden geïmporteerd én als testparameter gebruikt.
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import cli
from app.documenten import webhook_afleveraar, webhook_reconciliatie
from app.documenten.models import WebhookStatus
from app.documenten.storage import LokaleBestandsopslag
from app.documenten.webhook_afleveraar import (
    STORING_CADANS,
    STORING_MAX,
    WACHT_MAX,
    NuOpnieuwNietMogelijk,
    herzend_afgeleverd,
    nu_opnieuw,
    storing_cumulatief,
    storing_verlopen,
    verwerk_openstaande_webhooks,
    volgende_wacht_poging,
)
from app.main import app
from app.reconciliatie import soort_stand, teksten
from app.reconciliatie.run import Verzamelaar
from app.security.tokens import create_access_token
from tests.documenten.test_webhook_afleveraar import (  # noqa: F401
    MockOntvanger,
    _audit_acties,
    _maak_outbox_rij,
    aflevering_aan,
    vastgoed_administratie,
)

client = TestClient(app)
UUR = timedelta(hours=1)


class NietKoppelbaarOntvanger(MockOntvanger):
    """Vastly's §3c-gedrag: zolang `koppelbaar` False is antwoordt élk bericht 409 `niet_koppelbaar` mét reden;
    daarna 200 `verwerkt`."""

    def __init__(self, *, reden: str = "onbekende_administratie", forceer_status: list[int] | None = None) -> None:
        super().__init__(forceer_status=forceer_status)
        self.koppelbaar = False
        self.reden = reden

    def verwerk(self, envelope: dict) -> httpx.Response:
        if not self.koppelbaar:
            self.aantal_409 = getattr(self, "aantal_409", 0) + 1
            return httpx.Response(409, json={"resultaat": "niet_koppelbaar", "reden": self.reden})
        antwoord = super().verwerk(envelope)
        if antwoord.status_code == 200:
            return httpx.Response(200, json={"resultaat": "verwerkt"})
        return antwoord


def _headers(admin_engine: Engine, gid: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gid, rol='boekhouding')}"}


def _wacht_rij(admin_engine: Engine, rij_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT status, pogingen, wacht_pogingen, wacht_op_ontvanger_sinds, volgende_poging_op, "
                    "laatste_fout "
                    "FROM boekhouding.webhook_uitgaand WHERE id = :id"
                ),
                {"id": rij_id},
            )
            .mappings()
            .one()
        )


class TestCadans:
    def test_volgende_poging_1u_7u_31u_daarna_dagelijks_en_altijd_na_nu(self) -> None:
        sinds = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        assert volgende_wacht_poging(sinds=sinds, nu=sinds) == sinds + 1 * UUR
        assert volgende_wacht_poging(sinds=sinds, nu=sinds + 1 * UUR) == sinds + 7 * UUR
        assert volgende_wacht_poging(sinds=sinds, nu=sinds + 7 * UUR) == sinds + 31 * UUR
        assert volgende_wacht_poging(sinds=sinds, nu=sinds + 31 * UUR) == sinds + 55 * UUR
        # Een late job-run (poging 2 pas ná 9 u) slaat de gemiste stap over en landt op de eerstvolgende ná nu.
        assert volgende_wacht_poging(sinds=sinds, nu=sinds + 9 * UUR) == sinds + 31 * UUR
        assert volgende_wacht_poging(sinds=sinds, nu=sinds + 100 * UUR) == sinds + 103 * UUR


class TestAfleveraar409:
    def test_409_niet_koppelbaar_wordt_wacht_op_ontvanger_met_cadans_en_nooit_dead_letter(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = NietKoppelbaarOntvanger()
        t0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

        rapport = verwerk_openstaande_webhooks(nu=t0, transport=ontvanger.transport)
        assert rapport.wacht_op_ontvanger == 1 and rapport.storing_verlopen == 0 and rapport.poging_mislukt == 0
        rij = _wacht_rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.WACHT_OP_ONTVANGER.value
        assert rij["wacht_pogingen"] == 1 and rij["pogingen"] == 1
        assert rij["wacht_op_ontvanger_sinds"] == t0
        assert rij["volgende_poging_op"] == t0 + 1 * UUR
        assert "onbekende_administratie" in rij["laatste_fout"]
        assert _audit_acties(admin_engine, rij_id) == ["webhook_wacht_op_ontvanger"]

        # Vóór het cadansmoment: niets. Op 1 u: tweede 409 → volgende 7 u ná de eerste; 7 u → 31 u; 31 u → 55 u.
        verwerk_openstaande_webhooks(nu=t0 + timedelta(minutes=30), transport=ontvanger.transport)
        assert ontvanger.aantal_409 == 1
        for nu, verwacht in ((1 * UUR, 7 * UUR), (7 * UUR, 31 * UUR), (31 * UUR, 55 * UUR), (55 * UUR, 79 * UUR)):
            verwerk_openstaande_webhooks(nu=t0 + nu, transport=ontvanger.transport)
            rij = _wacht_rij(admin_engine, rij_id)
            assert rij["status"] == WebhookStatus.WACHT_OP_ONTVANGER.value, nu
            assert rij["volgende_poging_op"] == t0 + verwacht, nu
        assert rij["wacht_pogingen"] == 5 and ontvanger.aantal_409 == 5
        # vijf 409's en max_pogingen 2 — tóch geen dead-letter: 409-pogingen tellen daar niet in mee.
        assert rij["pogingen"] == 5

    def test_2xx_na_wachten_is_afgeleverd(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = NietKoppelbaarOntvanger(reden="onbekend_document")
        t0 = datetime.now(UTC) - timedelta(minutes=61)  # de tweede poging (t0 + 1 u) valt op "nu" (replay-venster)
        verwerk_openstaande_webhooks(nu=t0, transport=ontvanger.transport)
        ontvanger.koppelbaar = True  # Vastly herstelt de koppeling
        rapport = verwerk_openstaande_webhooks(nu=datetime.now(UTC), transport=ontvanger.transport)
        assert rapport.afgeleverd == 1
        rij = _wacht_rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.AFGELEVERD.value and rij["volgende_poging_op"] is None
        assert _audit_acties(admin_engine, rij_id) == ["webhook_wacht_op_ontvanger", "webhook_afgeleverd"]
        assert "ná 1 × wachten" in rapport.per_rij[rij_id]

    def test_na_14_dagen_mislukt_met_reden_en_wordt_niet_meer_geprobeerd(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = NietKoppelbaarOntvanger(reden="referentie_conflict")
        t0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        verwerk_openstaande_webhooks(nu=t0, transport=ontvanger.transport)
        # Dag 13: nog wachten. Dag 14: verlopen → mislukt mét reden, en daarna nooit meer stil geprobeerd.
        verwerk_openstaande_webhooks(nu=t0 + timedelta(days=13), transport=ontvanger.transport)
        assert _wacht_rij(admin_engine, rij_id)["status"] == WebhookStatus.WACHT_OP_ONTVANGER.value
        rapport = verwerk_openstaande_webhooks(nu=t0 + WACHT_MAX, transport=ontvanger.transport)
        assert rapport.wacht_verlopen == 1 and rapport.storing_verlopen == 0
        rij = _wacht_rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.MISLUKT.value
        assert rij["laatste_fout"] == "ontvanger kon niet koppelen binnen 14 dagen: referentie_conflict"
        assert rij["volgende_poging_op"] is None and rij["wacht_op_ontvanger_sinds"] == t0
        assert _audit_acties(admin_engine, rij_id)[-1] == "webhook_niet_koppelbaar_verlopen"
        n = ontvanger.aantal_409
        verwerk_openstaande_webhooks(nu=t0 + WACHT_MAX + timedelta(days=3), transport=ontvanger.transport)
        assert ontvanger.aantal_409 == n
        assert cli.main(["webhook-afleveren"]) in (0, 1)  # de CLI-regel noemt de nieuwe tellers (smoke)

    def test_nonce_replay_409_zonder_resultaat_blijft_gewone_retry(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = MockOntvanger(forceer_status=[409])  # tekst-body "opgelegde fout (test)", géén resultaat
        nu = datetime.now(UTC)
        rapport = verwerk_openstaande_webhooks(nu=nu, transport=ontvanger.transport)
        assert rapport.poging_mislukt == 1 and rapport.wacht_op_ontvanger == 0
        rij = _wacht_rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.OPENSTAAND.value and rij["wacht_pogingen"] == 0
        # 02-10 avond: de nonce-replay-409 is een storing → storingscadans (eerste stap 1 uur), geen wacht_op_ontvanger.
        assert rij["volgende_poging_op"] == nu + STORING_CADANS[0]

    def test_andere_niet_2xx_na_een_409_volgt_de_storingscadans_en_telt_409s_niet_mee(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        """Was tot 02-10 avond "8 pogingen ongeacht eerdere 409's" — nu de storingscadans (1 u → 6 u …) op
        `pogingen - wacht_pogingen`, nooit een dead-letter ná 8; de 409-poging telt niet mee."""
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = NietKoppelbaarOntvanger()
        t0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        verwerk_openstaande_webhooks(nu=t0, transport=ontvanger.transport)  # 409 → wacht
        ontvanger._forceer_status = [500, 500]  # daarna twee échte fouten
        verwerk_openstaande_webhooks(nu=t0 + 1 * UUR, transport=ontvanger.transport)
        rij = _wacht_rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.WACHT_OP_ONTVANGER.value and rij["pogingen"] == 2
        assert "500" in rij["laatste_fout"]
        assert rij["volgende_poging_op"] == t0 + 1 * UUR + STORING_CADANS[0]  # storingspoging 1 → +1 u
        verwerk_openstaande_webhooks(nu=t0 + 2 * UUR, transport=ontvanger.transport)
        rij = _wacht_rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.WACHT_OP_ONTVANGER.value
        assert rij["pogingen"] == 3 and rij["wacht_pogingen"] == 1
        assert rij["volgende_poging_op"] == t0 + 2 * UUR + STORING_CADANS[1]  # storingspoging 2 → +6 u
        assert "webhook_dead_letter" not in _audit_acties(admin_engine, rij_id)
        assert _audit_acties(admin_engine, rij_id)[-1] == "webhook_poging_mislukt"


class TestHerzendenEnNuOpnieuw:
    def test_herzenden_reset_het_wachten_en_ziet_een_wachtende_rij_als_onderweg(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = NietKoppelbaarOntvanger()
        t0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        verwerk_openstaande_webhooks(nu=t0, transport=ontvanger.transport)
        with admin_engine.connect() as conn:
            ref = conn.execute(
                text("SELECT payload -> 'data' ->> 'referentie' FROM boekhouding.webhook_uitgaand WHERE id = :id"),
                {"id": rij_id},
            ).scalar_one()
        uit = herzend_afgeleverd(
            actor_id=beheerder_id,
            administratie_id=vastgoed_administratie,
            referenties=[ref],
            reden="test",
            dry_run=True,
        )
        assert uit[0].uitkomst == "al openstaand — niet herzonden"
        verwerk_openstaande_webhooks(nu=t0 + WACHT_MAX, transport=ontvanger.transport)  # → mislukt (verlopen)
        uit = herzend_afgeleverd(
            actor_id=beheerder_id,
            administratie_id=vastgoed_administratie,
            referenties=[ref],
            reden="Vastly fix",
            dry_run=False,
        )
        assert uit[0].uitkomst == "herzonden"
        rij = _wacht_rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.OPENSTAAND.value
        assert rij["wacht_op_ontvanger_sinds"] is None and rij["wacht_pogingen"] == 0

    def test_nu_opnieuw_levert_direct_af_buiten_de_cadans_met_audit(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = NietKoppelbaarOntvanger()
        t0 = datetime.now(UTC) - timedelta(minutes=5)
        verwerk_openstaande_webhooks(nu=t0, transport=ontvanger.transport)
        # Nog niet aan de beurt (volgende poging over ~55 min), maar Vastly meldt: koppeling hersteld.
        ontvanger.koppelbaar = True
        r = nu_opnieuw(
            actor_id=beheerder_id,
            administratie_id=vastgoed_administratie,
            outbox_id=rij_id,
            transport=ontvanger.transport,
        )
        assert (r.status_voor, r.status_na) == (WebhookStatus.WACHT_OP_ONTVANGER.value, WebhookStatus.AFGELEVERD.value)
        assert r.uitkomst.startswith("afgeleverd")
        assert _audit_acties(admin_engine, rij_id) == [
            "webhook_wacht_op_ontvanger",
            "webhook_nu_opnieuw",
            "webhook_afgeleverd",
        ]

    def test_nu_opnieuw_op_verlopen_rij_start_opnieuw_en_wacht_bij_herhaalde_409(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = NietKoppelbaarOntvanger()
        t0 = datetime.now(UTC) - WACHT_MAX - timedelta(days=1)
        verwerk_openstaande_webhooks(nu=t0, transport=ontvanger.transport)
        verwerk_openstaande_webhooks(nu=t0 + WACHT_MAX, transport=ontvanger.transport)
        assert _wacht_rij(admin_engine, rij_id)["status"] == WebhookStatus.MISLUKT.value
        r = nu_opnieuw(
            actor_id=beheerder_id,
            administratie_id=vastgoed_administratie,
            outbox_id=rij_id,
            transport=ontvanger.transport,
        )
        assert r.status_voor == WebhookStatus.MISLUKT.value and r.status_na == WebhookStatus.WACHT_OP_ONTVANGER.value
        rij = _wacht_rij(admin_engine, rij_id)
        assert rij["wacht_pogingen"] == 1 and rij["wacht_op_ontvanger_sinds"] > t0 + WACHT_MAX  # verse telling

    def test_nu_opnieuw_weigert_een_rij_die_niet_wacht(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        with pytest.raises(NuOpnieuwNietMogelijk):
            nu_opnieuw(actor_id=beheerder_id, administratie_id=vastgoed_administratie, outbox_id=rij_id)
        with pytest.raises(LookupError):
            nu_opnieuw(actor_id=beheerder_id, administratie_id=vastgoed_administratie, outbox_id=uuid.uuid4())


class TestBlokWebhooks:
    def test_blok_staat_in_run_en_cli_en_soorten_in_registry_met_tekst(self) -> None:
        from app.reconciliatie import run as run_service

        assert run_service.BLOKKEN[-1] == webhook_reconciliatie.BLOK == "webhooks"
        assert cli._reconciliatie_run_blokken()[-1] == "webhooks"
        assert soort_stand.code_default(webhook_reconciliatie.SOORT_WACHT) == "meten"
        assert soort_stand.code_default(webhook_reconciliatie.SOORT_VERLOPEN) == "actie"
        assert soort_stand.REGISTRY[webhook_reconciliatie.SOORT_VERLOPEN].direct_actie_reden

    def test_blok_meldt_wachtende_en_verlopen_rij_met_handelingsdetail_en_leesbare_tekst(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        wacht_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        verlopen_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        gewoon_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        ontvanger = NietKoppelbaarOntvanger()
        t0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        verwerk_openstaande_webhooks(nu=t0, transport=ontvanger.transport)  # alle drie → wacht
        with admin_engine.begin() as conn:
            # `gewoon` wordt een gewone dead-letter (geen wacht-spoor) en hoort NIET in het blok.
            conn.execute(
                text(
                    "UPDATE boekhouding.webhook_uitgaand SET status = 'mislukt', wacht_op_ontvanger_sinds = NULL, "
                    "wacht_pogingen = 0, laatste_fout = 'HTTP 500' WHERE id = :id"
                ),
                {"id": gewoon_id},
            )
            conn.execute(
                text("UPDATE boekhouding.webhook_uitgaand SET volgende_poging_op = NULL WHERE id = :id"),
                {"id": verlopen_id},
            )
        # Alleen `verlopen` is aan de beurt op dag 14 (de andere wacht nog tot t0 + 1 u): die wordt mislukt-verlopen.
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.webhook_uitgaand SET volgende_poging_op = :vp WHERE id = :id"),
                {"id": wacht_id, "vp": t0 + WACHT_MAX + timedelta(days=5)},
            )
        verwerk_openstaande_webhooks(nu=t0 + WACHT_MAX, transport=ontvanger.transport)
        assert _wacht_rij(admin_engine, verlopen_id)["status"] == WebhookStatus.MISLUKT.value
        assert _wacht_rij(admin_engine, wacht_id)["status"] == WebhookStatus.WACHT_OP_ONTVANGER.value

        v = Verzamelaar()
        v.start_blok(webhook_reconciliatie.BLOK)
        regels: list[str] = []
        code = webhook_reconciliatie.cli_blok(None, v, stdout=regels.append, nu=t0 + WACHT_MAX)
        assert code == 1
        per_soort = {b.detail["afwijking_soort"]: b for b in v.bevindingen}
        assert set(per_soort) == {webhook_reconciliatie.SOORT_WACHT, webhook_reconciliatie.SOORT_VERLOPEN}
        wacht = per_soort[webhook_reconciliatie.SOORT_WACHT]
        assert wacht.administratie_id == vastgoed_administratie and wacht.detail["outbox_id"] == str(wacht_id)
        assert wacht.detail["reden"] == "onbekende_administratie" and wacht.detail["wacht_pogingen"] == 1
        assert wacht.detail["volgende_poging_op"] and datetime.fromisoformat(wacht.detail["sinds"]) == t0
        verlopen = per_soort[webhook_reconciliatie.SOORT_VERLOPEN]
        assert verlopen.detail["outbox_id"] == str(verlopen_id) and verlopen.detail["max_dagen"] == 14
        assert str(gewoon_id) not in {b.detail["outbox_id"] for b in v.bevindingen}
        assert regels[-1].startswith(
            "WEBHOOKS   2 outbox-rij(en) in wacht of verlopen getoetst: 1 wacht op de ontvanger"
        )
        for b in v.bevindingen:
            lees = teksten.leesbaar(b)
            assert len(lees.titel) <= teksten.MAX_TITEL and lees.wat and lees.doe
            assert "Nu opnieuw" in lees.doe
            assert not teksten.bevat_technische_sleutel(lees.wat) and not teksten.bevat_technische_sleutel(lees.doe)
        assert "14 dagen" in teksten.leesbaar(verlopen).titel

        # Zelfde blok via de CLI-keuzelijst (meetlat-vorm uit het meetrecept, letterlijk).
        assert cli.main(["reconciliatie-alles", "--alleen", "webhooks", "--lees-only"]) == 1
        out = capsys.readouterr().out
        assert "WEBHOOKS   2 outbox-rij(en)" in out and "AFWIJKING  webhooks" in out


class TestRouteNuOpnieuw:
    def test_route_200_409_404(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = NietKoppelbaarOntvanger()
        verwerk_openstaande_webhooks(nu=datetime.now(UTC) - timedelta(minutes=1), transport=ontvanger.transport)
        headers = _headers(admin_engine, gescoopte_gebruiker)
        body = {"administratie_id": str(vastgoed_administratie)}

        # De route gebruikt het echte httpx-transport; vervang 'm door de mock-ontvanger (koppeling intussen hersteld).
        ontvanger.koppelbaar = True
        echte = webhook_afleveraar.lever_rijen_direct_af

        def met_mock(**kw):  # noqa: ANN003, ANN202
            kw["transport"] = ontvanger.transport
            return echte(**kw)

        monkeypatch.setattr(webhook_afleveraar, "lever_rijen_direct_af", met_mock)
        r = client.post(f"/reconciliatie/webhooks/{rij_id}/nu-opnieuw", json=body, headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status_voor"] == "wacht_op_ontvanger" and data["status_na"] == "afgeleverd"
        assert data["uitkomst"].startswith("afgeleverd")
        # Nog eens: de rij wacht niet meer → 409 mét reden; onbekende rij → 404.
        r = client.post(f"/reconciliatie/webhooks/{rij_id}/nu-opnieuw", json=body, headers=headers)
        assert r.status_code == 409 and "wacht niet" in r.json()["detail"]
        r = client.post(f"/reconciliatie/webhooks/{uuid.uuid4()}/nu-opnieuw", json=body, headers=headers)
        assert r.status_code == 404
        assert client.post(f"/reconciliatie/webhooks/{rij_id}/nu-opnieuw", json=body).status_code == 401

    def test_route_aflevering_uit_is_zichtbaar_in_de_uitkomst(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.webhook_uitgaand SET status = 'wacht_op_ontvanger', wacht_pogingen = 1, "
                    "wacht_op_ontvanger_sinds = now(), laatste_fout = 'ontvanger kan nog niet koppelen (x) — wacht' "
                    "WHERE id = :id"
                ),
                {"id": rij_id},
            )
        r = client.post(
            f"/reconciliatie/webhooks/{rij_id}/nu-opnieuw",
            json={"administratie_id": str(vastgoed_administratie)},
            headers=_headers(admin_engine, gescoopte_gebruiker),
        )
        assert r.status_code == 200
        assert r.json()["uitkomst"].startswith("niet verstuurd — aflevering staat uit")
        assert r.json()["status_na"] == "wacht_op_ontvanger"


def test_db_lezen_query_webhook_outbox_laadt_met_de_nieuwe_kolommen() -> None:
    from app.lezen import bibliotheek

    q = bibliotheek.zoek("webhook-outbox")
    assert q.versie == "3"
    assert "wacht_op_ontvanger_sinds" in q.sql and "webhook_nu_opnieuw" in q.sql
    assert "webhook_aflevering_verlopen" in q.sql and "webhook_geweigerd_4xx" in q.sql  # 02-10 avond (17a)
    assert json.dumps(list(q.kolommen)).count("wacht") >= 2


class TestStoringscadans7Dagen:
    """02-10 avond (besluit Peter, besluiten run A punt 17a): storing → cadans tot 7 dagen → `mislukt` + bevinding
    direct
    `actie`; 4xx ≠ 409/429 → direct `mislukt`; "Nu opnieuw" werkt óók op die rijen (vers budget)."""

    def test_cadans_puur_9_pogingen_binnen_7_dagen(self) -> None:
        assert [storing_cumulatief(n) for n in (1, 2, 3, 4)] == [
            timedelta(hours=1), timedelta(hours=7), timedelta(hours=31), timedelta(hours=55)
        ]
        assert storing_cumulatief(8) == timedelta(hours=151) <= STORING_MAX
        assert storing_cumulatief(9) == timedelta(hours=175) > STORING_MAX
        assert not storing_verlopen(8) and storing_verlopen(9)
        assert timedelta(days=7) == STORING_MAX and timedelta(days=14) == WACHT_MAX  # 409 houdt 14 (RLZ-keuze 02-10)

    def test_blok_meldt_storing_verlopen_en_4xx_als_derde_soort_direct_actie_met_nu_opnieuw(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        maak = lambda: _maak_outbox_rij(  # noqa: E731
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        t0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        # payload: één 400 → direct mislukt; storing: 9 × 503 over de cadans; oud: oude dead-letter zonder prefix.
        # Eén rij per ronde, zodat de opgelegde status deterministisch bij de bedoelde rij landt.
        payload_id = maak()
        ontvanger = MockOntvanger(forceer_status=[400])
        verwerk_openstaande_webhooks(nu=t0, transport=ontvanger.transport)
        storing_id, oud_id = maak(), maak()
        ontvanger._forceer_status = [503, 503]
        verwerk_openstaande_webhooks(nu=t0, transport=ontvanger.transport)
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.webhook_uitgaand SET status = 'mislukt', volgende_poging_op = NULL, "
                    "laatste_fout = 'HTTP 500: oud' WHERE id = :id"
                ),
                {"id": oud_id},
            )
        ontvanger._forceer_status = [503] * 20
        for n in range(1, 9):
            verwerk_openstaande_webhooks(nu=t0 + storing_cumulatief(n), transport=ontvanger.transport)
        storing = _wacht_rij(admin_engine, storing_id)
        payload = _wacht_rij(admin_engine, payload_id)
        assert storing["status"] == payload["status"] == WebhookStatus.MISLUKT.value
        assert storing["laatste_fout"].startswith("aflevering mislukt binnen 7 dagen (9 pogingen): HTTP 503")
        assert payload["laatste_fout"].startswith("ontvanger weigerde het bericht (HTTP 400)")

        v = Verzamelaar()
        v.start_blok(webhook_reconciliatie.BLOK)
        regels: list[str] = []
        code = webhook_reconciliatie.cli_blok(None, v, stdout=regels.append, nu=t0 + STORING_MAX)
        assert code == 1
        per_outbox = {b.detail["outbox_id"]: b for b in v.bevindingen}
        # De oude dead-letter zonder prefix hoort er niet in.
        assert set(per_outbox) == {str(storing_id), str(payload_id)}
        s = per_outbox[str(storing_id)]
        assert s.detail["afwijking_soort"] == webhook_reconciliatie.SOORT_AFLEVERING_MISLUKT
        assert s.detail["reden_soort"] == "storing_verlopen" and s.detail["storing_pogingen"] == 9
        assert s.detail["max_dagen"] == 7 and s.detail["reden"].startswith("HTTP 503")
        p = per_outbox[str(payload_id)]
        assert p.detail["reden_soort"] == "payloadfout"
        assert p.detail["reden"].startswith("(HTTP 400): opgelegde fout (test)")
        assert regels[-1].endswith("0 ná 14 dagen mislukt, 2 ná 7 dagen storing of 4xx geweigerd")
        assert soort_stand.code_default(webhook_reconciliatie.SOORT_AFLEVERING_MISLUKT) == "actie"
        assert soort_stand.REGISTRY[webhook_reconciliatie.SOORT_AFLEVERING_MISLUKT].direct_actie_reden
        for b in v.bevindingen:
            lees = teksten.leesbaar(b)
            assert len(lees.titel) <= teksten.MAX_TITEL and lees.wat and lees.doe and "Nu opnieuw" in lees.doe
            assert not teksten.bevat_technische_sleutel(lees.wat) and not teksten.bevat_technische_sleutel(lees.doe)
        assert "7 dagen" in teksten.leesbaar(s).titel and "afgekeurd" in teksten.leesbaar(p).titel
        assert cli.main(["reconciliatie-alles", "--alleen", "webhooks", "--lees-only"]) == 1
        assert "2 ná 7 dagen storing of 4xx geweigerd" in capsys.readouterr().out

        # "Nu opnieuw" op zo'n rij: terug naar openstaand mét vers budget, direct één afleverronde (nu 200 →
        # afgeleverd).
        ontvanger._forceer_status = []
        uit = nu_opnieuw(  # échte klok: de mock toetst de timestamp tegen het replay-venster
            actor_id=beheerder_id, administratie_id=vastgoed_administratie, outbox_id=storing_id,
            nu=datetime.now(UTC), transport=ontvanger.transport,
        )
        assert uit.status_voor == "mislukt" and uit.status_na == WebhookStatus.AFGELEVERD.value
        assert _audit_acties(admin_engine, storing_id)[-2:] == ["webhook_nu_opnieuw", "webhook_afgeleverd"]
        # Een oude dead-letter zonder prefix blijft webhook-redrive-terrein (409 in de router).
        with pytest.raises(NuOpnieuwNietMogelijk):
            nu_opnieuw(actor_id=beheerder_id, administratie_id=vastgoed_administratie, outbox_id=oud_id, nu=t0,
            transport=ontvanger.transport)
