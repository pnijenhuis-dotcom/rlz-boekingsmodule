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
