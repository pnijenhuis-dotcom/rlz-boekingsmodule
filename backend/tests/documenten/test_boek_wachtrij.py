"""Boeken sneller (Peter 18-09), stap 2 + 3: de achtergrond-schrijver.

- `dien_boeking_in` = synchroon deel → wordt_geboekt + audit + volgende document; de worker rondt af (geboekt) of zet
  zichtbaar boeken_mislukt; claim per idempotency-key; een tweede taak op dezelfde boeking = overgeslagen (één RLZ-
  document); herstel-vangnet voor gestrande boekingen; `kies_volgend_document` = spiegel van kiesVolgendDocument.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import boek_wachtrij, boeken, boekvoorstel, service
from app.documenten.models import DocumentStatus
from app.documenten.statusmachine import _TOEGESTANE_OVERGANGEN
from app.documenten.storage import LokaleBestandsopslag
from tests.documenten.fake_rlz_client import FakeBoekClient


def _regel() -> boekvoorstel.BoekvoorstelRegelData:
    return boekvoorstel.BoekvoorstelRegelData(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"),
        omschrijving="Testregel",
    )


def _klaar(administratie_id, actor, opslag, *, referentie: str) -> uuid.UUID:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"{uuid.uuid4()}.pdf",
        inhoud=b"%PDF-1.4 " + uuid.uuid4().bytes,
        actor_id=actor,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor,
        vendor_id=uuid.uuid4(),
        referentie=referentie,
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal("121.00"),
        regels=[_regel()],
    )
    return resultaat.document_id


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}).scalar_one()


class _Verzamelaar:
    """Wachtrij die alleen verzamelt — de test roept de worker zelf aan (het asynchrone gedrag zichtbaar)."""

    def __init__(self) -> None:
        self.items: list[tuple[uuid.UUID, uuid.UUID]] = []

    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> None:
        self.items.append((administratie_id, document_id))


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


class TestDienInEnWorker:
    def test_indienen_zet_wordt_geboekt_en_de_worker_boekt_precies_een_keer(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        document_id = _klaar(administratie_id, gescoopte_gebruiker, opslag, referentie="F-1")
        wachtrij = _Verzamelaar()

        ingediend = boek_wachtrij.dien_boeking_in(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker, wachtrij=wachtrij
        )
        assert ingediend.status == DocumentStatus.WORDT_GEBOEKT
        assert ingediend.sleutel == f"boek-{document_id}-0"
        assert _status(admin_engine, document_id) == "wordt_geboekt"
        assert wachtrij.items == [(administratie_id, document_id)]
        assert fake.puts == []  # niets naar RLZ in het synchrone deel

        # Nog eens indienen terwijl 'ie onderweg is = 409-waardige fout, geen tweede claim.
        with pytest.raises(boeken.OngeldigeBoekpoging):
            boek_wachtrij.dien_boeking_in(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker, wachtrij=wachtrij
            )

        assert boek_wachtrij.verwerk_boek_taak(administratie_id=administratie_id, document_id=document_id) == "geboekt"
        assert _status(admin_engine, document_id) == "geboekt" and len(fake.puts) == 1
        # Idempotent: een tweede taak (trigger + scheduler) doet niets meer — één RLZ-document.
        assert boek_wachtrij.verwerk_boek_taak(administratie_id=administratie_id, document_id=document_id) == "overgeslagen"
        assert len(fake.puts) == 1
        with admin_engine.connect() as conn:
            claim = conn.execute(
                text("SELECT uitkomst, verwerker FROM boekhouding.boek_wachtrij_claim WHERE sleutel = :s"),
                {"s": ingediend.sleutel},
            ).one()
            detail = conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id AND naar_status = 'geboekt'"
                ),
                {"id": document_id},
            ).scalar_one()
        assert claim.uitkomst == "geboekt"
        assert detail.get("via_boek_wachtrij") == ingediend.sleutel

    def test_worker_zet_boeken_mislukt_zichtbaar_bij_rlz_fout_en_opnieuw_indienen_lukt(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        kapot = FakeBoekClient(faal_op="put")
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: kapot)
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda rlz_admin_id: kapot)
        document_id = _klaar(administratie_id, gescoopte_gebruiker, opslag, referentie="F-2")
        boek_wachtrij.dien_boeking_in(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker, wachtrij=_Verzamelaar()
        )
        assert boek_wachtrij.verwerk_boek_taak(administratie_id=administratie_id, document_id=document_id) == "mislukt"
        assert _status(admin_engine, document_id) == "boeken_mislukt"
        with admin_engine.connect() as conn:
            fout = conn.execute(
                text("SELECT detail->>'fout' FROM boekhouding.document_gebeurtenis WHERE document_id = :id AND naar_status = 'boeken_mislukt'"),
                {"id": document_id},
            ).scalar_one()
        assert "PUT mislukt" in fout
        # "Opnieuw": vanuit boeken_mislukt opnieuw indienen — zelfde boek_cyclus, dus dezelfde idempotency-key; een claim
        # mét uitkomst 'mislukt' blokkeert die retry niet (alleen 'geboekt' is definitief).
        goed = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: goed)
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda rlz_admin_id: goed)
        boek_wachtrij.dien_boeking_in(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker, wachtrij=_Verzamelaar()
        )
        assert _status(admin_engine, document_id) == "wordt_geboekt"
        assert boek_wachtrij.verwerk_boek_taak(administratie_id=administratie_id, document_id=document_id) == "geboekt"
        assert _status(admin_engine, document_id) == "geboekt" and len(goed.puts) == 1

    def test_geblokkeerde_checks_blijven_synchroon_409_waardig(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient()
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="leeg.pdf",
            inhoud=b"%PDF-1.4 leeg",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with pytest.raises(boeken.BoekenGeblokkeerdDoorChecks):
            boek_wachtrij.dien_boeking_in(
                administratie_id=administratie_id,
                document_id=resultaat.document_id,
                actor_id=gescoopte_gebruiker,
                wachtrij=_Verzamelaar(),
            )

    def test_herstel_vangnet_plant_verouderde_boekingen_opnieuw_in_en_reconciliatie_ziet_ze(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        document_id = _klaar(administratie_id, gescoopte_gebruiker, opslag, referentie="F-3")
        boek_wachtrij.dien_boeking_in(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker, wachtrij=_Verzamelaar()
        )
        # Vers ingediend = niets te herstellen, geen bevinding.
        assert boek_wachtrij.herstel_achtergebleven_boekingen(wachtrij=_Verzamelaar()) == 0
        assert boek_wachtrij.verouderde_boekingen() == []
        # Maak 'm ouder dan de herstelgrens (gestrande verwerker).
        oud = datetime.now(UTC) - timedelta(minutes=settings.boek_wachtrij_herstel_minuten + 1)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.document_gebeurtenis SET tijdstip = :t WHERE document_id = :id AND naar_status = 'wordt_geboekt'"),
                {"t": oud, "id": document_id},
            )
        verouderd = boek_wachtrij.verouderde_boekingen()
        assert [(a, d) for a, d, _ in verouderd] == [(administratie_id, document_id)]
        wachtrij = _Verzamelaar()
        assert boek_wachtrij.herstel_achtergebleven_boekingen(wachtrij=wachtrij) == 1
        assert wachtrij.items == [(administratie_id, document_id)]
        # De job-verwerker rondt 'm af.
        assert boek_wachtrij.verwerk_boek_wachtrij(verwerker="test-job") == 1
        assert _status(admin_engine, document_id) == "geboekt"

    def test_gestrande_claim_wordt_na_de_grens_hervat(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        document_id = _klaar(administratie_id, gescoopte_gebruiker, opslag, referentie="F-4")
        ingediend = boek_wachtrij.dien_boeking_in(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker, wachtrij=_Verzamelaar()
        )
        # Een andere verwerker claimde net (en is nog bezig): de tweede taak slaat over.
        claim = boek_wachtrij._claim(
            administratie_id=administratie_id, document_id=document_id, boek_cyclus=0, verwerker="ander"
        )
        assert claim is not None
        assert boek_wachtrij.verwerk_boek_taak(administratie_id=administratie_id, document_id=document_id) == "overgeslagen"
        assert fake.puts == []
        # Diezelfde claim is gestrand (ouder dan de grens, niet afgerond) → hervatten mag.
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.boek_wachtrij_claim SET geclaimd_op = :t WHERE sleutel = :s"),
                {"t": datetime.now(UTC) - timedelta(minutes=settings.boek_wachtrij_herstel_minuten + 1), "s": ingediend.sleutel},
            )
        assert boek_wachtrij.verwerk_boek_taak(administratie_id=administratie_id, document_id=document_id) == "geboekt"
        assert len(fake.puts) == 1


class TestVolgendDocument:
    def test_volgorde_positioneel_cyclisch_alleen_verwerkbaar(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, admin_engine: Engine
    ) -> None:
        a = _klaar(administratie_id, gescoopte_gebruiker, opslag, referentie="A")
        b = _klaar(administratie_id, gescoopte_gebruiker, opslag, referentie="B")
        c = _klaar(administratie_id, gescoopte_gebruiker, opslag, referentie="C")
        # `b` ligt bij de klant (vraag_open) → niet verwerkbaar voor de doorloop (VERWERKBARE_STATUSSEN).
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET status = 'vraag_open' WHERE id = :id"), {"id": b})
        # Ná a komt b (niet verwerkbaar) → c.
        assert boek_wachtrij.kies_volgend_document(administratie_id=administratie_id, huidig_id=a, volgorde=[a, b, c]) == (
            c,
            "inkoopfactuur",
        )
        # Cyclisch: ná c terug naar a.
        assert boek_wachtrij.kies_volgend_document(administratie_id=administratie_id, huidig_id=c, volgorde=[a, b, c])[0] == a
        # Alleen het huidige is verwerkbaar → None.
        assert boek_wachtrij.kies_volgend_document(administratie_id=administratie_id, huidig_id=a, volgorde=[a, b]) is None
        # Zonder volgorde: de backend-lijstvolgorde (nieuwste eerst); het eerstvolgende verwerkbare document ná `c` in die
        # volgorde (cyclisch, `b` telt niet) is `a` — ongeacht hoe de aangemaakt_op-tijdstippen precies vallen.
        uitkomst = boek_wachtrij.kies_volgend_document(administratie_id=administratie_id, huidig_id=c, volgorde=None)
        assert uitkomst is not None and uitkomst[0] == a

    def test_verwerkbare_statussen_zijn_gelijk_aan_de_frontend(self) -> None:
        ts = Path(__file__).resolve().parents[3] / "frontend" / "src" / "werkvoorraad" / "volgendDocument.ts"
        bron = ts.read_text()
        m = re.search(r"VERWERKBARE_STATUSSEN = new Set\(\[(.*?)\]\)", bron, re.S)
        assert m, "VERWERKBARE_STATUSSEN niet gevonden in volgendDocument.ts"
        frontend = {x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()}
        assert frontend == {s.value for s in boek_wachtrij.VERWERKBARE_STATUSSEN}


def test_statusmachine_wordt_geboekt() -> None:
    assert DocumentStatus.WORDT_GEBOEKT in _TOEGESTANE_OVERGANGEN[DocumentStatus.KLAAR_OM_TE_BOEKEN]
    assert DocumentStatus.WORDT_GEBOEKT in _TOEGESTANE_OVERGANGEN[DocumentStatus.BOEKEN_MISLUKT]
    assert _TOEGESTANE_OVERGANGEN[DocumentStatus.WORDT_GEBOEKT] == frozenset(
        {DocumentStatus.GEBOEKT, DocumentStatus.BOEKEN_MISLUKT}
    )
    # Niet bewerkbaar, niet verwijderbaar, niet nog eens te boeken vanuit de UI.
    assert DocumentStatus.VERWIJDERD not in _TOEGESTANE_OVERGANGEN[DocumentStatus.WORDT_GEBOEKT]


class TestNietsStil21_09:
    """BUG 21-09 (rlz-boek-wachtrij zonder `--command python`: drie dagen 'Wordt geboekt…' zonder signaal): de trigger-
    uitkomst staat op de tijdlijn, 'Opnieuw indienen' start de verwerker opnieuw zonder dubbel te boeken, en een boeking
    > herstelgrens is een regressie-LET-OP (blok automatisering) + een 'fout' van de kwartier-probe."""

    def _hangend(self, administratie_id, actor, opslag, admin_engine, monkeypatch, *, referentie: str) -> uuid.UUID:
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        document_id = _klaar(administratie_id, actor, opslag, referentie=referentie)
        boek_wachtrij.dien_boeking_in(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor, wachtrij=_Verzamelaar()
        )
        oud = datetime.now(UTC) - timedelta(minutes=settings.boek_wachtrij_herstel_minuten + 3)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.document_gebeurtenis SET tijdstip = :t WHERE document_id = :id AND naar_status = 'wordt_geboekt'"),
                {"t": oud, "id": document_id},
            )
        return document_id

    def test_mislukte_trigger_staat_op_de_tijdlijn_en_in_het_audit(
        self, gescoopte_gebruiker, administratie_id, opslag, admin_engine, boeken_aan, monkeypatch
    ) -> None:
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        document_id = _klaar(administratie_id, gescoopte_gebruiker, opslag, referentie="F-21a")

        def _kapot(resource: str) -> None:
            raise PermissionError("403 run.jobs.run ontbreekt op rlz-boek-wachtrij")

        cloud = boek_wachtrij.CloudRunJobBoekWachtrij(
            job_resource="projects/p/locations/l/jobs/rlz-boek-wachtrij", trigger=_kapot
        )
        boek_wachtrij.dien_boeking_in(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker, wachtrij=cloud
        )
        trigger = boek_wachtrij.laatste_trigger(administratie_id, document_id)
        assert trigger is not None and trigger["uitkomst"] == "mislukt"
        assert "403 run.jobs.run" in trigger["fout"] and trigger["job"] == "rlz-boek-wachtrij"
        with admin_engine.connect() as conn:
            redenen = conn.execute(
                text(
                    "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                    "AND van_status = 'wordt_geboekt' AND naar_status = 'wordt_geboekt' ORDER BY tijdstip"
                ), {"id": document_id},
            ).scalars().all()
        assert len(redenen) == 1 and "starten mislukt (job rlz-boek-wachtrij): PermissionError: 403" in redenen[0]
        assert "Opnieuw indienen" in redenen[0]
        # Geslaagde trigger = alleen audit, geen tijdlijnregel (geen ruis).
        ok = boek_wachtrij.CloudRunJobBoekWachtrij(job_resource="projects/p/locations/l/jobs/rlz-boek-wachtrij", trigger=lambda r: None)
        assert ok.enqueue(administratie_id=administratie_id, document_id=document_id) is None
        assert boek_wachtrij.laatste_trigger(administratie_id, document_id)["uitkomst"] == "geslaagd"
        with admin_engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM boekhouding.document_gebeurtenis WHERE document_id = :id AND van_status = 'wordt_geboekt' AND naar_status = 'wordt_geboekt'"),
                {"id": document_id},
            ).scalar_one()
        assert n == 1

    def test_opnieuw_indienen_start_de_verwerker_zonder_dubbel_te_boeken(
        self, gescoopte_gebruiker, administratie_id, opslag, admin_engine, boeken_aan, monkeypatch
    ) -> None:
        document_id = self._hangend(administratie_id, gescoopte_gebruiker, opslag, admin_engine, monkeypatch, referentie="F-21b")
        wachtrij = _Verzamelaar()
        uit = boek_wachtrij.dien_opnieuw_in(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker, wachtrij=wachtrij
        )
        assert uit.trigger_uitkomst == "lokaal" and uit.sleutel == boek_wachtrij.sleutel(document_id, 0)
        assert wachtrij.items == [(administratie_id, document_id)]
        assert _status(admin_engine, document_id) == "wordt_geboekt"
        with admin_engine.connect() as conn:
            reden = conn.execute(
                text("SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis WHERE document_id = :id AND detail ? 'boek_wachtrij_opnieuw'"),
                {"id": document_id},
            ).scalar_one()
            audits = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE record_id = :id AND actie = 'boek_wachtrij_opnieuw_ingediend'"),
                {"id": document_id},
            ).scalar_one()
        assert "Opnieuw ingediend" in reden and audits == 1
        # Cloud-wachtrij mét kapotte trigger: de fout gaat direct terug naar de mens.
        cloud = boek_wachtrij.CloudRunJobBoekWachtrij(
            job_resource="projects/p/locations/l/jobs/rlz-boek-wachtrij",
            trigger=lambda r: (_ for _ in ()).throw(RuntimeError("job start niet")),
        )
        uit2 = boek_wachtrij.dien_opnieuw_in(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker, wachtrij=cloud
        )
        assert uit2.trigger_uitkomst == "mislukt" and "job start niet" in (uit2.trigger_fout or "")
        #  De tijdlijnregels (van = naar = wordt_geboekt) verschuiven het indienmoment niet en verbergen de indiening
        # niet.
        with admin_engine.connect() as conn, scoped_session(administratie_id) as session:
            detail = boek_wachtrij._wachtrij_detail(session, document_id)
        assert detail.get("actor_id") == str(gescoopte_gebruiker)
        assert [d for _, d, _ in boek_wachtrij.verouderde_boekingen()] == [document_id]
        # De verwerker rondt 'm daarna precies één keer af (zelfde sleutel/claim).
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        assert boek_wachtrij.verwerk_boek_wachtrij(verwerker="test-job") == 1
        assert _status(admin_engine, document_id) == "geboekt" and len(fake.puts) == 1
        # Niet meer op wordt_geboekt = 409-waardig, nooit stil opnieuw.
        with pytest.raises(boeken.OngeldigeBoekpoging):
            boek_wachtrij.dien_opnieuw_in(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
                wachtrij=_Verzamelaar()
            )

    def test_gestrande_boeking_is_regressie_let_op_met_trigger_reden_en_probe_fout(
        self, gescoopte_gebruiker, administratie_id, opslag, admin_engine, boeken_aan, monkeypatch
    ) -> None:
        from app.bewaking import service as bewaking
        from app.reconciliatie import automatiseringen as auto
        from app.reconciliatie.run import Bevinding, BevindingSoort, is_beheer_signaal, is_regressie

        assert bewaking._probe_boek_wachtrij_gestrand(datetime.now(UTC)).status == "ok"
        document_id = self._hangend(administratie_id, gescoopte_gebruiker, opslag, admin_engine, monkeypatch, referentie="F-21c")
        # Trigger-spoor "geslaagd" (zoals in productie 18→21-09: run.jobs.run lukte, de executie startte niet).
        ok = boek_wachtrij.CloudRunJobBoekWachtrij(job_resource="projects/p/locations/l/jobs/rlz-boek-wachtrij", trigger=lambda r: None)
        ok.enqueue(administratie_id=administratie_id, document_id=document_id)

        gestrand = boek_wachtrij.gestrande_boekingen()
        assert [(g.administratie_id, g.document_id) for g in gestrand] == [(administratie_id, document_id)]
        assert gestrand[0].minuten >= settings.boek_wachtrij_herstel_minuten and gestrand[0].trigger_uitkomst == "geslaagd"

        kws = auto.boek_wachtrij_gestrand_bevindingen(nu=datetime.now(UTC))
        assert len(kws) == 1
        kw = kws[0]
        assert kw["soort"] == "let_op" and kw["blok"] == auto.BLOK and kw["administratie_id"] == administratie_id
        assert kw["detail"]["reden"] == auto.BOEK_WACHTRIJ_GESTRAND
        assert kw["detail"]["afwijking_soort"] == "wordt_geboekt_verouderd"
        assert kw["detail"]["document_id"] == str(document_id)
        assert kw["detail"]["doel_pad"] == f"/?administratie={administratie_id}&document={document_id}"
        assert "trigger geslaagd maar de job rondde de boeking niet af" in kw["tekst"]
        assert auto.REGRESSIE_TEKST in kw["tekst"]
        b = Bevinding(
            blok=kw["blok"], soort=BevindingSoort.LET_OP, administratie_id=kw["administratie_id"],
            vingerafdruk=kw["vingerafdruk"], tekst=kw["tekst"], detail=kw["detail"],
        )
        assert is_regressie(b) and is_beheer_signaal(b)
        # Vingerafdruk stabiel per document × indienmoment (één mail per hangende boeking).
        assert auto.boek_wachtrij_gestrand_bevindingen(nu=datetime.now(UTC) + timedelta(minutes=5))[0]["vingerafdruk"] == kw["vingerafdruk"]

        # Mét een mislukte trigger draagt de tekst de letterlijke fout.
        kapot = boek_wachtrij.CloudRunJobBoekWachtrij(
            job_resource="projects/p/locations/l/jobs/rlz-boek-wachtrij",
            trigger=lambda r: (_ for _ in ()).throw(PermissionError("403 invoker")),
        )
        kapot.enqueue(administratie_id=administratie_id, document_id=document_id)
        kw2 = auto.boek_wachtrij_gestrand_bevindingen(nu=datetime.now(UTC))[0]
        assert "trigger mislukt: PermissionError: 403 invoker" in kw2["tekst"]
        assert kw2["detail"]["trigger_fout"].startswith("PermissionError: 403 invoker")

        probe = bewaking._probe_boek_wachtrij_gestrand(datetime.now(UTC))
        assert probe.status == "fout" and str(document_id) in (probe.detail or "")
        assert "403 invoker" in (probe.detail or "")

        # De verwerker rondt af → geen bevinding, probe ok.
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        assert boek_wachtrij.verwerk_boek_wachtrij(verwerker="test-job") == 1
        assert auto.boek_wachtrij_gestrand_bevindingen(nu=datetime.now(UTC)) == []
        assert bewaking._probe_boek_wachtrij_gestrand(datetime.now(UTC)).status == "ok"
