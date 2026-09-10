"""Bewakingsprobe `deploy_drift` (ochtendrun 11-09 blok 2.1): service-beeld vs. job-beelden via een gestubde Cloud Run
Admin API — gratieperiode, drift = fout + audit (idempotent), leesfout = fout mét melding, geen resource = overgeslagen;
plus de reconciliatie-LET-OP "systeemfout — automatisch gemeld" op een open storing (beheer-signaal, leesbaar)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.bewaking import deploy_drift, service
from app.bewaking.models import BewakingStoring
from app.config import settings
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import teksten
from app.reconciliatie.run import Bevinding, is_beheer_signaal

SERVICE = "projects/p/locations/europe-west4/services/rlz-backend"
OUDER = "projects/p/locations/europe-west4"
BEELD_NIEUW = "europe-west4-docker.pkg.dev/p/rlz/backend:58feacb99ff2a691ea41f0b3f2d8426de1c13001"
BEELD_OUD = "europe-west4-docker.pkg.dev/p/rlz/backend:2990c8b1111111111111111111111111111111111"
REVISIE_OP = datetime(2026, 9, 10, 19, 41, 20, tzinfo=UTC)


def _api(
    jobs: dict[str, str], *, per_pagina: int | None = None, revisie: str = "rlz-backend-00505-hkk"
) -> dict[str, dict]:
    """Antwoorden per v2-pad, in de vorm die de echte API op 10-09 gaf (geverifieerd met curl)."""
    antwoorden = {
        SERVICE: {
            "name": SERVICE,
            "latestReadyRevision": f"{SERVICE}/revisions/{revisie}",
            "template": {"containers": [{"image": BEELD_NIEUW}]},
        },
        f"{SERVICE}/revisions/{revisie}": {"createTime": "2026-09-10T19:41:20.397608Z"},
    }
    rijen = [
        {"name": f"{OUDER}/jobs/{naam}", "template": {"template": {"containers": [{"image": beeld}]}}}
        for naam, beeld in jobs.items()
    ]
    if per_pagina is None:
        antwoorden[f"{OUDER}/jobs?pageSize=100"] = {"jobs": rijen}
    else:
        antwoorden[f"{OUDER}/jobs?pageSize=100"] = {"jobs": rijen[:per_pagina], "nextPageToken": "p2"}
        antwoorden[f"{OUDER}/jobs?pageSize=100&pageToken=p2"] = {"jobs": rijen[per_pagina:]}
    return antwoorden


def _stub_api(monkeypatch: pytest.MonkeyPatch, antwoorden: dict[str, dict]) -> list[str]:
    paden: list[str] = []

    def nep_get(pad: str, *, token: str) -> dict:
        paden.append(pad)
        if pad not in antwoorden:
            raise deploy_drift.DeployDriftLeesfout(f"GET {pad} → 403: Permission 'run.jobs.list' denied")
        return antwoorden[pad]

    monkeypatch.setattr(deploy_drift, "_get", nep_get)
    monkeypatch.setattr(deploy_drift, "metadata_token", lambda: "token")
    return paden


@pytest.fixture()
def mails(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []

    def nep_verzend(*, onderwerp: str, tekst: str) -> bool:
        verzonden.append({"onderwerp": onderwerp, "tekst": tekst})
        return True

    monkeypatch.setattr(service, "_verzend_alert", nep_verzend)
    return verzonden


def _schoon() -> None:
    """Open deploy_drift-storingen sluiten (de app-rol mag niet DELETEn; UPDATE wél) — de test-DB houdt rijen."""
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        for rij in session.scalars(
            select(BewakingStoring).where(
                BewakingStoring.soort == deploy_drift.SOORT, BewakingStoring.hersteld_op.is_(None)
            )
        ):
            rij.hersteld_op = datetime.now(UTC)


def _audit_events(revisie: str) -> list[dict]:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = session.execute(select(AuditEvent.nieuwe_waarde).where(AuditEvent.actie == "deploy_drift")).all()
    return [nw for (nw,) in rijen if (nw or {}).get("service_revisie") == revisie]


class TestLeesStand:
    def test_leest_service_revisie_en_jobs_gepagineerd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        jobs = {"rlz-sync": BEELD_NIEUW, "rlz-bewaking": BEELD_NIEUW, "rlz-reconciliatie": BEELD_OUD}
        paden = _stub_api(monkeypatch, _api(jobs, per_pagina=2))
        stand = deploy_drift.lees_stand(service_resource=SERVICE, token="t")
        assert stand.service_image == BEELD_NIEUW
        assert stand.service_revisie == "rlz-backend-00505-hkk"
        assert stand.service_revisie_op == datetime(2026, 9, 10, 19, 41, 20, 397608, tzinfo=UTC)
        assert stand.jobs == jobs
        assert any("pageToken=p2" in p for p in paden)

    def test_leesfout_wordt_leesfout_met_letterlijke_melding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_api(monkeypatch, {})
        with pytest.raises(deploy_drift.DeployDriftLeesfout, match="403"):
            deploy_drift.lees_stand(service_resource=SERVICE, token="t")


class TestBeoordeel:
    def _stand(self, jobs: dict[str, str]) -> deploy_drift.DeployStand:
        return deploy_drift.DeployStand(
            service_resource=SERVICE,
            service_image=BEELD_NIEUW,
            service_revisie="rlz-backend-00505-hkk",
            service_revisie_op=REVISIE_OP,
            jobs=jobs,
        )

    def test_alles_gelijk_is_geen_drift(self) -> None:
        stand = self._stand({"rlz-sync": BEELD_NIEUW, "rlz-bewaking": BEELD_NIEUW})
        oordeel = deploy_drift.beoordeel(stand, nu=REVISIE_OP + timedelta(hours=5))
        assert oordeel.achter == {} and not oordeel.is_drift
        assert (
            deploy_drift.samenvatting(stand, oordeel)
            == "service en 2 job(s) op 58feacb (revisie rlz-backend-00505-hkk)"
        )

    def test_binnen_gratie_is_lopende_deploy_geen_drift(self) -> None:
        stand = self._stand({"rlz-sync": BEELD_OUD, "rlz-bewaking": BEELD_NIEUW})
        oordeel = deploy_drift.beoordeel(stand, nu=REVISIE_OP + timedelta(minutes=10))
        assert oordeel.achter == {"rlz-sync": BEELD_OUD} and oordeel.binnen_gratie and not oordeel.is_drift
        assert "deploy loopt nog" in deploy_drift.samenvatting(stand, oordeel)

    def test_na_dertig_minuten_is_het_drift(self) -> None:
        stand = self._stand({"rlz-sync": BEELD_OUD, "rlz-bewaking": BEELD_NIEUW, "rlz-intake-imap": BEELD_OUD})
        oordeel = deploy_drift.beoordeel(stand, nu=REVISIE_OP + timedelta(minutes=31))
        assert oordeel.is_drift and list(oordeel.achter) == ["rlz-intake-imap", "rlz-sync"]
        tekst = deploy_drift.samenvatting(stand, oordeel)
        assert tekst.startswith(
            "2 van 3 job(s) achter op de service (58feacb, revisie rlz-backend-00505-hkk van 10-09 19:41 UTC)"
        )
        assert "rlz-sync op 2990c8b" in tekst and "gratie" not in tekst
        # Zelfde situatie = zelfde audit-record-id; een extra achterlopende job = een nieuwe situatie.
        assert deploy_drift.audit_record_id(stand, oordeel) == deploy_drift.audit_record_id(stand, oordeel)
        stand2 = self._stand({**stand.jobs, "rlz-bewaking": BEELD_OUD})
        assert deploy_drift.audit_record_id(
            stand2, deploy_drift.beoordeel(stand2, nu=REVISIE_OP + timedelta(hours=1))
        ) != (deploy_drift.audit_record_id(stand, oordeel))

    def test_kort_beeld(self) -> None:
        assert deploy_drift.kort_beeld(BEELD_NIEUW) == "58feacb"
        assert deploy_drift.kort_beeld("eu.pkg.dev/p/rlz/backend@sha256:fe47a47948ef0859b99b") == "sha256:fe47a47948ef"


class TestProbe:
    def test_zonder_resource_overgeslagen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "bewaking_service_resource", None)
        u = service._probe_deploy_drift(datetime.now(UTC))
        assert (u.soort, u.status) == ("deploy_drift", "overgeslagen") and "BEWAKING_SERVICE_RESOURCE" in (
            u.detail or ""
        )

    def test_drift_is_fout_met_audit_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _schoon()
        monkeypatch.setattr(settings, "bewaking_service_resource", SERVICE)
        revisie = f"rlz-backend-{uuid.uuid4().hex[:8]}"  # unieke drift-situatie per testrun (gedeelde test-DB)
        _stub_api(monkeypatch, _api({"rlz-sync": BEELD_OUD, "rlz-bewaking": BEELD_NIEUW}, revisie=revisie))
        nu = REVISIE_OP + timedelta(hours=2)
        u = service._probe_deploy_drift(nu)
        assert u.status == "fout" and "rlz-sync op 2990c8b" in (u.detail or "")
        u2 = service._probe_deploy_drift(nu + timedelta(minutes=15))
        assert u2.status == "fout"
        events = _audit_events(revisie)
        assert len(events) == 1, "audit deploy_drift is idempotent per drift-situatie"
        assert events[0]["jobs_achter"] == {"rlz-sync": BEELD_OUD} and events[0]["service_revisie"] == revisie

    def test_binnen_gratie_ok_met_detail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _schoon()
        monkeypatch.setattr(settings, "bewaking_service_resource", SERVICE)
        revisie = f"rlz-backend-{uuid.uuid4().hex[:8]}"
        _stub_api(monkeypatch, _api({"rlz-sync": BEELD_OUD}, revisie=revisie))
        u = service._probe_deploy_drift(REVISIE_OP + timedelta(minutes=5))
        assert u.status == "ok" and "deploy loopt nog" in (u.detail or "")
        assert _audit_events(revisie) == []

    def test_leesfout_is_fout_met_rechten_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "bewaking_service_resource", SERVICE)
        _stub_api(monkeypatch, {})
        u = service._probe_deploy_drift(datetime.now(UTC))
        assert u.status == "fout" and "run.viewer" in (u.detail or "") and "403" in (u.detail or "")

    def test_statemachine_alarmeert_bij_tweede_meting_en_meldt_herstel(
        self, monkeypatch: pytest.MonkeyPatch, mails: list[dict]
    ) -> None:
        _schoon()
        nu = datetime.now(UTC)
        fout = service.ProbeUitkomst(soort="deploy_drift", status="fout", detail="1 van 15 job(s) achter")
        service._verwerk_uitkomst(fout, nu=nu)
        assert mails == []
        service._verwerk_uitkomst(fout, nu=nu + timedelta(minutes=15))
        assert len(mails) == 1 and "deploy_drift" in mails[0]["onderwerp"] and "⛔" in mails[0]["onderwerp"]
        # Reconciliatie ziet de open storing als beheer-LET-OP.
        kw = auto.deploy_drift_bevinding(nu=nu + timedelta(minutes=16))
        assert kw is not None and kw["soort"] == "let_op" and kw["administratie_id"] is None
        assert kw["detail"]["reden"] == auto.DEPLOY_DRIFT and kw["detail"]["gealarmeerd"] is True
        assert auto.REGRESSIE_TEKST in kw["tekst"] and "1 van 15 job(s) achter" in kw["tekst"]
        b = Bevinding(
            blok=kw["blok"],
            soort=kw["soort"],
            administratie_id=kw["administratie_id"],
            vingerafdruk=kw["vingerafdruk"],
            tekst=kw["tekst"],
            detail=kw["detail"],
        )
        assert is_beheer_signaal(b)
        lees = teksten.leesbaar(b, administratie_naam=None)
        assert lees.titel.startswith("Deploy-drift") and "Systeemfout — automatisch gemeld" in lees.doe
        assert "1 van 15 job(s) achter" in lees.wat
        assert not teksten.bevat_technische_sleutel(lees.titel + lees.wat + lees.doe)
        # Vingerafdruk stabiel over metingen → één actiemail/systeemmail.
        assert kw["vingerafdruk"] == auto.deploy_drift_bevinding(nu=nu + timedelta(hours=3))["vingerafdruk"]
        # Herstel: groen → storing dicht, herstelmelding, geen LET-OP meer.
        service._verwerk_uitkomst(service.ProbeUitkomst(soort="deploy_drift", status="ok"), nu=nu + timedelta(hours=4))
        assert len(mails) == 2 and "hersteld" in mails[1]["onderwerp"]
        assert auto.deploy_drift_bevinding(nu=nu + timedelta(hours=5)) is None


def test_deploy_drift_staat_in_de_kwartierrun(monkeypatch: pytest.MonkeyPatch) -> None:
    """De probe draait élk kwartier mee (niet in het uurvenster) en landt in de statusrij."""
    monkeypatch.setattr(settings, "bewaking_service_resource", None)
    aangeroepen: list[str] = []

    def stub(soort: str) -> service.ProbeUitkomst:
        aangeroepen.append(soort)
        return service.ProbeUitkomst(soort=soort, status="ok")

    for naam in (
        "_probe_health",
        "_probe_database",
        "_probe_documentopslag",
        "_probe_mailkanaal",
        "_probe_rlz",
        "_probe_reconciliatie_mail",
        "_probe_ai",
    ):
        monkeypatch.setattr(service, naam, lambda naam=naam: stub(naam[7:]))
    for naam in ("_probe_automatisering_regressie", "_probe_extractie_foutratio", "_probe_intake_verwerpingsratio"):
        monkeypatch.setattr(service, naam, lambda nu, naam=naam: stub(naam[7:]))
    monkeypatch.setattr(service, "_verzend_alert", lambda **kw: True)
    statussen = service.voer_probes_uit(nu=datetime.now(UTC) + timedelta(days=3, seconds=uuid.uuid4().int % 3600))
    assert statussen["deploy_drift"] == "overgeslagen"
    assert "deploy_drift" in statussen
