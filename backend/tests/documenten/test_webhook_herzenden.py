# ruff: noqa: F811 — pytest-fixtures als parameters
"""Webhook-herzenden + "200 genegeerd = zichtbaar mislukt" (Platform OPEN_ITEMS regel 13, vastgoed-verzoek 21-09: elf
`factuur_geboekt`-kostenevents Rubicon/ARVUM die Vastly vóór de matchsleutel-fix van 20-09 met 200 `{"resultaat":
"genegeerd", "reden": "onbekende_administratie"}` beantwoordde stonden bij ons "afgeleverd"). Twee regels:
(1) een 2xx mét `resultaat: genegeerd` is géén aflevering — rij `mislukt` mét de reden uit de body, audit
`webhook_genegeerd`, niet herhaald; (2) `herzend_afgeleverd` zet afgeleverde rijen op referentie terug naar openstaand
(zelfde payload → zelfde rlz_document_id/volgnummer, verse timestamp/nonce bij de volgende poging), audit
`webhook_herzonden`, dry-run schrijft niets, niet-gevonden referenties komen zichtbaar terug."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import Engine, text

from app import cli as app_cli
from app.documenten import webhook_afleveraar
from app.documenten.models import WebhookStatus
from app.documenten.storage import LokaleBestandsopslag
from app.documenten.webhook_afleveraar import herzend_afgeleverd, lever_rijen_direct_af, verwerk_openstaande_webhooks
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.test_webhook_afleveraar import (  # noqa: F401
    MockOntvanger,
    _audit_acties,
    _maak_outbox_rij,
    _rij,
    aflevering_aan,
    vastgoed_administratie,
)


class VastlyOntvanger(MockOntvanger):
    """Vastly's echte antwoordvorm (`src/layer1_functions/rlz_webhook.py`): 200 mét JSON `resultaat` (+ `reden`)."""

    def __init__(self, antwoorden: list[dict]) -> None:
        super().__init__()
        self._antwoorden = list(antwoorden)

    def verwerk(self, envelope: dict) -> httpx.Response:
        basis = super().verwerk(envelope)
        if basis.status_code != 200:
            return basis
        body = self._antwoorden.pop(0) if self._antwoorden else {"resultaat": "verwerkt"}
        return httpx.Response(200, json=body)


def _referentie(admin_engine: Engine, rij_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT payload -> 'data' ->> 'referentie' FROM boekhouding.webhook_uitgaand WHERE id = :id"),
            {"id": rij_id},
        ).scalar_one()


def _audit_detail(admin_engine: Engine, rij_id: uuid.UUID, actie: str) -> dict:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT nieuwe_waarde FROM platform.audit_event WHERE tabel = 'webhook_uitgaand' AND record_id = :id "
                "AND actie = :a ORDER BY tijdstip DESC LIMIT 1"
            ),
            {"id": rij_id, "a": actie},
        ).scalar_one()


class TestGenegeerdIsGeenAflevering:
    def test_200_genegeerd_wordt_zichtbaar_mislukt_met_reden_en_niet_herhaald(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = VastlyOntvanger([{"resultaat": "genegeerd", "reden": "onbekende_administratie"}])
        nu = datetime.now(UTC)
        rapport = verwerk_openstaande_webhooks(nu=nu, transport=ontvanger.transport)
        assert rapport.genegeerd == 1 and rapport.afgeleverd == 0
        assert any("genegeerd door de ontvanger — onbekende_administratie" in f for f in rapport.fouten)
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.MISLUKT.value and rij["afgeleverd_op"] is None
        assert rij["laatste_fout"] == "ontvanger negeerde het event: onbekende_administratie"
        assert rij["volgende_poging_op"] is None
        assert _audit_acties(admin_engine, rij_id) == ["webhook_genegeerd"]
        detail = _audit_detail(admin_engine, rij_id, "webhook_genegeerd")
        assert detail["resultaat"] == "genegeerd" and detail["ontvanger_reden"] == "onbekende_administratie"
        # Niet herhalen: een volgende run raakt de rij niet meer aan.
        verwerk_openstaande_webhooks(nu=nu + timedelta(hours=1), transport=ontvanger.transport)
        assert ontvanger.aantal_requests == 1 and _rij(admin_engine, rij_id)["pogingen"] == 1

    def test_verwerkt_en_al_verwerkt_zijn_afleveringen_met_resultaat_in_het_audit(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        r1 = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        r2 = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = VastlyOntvanger([{"resultaat": "voorstellen", "aangemaakt": 2}, {"resultaat": "al_verwerkt"}])
        rapport = verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert rapport.afgeleverd == 2 and rapport.genegeerd == 0
        assert _rij(admin_engine, r1)["status"] == WebhookStatus.AFGELEVERD.value
        assert {_audit_detail(admin_engine, r, "webhook_afgeleverd")["resultaat"] for r in (r1, r2)} == {
            "voorstellen",
            "al_verwerkt",
        }
        # Een 200 zonder JSON-body (de oude mock) blijft een gewone aflevering.
        r3 = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        verwerk_openstaande_webhooks(transport=MockOntvanger().transport)
        assert _rij(admin_engine, r3)["status"] == WebhookStatus.AFGELEVERD.value
        assert _audit_detail(admin_engine, r3, "webhook_afgeleverd")["resultaat"] is None


class TestHerzenden:
    def test_dry_run_toont_de_rijen_zonder_te_schrijven(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        verwerk_openstaande_webhooks(transport=MockOntvanger().transport)
        ref = _referentie(admin_engine, rij_id)
        uit = herzend_afgeleverd(
            actor_id=beheerder_id,
            administratie_id=vastgoed_administratie,
            referenties=[ref, "BESTAAT-NIET"],
            reden="",
            dry_run=True,
        )
        assert [(r.referentie, r.uitkomst) for r in uit] == [
            (ref, "zou herzenden (dry-run)"),
            ("BESTAAT-NIET", "niet gevonden"),
        ]
        assert uit[0].outbox_id == rij_id and uit[0].status_voor == "afgeleverd" and uit[0].volgnummer == 1
        assert _rij(admin_engine, rij_id)["status"] == WebhookStatus.AFGELEVERD.value
        assert _audit_acties(admin_engine, rij_id) == ["webhook_afgeleverd"]

    def test_uitvoeren_zet_terug_naar_openstaand_met_audit_en_de_afleveraar_verstuurt_dezelfde_payload_opnieuw(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        eerste = VastlyOntvanger([{"resultaat": "genegeerd", "reden": "onbekende_administratie"}])
        # De situatie van 21-09: de ontvanger negeerde, maar de rij stond (vóór deze fix) als afgeleverd. Simuleer dat
        # door de oude mock (200 zonder body) te gebruiken → afgeleverd.
        verwerk_openstaande_webhooks(transport=MockOntvanger().transport)
        assert _rij(admin_engine, rij_id)["status"] == WebhookStatus.AFGELEVERD.value
        ref = _referentie(admin_engine, rij_id)
        with pytest.raises(ValueError, match="reden is verplicht"):
            herzend_afgeleverd(
                actor_id=beheerder_id,
                administratie_id=vastgoed_administratie,
                referenties=[ref],
                reden="",
                dry_run=False,
            )
        uit = herzend_afgeleverd(
            actor_id=beheerder_id,
            administratie_id=vastgoed_administratie,
            referenties=[ref],
            reden="Vastly negeerde het event vóór de matchsleutel-fix van 20-09 (OPEN_ITEMS regel 13)",
            dry_run=False,
        )
        assert [r.uitkomst for r in uit] == ["herzonden"]
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.OPENSTAAND.value and rij["pogingen"] == 0
        assert rij["afgeleverd_op"] is None
        assert _audit_acties(admin_engine, rij_id) == ["webhook_afgeleverd", "webhook_herzonden"]
        detail = _audit_detail(admin_engine, rij_id, "webhook_herzonden")
        assert detail["referentie"] == ref and detail["volgnummer"] == 1 and "OPEN_ITEMS regel 13" in detail["reden"]
        # De gewone afleveraar verstuurt opnieuw: zelfde data (rlz_document_id/volgnummer), verse timestamp + nonce.
        ontvanger = VastlyOntvanger([{"resultaat": "voorstellen", "aangemaakt": 1}])
        # (dagen ná de oorspronkelijke aflevering; de mock toetst het replay-venster tegen de échte klok → nu)
        verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert ontvanger.aantal_requests == 1
        envelope = ontvanger.ontvangen[0]
        assert envelope["data"]["referentie"] == ref and envelope["data"]["volgnummer"] == 1
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.AFGELEVERD.value and rij["pogingen"] == 1
        assert _audit_detail(admin_engine, rij_id, "webhook_afgeleverd")["resultaat"] == "voorstellen"
        # Al herzonden + weer afgeleverd: een tweede herzending is opnieuw mogelijk (idempotente ontvanger), en een
        # mislukte rij wordt bewust NIET meegenomen (dat is webhook-redrive).
        del eerste

    def test_genegeerde_mislukte_rij_wordt_herzonden_en_een_openstaande_niet_dubbel(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        """24-09 (herzending Rubicon): de ontvanger negeerde de eerste herzending → rij `mislukt`. Ná een fix aan de
        ontvangerkant is herzenden op referentie hét herstel — de rij mag niet alleen via webhook-redrive terug."""
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        verwerk_openstaande_webhooks(
            transport=VastlyOntvanger([{"resultaat": "genegeerd", "reden": "onbekend_document"}]).transport
        )
        assert _rij(admin_engine, rij_id)["status"] == WebhookStatus.MISLUKT.value
        ref = _referentie(admin_engine, rij_id)
        uit = herzend_afgeleverd(
            actor_id=beheerder_id,
            administratie_id=vastgoed_administratie,
            referenties=[ref],
            reden="herzend-test ná fix ontvanger",
            dry_run=False,
        )
        assert [(r.status_voor, r.uitkomst) for r in uit] == [("mislukt", "herzonden")]
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.OPENSTAAND.value and rij["pogingen"] == 0 and rij["laatste_fout"] is None
        detail = _audit_detail(admin_engine, rij_id, "webhook_herzonden")
        assert detail["status"] == "openstaand"
        # Al openstaand: niet dubbel terugzetten, wel zichtbaar.
        uit = herzend_afgeleverd(
            actor_id=beheerder_id,
            administratie_id=vastgoed_administratie,
            referenties=[ref],
            reden="herzend-test tweede keer",
            dry_run=False,
        )
        assert uit[0].uitkomst == "al openstaand — niet herzonden"
        assert _audit_acties(admin_engine, rij_id) == ["webhook_genegeerd", "webhook_herzonden"]


class TestSamengesteldAntwoord:
    """Vastly's `factuur_geboekt`-antwoord bestaat uit twee verwerkers: de verkoopfactuur-badge op het topniveau en de
    kostenregel-verwerker genest onder `kostenvoorstellen`. Voor een inkoopfactuur zegt het topniveau per definitie
    `genegeerd`/`onbekend_document` (herzending Rubicon 24-09 17:55 UTC: zes rijen ten onrechte `mislukt`)."""

    def test_topniveau_genegeerd_met_genest_voorstellen_is_een_aflevering(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = VastlyOntvanger(
            [
                {
                    "resultaat": "genegeerd",
                    "reden": "onbekend_document",
                    "kostenvoorstellen": {"resultaat": "voorstellen", "aangemaakt": 2, "al_aanwezig": 0},
                }
            ]
        )
        rapport = verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert rapport.afgeleverd == 1 and rapport.genegeerd == 0 and rapport.zonder_verwerking == 0
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.AFGELEVERD.value and rij["laatste_fout"] is None
        detail = _audit_detail(admin_engine, rij_id, "webhook_afgeleverd")
        assert detail["resultaat"] == "voorstellen" and detail["topniveau_resultaat"] == "genegeerd"
        assert '"kostenvoorstellen"' in detail["ontvanger_antwoord"]

    def test_kostenintake_uit_is_afgeleverd_zonder_verwerking_en_zichtbaar(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = VastlyOntvanger(
            [
                {
                    "resultaat": "genegeerd",
                    "reden": "onbekend_document",
                    "kostenvoorstellen": {"resultaat": "kostenintake_uit"},
                }
            ]
        )
        rapport = verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert rapport.afgeleverd == 1 and rapport.zonder_verwerking == 1 and rapport.genegeerd == 0
        assert rapport.fouten == [] and len(rapport.let_op) == 1 and "kostenintake_uit" in rapport.let_op[0]
        assert _rij(admin_engine, rij_id)["status"] == WebhookStatus.AFGELEVERD.value
        assert _audit_detail(admin_engine, rij_id, "webhook_afgeleverd")["resultaat"] == "kostenintake_uit"
        # Niet herhalen: zelfde payload = zelfde antwoord tot de klant de vlag aan Vastly-kant omzet.
        verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert ontvanger.aantal_requests == 1

    def test_genest_genegeerd_blijft_genegeerd_met_de_geneste_reden(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        ontvanger = VastlyOntvanger(
            [
                {
                    "resultaat": "genegeerd",
                    "reden": "onbekend_document",
                    "kostenvoorstellen": {"resultaat": "genegeerd", "reden": "onbekende_administratie"},
                }
            ]
        )
        rapport = verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert rapport.genegeerd == 1 and rapport.afgeleverd == 0
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.MISLUKT.value
        assert rij["laatste_fout"] == "ontvanger negeerde het event: onbekende_administratie"

    def test_directe_afleverronde_geeft_uitkomst_per_rij(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        r1 = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        r2 = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        verwerk_openstaande_webhooks(transport=MockOntvanger().transport)
        refs = [_referentie(admin_engine, r1), _referentie(admin_engine, r2)]
        uit = herzend_afgeleverd(
            actor_id=beheerder_id, administratie_id=vastgoed_administratie, referenties=refs,
            reden="directe afleverronde test", dry_run=False,
        )
        assert [r.uitkomst for r in uit] == ["herzonden", "herzonden"]
        ontvanger = VastlyOntvanger(
            [
                {
                    "resultaat": "genegeerd",
                    "reden": "onbekend_document",
                    "kostenvoorstellen": {"resultaat": "al_verwerkt"},
                },
                {"resultaat": "genegeerd", "reden": "onbekend_document"},
            ]
        )
        rapport = lever_rijen_direct_af(
            rij_ids=[r1, r2], administratie_id=vastgoed_administratie, transport=ontvanger.transport
        )
        assert rapport.afgeleverd == 1 and rapport.genegeerd == 1 and ontvanger.aantal_requests == 2
        assert rapport.per_rij[r1] == "afgeleverd — resultaat al_verwerkt"
        assert rapport.per_rij[r2] == "genegeerd door de ontvanger — onbekend_document"
        assert _rij(admin_engine, r1)["status"] == WebhookStatus.AFGELEVERD.value
        assert _rij(admin_engine, r2)["status"] == WebhookStatus.MISLUKT.value
        # Een rij die niet (meer) openstaand is, wordt niet geraakt — zichtbaar.
        rapport = lever_rijen_direct_af(
            rij_ids=[r1], administratie_id=vastgoed_administratie, transport=ontvanger.transport
        )
        assert rapport.per_rij[r1] == "niet geraakt (al geclaimd of niet openstaand)" and ontvanger.aantal_requests == 2


class TestCli:
    def test_cli_dry_run_en_uitvoeren(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        verwerk_openstaande_webhooks(transport=MockOntvanger().transport)
        ref = _referentie(admin_engine, rij_id)
        basis = ["webhook-herzenden", "--administratie", str(vastgoed_administratie), "--referentie", ref,
                 "--referentie", "X-ONBEKEND", "--beheerder-id", str(beheerder_id)]
        code = app_cli.main(basis)
        uit = capsys.readouterr()
        assert code == 1  # één referentie niet gevonden = exit 1 (zichtbaar), niets geschreven
        assert "DRY-RUN — niets gewijzigd" in uit.out and "zou herzenden (dry-run)" in uit.out
        assert "LET-OP  X-ONBEKEND: niet gevonden" in uit.err
        assert _rij(admin_engine, rij_id)["status"] == WebhookStatus.AFGELEVERD.value
        code = app_cli.main(
            ["webhook-herzenden", "--administratie", str(vastgoed_administratie), "--referentie", ref,
             "--beheerder-id", str(beheerder_id), "--uitvoeren", "--reden", "OPEN_ITEMS regel 13 herzending"]
        )
        uit = capsys.readouterr()
        assert code == 0 and "UITGEVOERD" in uit.out and "TOTAAL: herzonden 1" in uit.out
        assert _rij(admin_engine, rij_id)["status"] == WebhookStatus.OPENSTAAND.value
        # Zonder reden bij --uitvoeren: geweigerd.
        assert app_cli.main(
            ["webhook-herzenden", "--administratie", str(vastgoed_administratie), "--referentie", ref,
             "--beheerder-id", str(beheerder_id), "--uitvoeren"]
        ) == 1
        assert "reden is verplicht" in capsys.readouterr().err

    def test_cli_uitvoeren_met_afleveren_toont_de_uitkomst_per_referentie(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rij_id = _maak_outbox_rij(administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag)
        verwerk_openstaande_webhooks(transport=MockOntvanger().transport)
        ref = _referentie(admin_engine, rij_id)
        ontvanger = VastlyOntvanger(
            [
                {
                    "resultaat": "genegeerd",
                    "reden": "onbekend_document",
                    "kostenvoorstellen": {"resultaat": "kostenintake_uit"},
                }
            ]
        )
        echte = lever_rijen_direct_af
        monkeypatch.setattr(
            webhook_afleveraar, "lever_rijen_direct_af", lambda **kw: echte(transport=ontvanger.transport, **kw)
        )
        code = app_cli.main(
            ["webhook-herzenden", "--administratie", str(vastgoed_administratie), "--referentie", ref,
             "--beheerder-id", str(beheerder_id), "--uitvoeren", "--afleveren", "--reden", "herzending mét bewijs"]
        )
        uit = capsys.readouterr()
        assert code == 0, uit.err
        assert "TOTAAL: herzonden 1" in uit.out and "AFLEVERRONDE direct ná herzenden: 1 rij(en)" in uit.out
        assert f"{ref} | {rij_id} | afgeleverd — resultaat kostenintake_uit" in uit.out
        assert "TOTAAL afleverronde: afgeleverd 1 (waarvan zonder verwerking 1)" in uit.out
        assert f"LET-OP  {ref}: afgeleverd maar niet verwerkt — ontvanger antwoordt kostenintake_uit" in uit.err
        assert ontvanger.aantal_requests == 1 and _rij(admin_engine, rij_id)["status"] == WebhookStatus.AFGELEVERD.value

    def test_cli_onbekende_of_meerduidige_administratie_is_fout(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert app_cli.main(
            ["webhook-herzenden", "--administratie", "zzz-bestaat-niet-zzz", "--referentie", "1",
             "--beheerder-id", str(beheerder_id)]
        ) == 1
        assert "niet eenduidig (0 treffer(s)" in capsys.readouterr().err
        # Een onbekende UUID is óók een fout — geen stille "niet gevonden" per referentie (ARVUM 24-09).
        assert app_cli.main(
            ["webhook-herzenden", "--administratie", str(uuid.uuid4()), "--referentie", "1",
             "--beheerder-id", str(beheerder_id)]
        ) == 1
        assert "niet eenduidig (0 treffer(s)" in capsys.readouterr().err

    def test_administratie_via_rlz_admin_id_en_meerduidige_naam_kiest_de_vastgoed_administratie(
        self, administratie_id: uuid.UUID, admin_engine: Engine, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ARVUM 24-09: Peter gaf de rlz_admin_id (die Vastly's signalen dragen) i.p.v. de platform-id → "niet
        gevonden"; en de naam "ARVUM B.V." bestaat sinds de Odoo-parallel-modus twee keer (RLZ is_vastgoed + Odoo)."""
        rlz_guid = str(uuid.uuid4())
        odoo_id = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE platform.administratie SET naam = 'Dubbel Test B.V.', rlz_admin_id = :rlz, "
                    "is_vastgoed = true WHERE id = :id"
                ),
                {"id": administratie_id, "rlz": rlz_guid},
            )
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id, is_vastgoed) "
                     "VALUES (:id, 'Dubbel Test B.V.', :rlz, false)"),
                {"id": odoo_id, "rlz": f"odoo:test.odoo.com:{odoo_id.int % 1000}"},
            )
        try:
            assert app_cli._zoek_administratie_id(rlz_guid) == administratie_id
            assert "is de rlz_admin_id van 'Dubbel Test B.V.'" in capsys.readouterr().out
            assert app_cli._zoek_administratie_id("Dubbel Test") == administratie_id
            assert "de enige vastgoed-administratie gekozen" in capsys.readouterr().out
            assert app_cli._zoek_administratie_id(str(odoo_id)) == odoo_id
            # Twee vastgoed-administraties met dezelfde naam: geen keuze, kandidaten mét id tonen.
            with admin_engine.begin() as conn:
                conn.execute(
                    text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"), {"id": odoo_id}
                )
            assert app_cli._zoek_administratie_id("Dubbel Test") is None
            err = capsys.readouterr().err
            assert "2 treffer(s)" in err and str(odoo_id) in err and rlz_guid in err
        finally:
            with admin_engine.begin() as conn:
                conn.execute(text("DELETE FROM platform.administratie WHERE id = :id"), {"id": odoo_id})
