"""Projectcijfers-sync als achtergrondrun (fix 504-crash 2026-08-23): de gepagineerde,
geheugen-begrensde aanvoer (per documenttype en per RLZ-pagina), de leesfout-herkansing
mét verdwenen-bescherming (een onleesbaar document markeert zijn cache-rijen nooit als
verdwenen) en de run-levensloop (wachtrij → bezig → klaar/fout, heartbeat/stale,
dubbelklik = zelfde run). De rekenlaag zelf is bewust ongewijzigd — die tests staan in
test_kantoor_module.py."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.projecten import cijfers, cijfers_run
from app.rlz.client import RlzApiError
from tests.projecten.conftest import administratie_id, beheerder_id  # noqa: F401

PAGINA = cijfers._PAGINA_GROOTTE


def _doc(doc_id: uuid.UUID, *, datum: str = "2026-08-01", status: int = 2, referentie: str = "F-1") -> dict:
    return {"id": str(doc_id), "Date": datum, "Status": status, "Reference": referentie}


def _line(project_id: uuid.UUID, *, netto: str = "100.00") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "Project": {"id": str(project_id)},
        "Account": {"id": str(uuid.uuid4())},
        "NetAmount": netto,
        "TaxAmount": "21.00",
        "Description": "regel",
    }


class FakeCijfersClient:
    """Simuleert de RLZ-leesroutes van de sync: server-side paginering op de collecties
    ($top/$skip) + /Lines per document; `faal_lines` telt af per document-GUID zodat de
    herkansing (tweede poging) testbaar is."""

    def __init__(self) -> None:
        self.documenten: dict[str, list[dict]] = {"PurchaseInvoices": [], "SalesInvoices": []}
        self.lines: dict[str, list[dict]] = {}
        self.faal_lines: dict[str, int] = {}  # doc-id → aantal keren dat /Lines nog faalt
        self.collectie_params: list[dict] = []
        self.gesloten = False

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        assert path in self.documenten, f"onverwachte GET {path}"
        self.collectie_params.append({"collectie": path, **(params or {})})
        skip = int((params or {}).get("$skip", 0))
        top = int((params or {}).get("$top", PAGINA))
        return {"value": self.documenten[path][skip : skip + top]}

    def get_lines(self, entity_path: str, entity_id: uuid.UUID | str, *, expand: str = "") -> list[dict]:
        sleutel = str(entity_id)
        if self.faal_lines.get(sleutel, 0) > 0:
            self.faal_lines[sleutel] -= 1
            raise RlzApiError(403, "GET", f"/{entity_path}/{sleutel}/Lines", "<HTML>rate limited</HTML>")
        return self.lines.get(sleutel, [])

    def close(self) -> None:
        self.gesloten = True


def _cache_rijen(admin_engine: Engine, administratie_id: uuid.UUID) -> list:  # noqa: F811
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT id, rlz_document_id, verdwenen_uit_bron_op FROM boekhouding.project_regel_cache "
                "WHERE administratie_id = :aid"
            ),
            {"aid": administratie_id},
        ).all()


class TestGepagineerdeAanvoer:
    def test_verwerkt_alle_paginas_per_documenttype(
        self, admin_engine: Engine, administratie_id: uuid.UUID  # noqa: F811
    ) -> None:
        """Meer documenten dan één RLZ-pagina: álles wordt verwerkt en de aanvoer vraagt de
        collectie per pagina op ($skip loopt) — nooit meer één volledige collectie in één
        lijst (de 504-crash van 23-08)."""
        fake = FakeCijfersClient()
        project_id = uuid.uuid4()
        for _ in range(PAGINA + 5):
            doc_id = uuid.uuid4()
            fake.documenten["PurchaseInvoices"].append(_doc(doc_id))
            fake.lines[str(doc_id)] = [_line(project_id)]
        teller = cijfers.sync_project_regels(administratie_id=administratie_id, client=fake)
        assert teller["documenten"] == PAGINA + 5
        assert teller["regels"] == PAGINA + 5
        assert teller["leesfouten"] == 0
        skips = [p["$skip"] for p in fake.collectie_params if p["collectie"] == "PurchaseInvoices"]
        assert skips == ["0", str(PAGINA)]
        assert len(_cache_rijen(admin_engine, administratie_id)) == PAGINA + 5

    def test_concept_documenten_tellen_niet_mee(
        self, admin_engine: Engine, administratie_id: uuid.UUID  # noqa: F811
    ) -> None:
        fake = FakeCijfersClient()
        doc_id = uuid.uuid4()
        fake.documenten["SalesInvoices"].append(_doc(doc_id, status=1))
        fake.lines[str(doc_id)] = [_line(uuid.uuid4())]
        teller = cijfers.sync_project_regels(administratie_id=administratie_id, client=fake)
        assert teller["documenten"] == 0
        assert _cache_rijen(admin_engine, administratie_id) == []

    def test_voortgang_callback_per_pagina(self, administratie_id: uuid.UUID) -> None:  # noqa: F811
        fake = FakeCijfersClient()
        project_id = uuid.uuid4()
        for _ in range(3):
            doc_id = uuid.uuid4()
            fake.documenten["PurchaseInvoices"].append(_doc(doc_id))
            fake.lines[str(doc_id)] = [_line(project_id)]
        heartbeats: list[dict] = []
        cijfers.sync_project_regels(administratie_id=administratie_id, client=fake, voortgang=heartbeats.append)
        assert heartbeats  # minstens één heartbeat (per niet-lege pagina)
        assert heartbeats[-1]["documenten"] == 3


class TestVerkoopmoduleAfwezig:
    def test_slaat_salesinvoices_over_en_markeert_verkoop_niet_als_verdwenen(
        self, admin_engine: Engine, administratie_id: uuid.UUID  # noqa: F811
    ) -> None:
        """Facturatiemodule niet afgenomen (01-09): de SalesInvoices-collectie geeft daar altijd
        403 — de sync slaat de verkoopkant zichtbaar over (teller verkoop_overgeslagen), leest de
        inkoopkant gewoon, en markeert bestaande verkoop-cache-rijen nooit als verdwenen (de bron
        is bewust niet geraadpleegd, niet leeg)."""
        fake = FakeCijfersClient()
        project_id = uuid.uuid4()
        inkoop_id = uuid.uuid4()
        fake.documenten["PurchaseInvoices"] = [_doc(inkoop_id)]
        fake.lines[str(inkoop_id)] = [_line(project_id)]

        # Eerst een gewone run mét verkoopkant → er staat een verkoop-cache-rij.
        verkoop_id = uuid.uuid4()
        fake.documenten["SalesInvoices"] = [_doc(verkoop_id, referentie="V-1")]
        fake.lines[str(verkoop_id)] = [_line(project_id)]
        cijfers.sync_project_regels(administratie_id=administratie_id, client=fake)
        assert len(_cache_rijen(admin_engine, administratie_id)) == 2

        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET verkoopmodule_afwezig = true WHERE id = :id"),
                {"id": administratie_id},
            )
        fake.collectie_params.clear()
        teller = cijfers.sync_project_regels(administratie_id=administratie_id, client=fake)
        assert teller["verkoop_overgeslagen"] == 1
        assert all(p["collectie"] == "PurchaseInvoices" for p in fake.collectie_params)
        rijen = _cache_rijen(admin_engine, administratie_id)
        # Beide rijen (inkoop én verkoop) staan er nog en niets is als verdwenen gemarkeerd.
        assert len(rijen) == 2 and all(r.verdwenen_uit_bron_op is None for r in rijen)


class TestLeesfouten:
    def test_herkansing_herstelt_tijdelijke_leesfout(
        self, admin_engine: Engine, administratie_id: uuid.UUID  # noqa: F811
    ) -> None:
        """De 403-storm van 23-08 was tijdelijk: één herkansing aan het einde van de run
        haalt het document alsnog binnen — geen leesfout, rijen gewoon geschreven."""
        fake = FakeCijfersClient()
        doc_id = uuid.uuid4()
        fake.documenten["PurchaseInvoices"].append(_doc(doc_id))
        fake.lines[str(doc_id)] = [_line(uuid.uuid4())]
        fake.faal_lines[str(doc_id)] = 1  # eerste poging faalt, herkansing slaagt
        teller = cijfers.sync_project_regels(administratie_id=administratie_id, client=fake)
        assert teller["leesfouten"] == 0
        assert teller["regels"] == 1

    def test_blijvende_leesfout_markeert_rijen_niet_als_verdwenen(
        self, admin_engine: Engine, administratie_id: uuid.UUID  # noqa: F811
    ) -> None:
        """Verdwenen-markering onverkort maar nooit vals: een document waarvan RLZ de regels
        niet gaf is ONLEESBAAR, niet leeg — zijn bestaande cache-rijen blijven staan
        (leesfout zichtbaar in de teller); een document dat écht uit de bron verdween wordt
        wél gemarkeerd."""
        fake = FakeCijfersClient()
        onleesbaar_doc = uuid.uuid4()
        fake.documenten["PurchaseInvoices"].append(_doc(onleesbaar_doc))
        fake.faal_lines[str(onleesbaar_doc)] = 99  # faalt óók bij de herkansing
        echt_verdwenen_doc = uuid.uuid4()  # staat niet in de listing
        with admin_engine.begin() as conn:
            for doc in (onleesbaar_doc, echt_verdwenen_doc):
                conn.execute(
                    text(
                        "INSERT INTO boekhouding.project_regel_cache "
                        "(id, administratie_id, rlz_document_id, soort, project_id, netto_bedrag, datum) "
                        "VALUES (:id, :aid, :doc, 'inkoop', :pid, 50, '2026-08-01')"
                    ),
                    {"id": uuid.uuid4(), "aid": administratie_id, "doc": doc, "pid": uuid.uuid4()},
                )
        teller = cijfers.sync_project_regels(administratie_id=administratie_id, client=fake)
        assert teller["leesfouten"] == 1
        rijen = _cache_rijen(admin_engine, administratie_id)
        per_doc = {rij.rlz_document_id: rij.verdwenen_uit_bron_op for rij in rijen}
        assert per_doc[onleesbaar_doc] is None  # onleesbaar ≠ verdwenen
        assert per_doc[echt_verdwenen_doc] is not None  # écht weg = gemarkeerd


class TestAchtergrondrun:
    @pytest.fixture
    def zonder_voertuig(self, monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
        """start_achtergrondrun zonder échte thread/job: de gestarte administraties worden
        alleen geregistreerd — de verwerking roepen de tests zelf expliciet aan."""
        gestart: list[uuid.UUID] = []
        monkeypatch.setattr(cijfers_run, "_start_voertuig", gestart.append)
        return gestart

    def test_levensloop_wachtrij_bezig_klaar(
        self,
        administratie_id: uuid.UUID,  # noqa: F811
        beheerder_id: uuid.UUID,  # noqa: F811
        zonder_voertuig: list[uuid.UUID],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        run = cijfers_run.start_achtergrondrun(administratie_id=administratie_id, actor_id=beheerder_id)
        assert run.status == "wachtrij"
        assert zonder_voertuig == [administratie_id]
        monkeypatch.setattr(
            cijfers_run,
            "sync_project_regels",
            lambda **kw: {"documenten": 7, "regels": 12, "verdwenen": 1, "leesfouten": 0},
        )
        verwerkt = cijfers_run.verwerk_wachtrij_voor(administratie_id)
        assert verwerkt is not None and verwerkt.status == "klaar"
        status = cijfers_run.laatste_run(administratie_id)
        assert status is not None
        assert (status.status, status.documenten, status.regels, status.verdwenen) == ("klaar", 7, 12, 1)
        assert status.beeindigd_op is not None

    def test_fout_is_zichtbaar_nooit_stil(
        self,
        administratie_id: uuid.UUID,  # noqa: F811
        beheerder_id: uuid.UUID,  # noqa: F811
        zonder_voertuig: list[uuid.UUID],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cijfers_run.start_achtergrondrun(administratie_id=administratie_id, actor_id=beheerder_id)

        def _kapot(**kw: object) -> dict:
            raise RlzApiError(502, "GET", "/PurchaseInvoices", "RLZ plat")

        monkeypatch.setattr(cijfers_run, "sync_project_regels", _kapot)
        cijfers_run.verwerk_wachtrij_voor(administratie_id)
        status = cijfers_run.laatste_run(administratie_id)
        assert status is not None and status.status == "fout"
        assert status.fout_reden and "RLZ" in status.fout_reden

    def test_dubbelklik_hergebruikt_actieve_run(
        self,
        administratie_id: uuid.UUID,  # noqa: F811
        beheerder_id: uuid.UUID,  # noqa: F811
        zonder_voertuig: list[uuid.UUID],
    ) -> None:
        eerste = cijfers_run.start_achtergrondrun(administratie_id=administratie_id, actor_id=beheerder_id)
        tweede = cijfers_run.start_achtergrondrun(administratie_id=administratie_id, actor_id=beheerder_id)
        assert eerste.run_id == tweede.run_id  # nooit twee RLZ-rondes tegelijk

    def test_stale_bezig_run_telt_als_afgebroken_en_blokkeert_niet(
        self,
        admin_engine: Engine,
        administratie_id: uuid.UUID,  # noqa: F811
        beheerder_id: uuid.UUID,  # noqa: F811
        zonder_voertuig: list[uuid.UUID],
    ) -> None:
        oud = datetime.now(UTC) - cijfers_run.STALE_NA - timedelta(minutes=1)
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.project_cijfers_sync_run "
                    "(id, administratie_id, status, aangevraagd_op, gestart_op, laatst_actief_op) "
                    "VALUES (:id, :aid, 'bezig', :oud, :oud, :oud)"
                ),
                {"id": uuid.uuid4(), "aid": administratie_id, "oud": oud},
            )
        status = cijfers_run.laatste_run(administratie_id)
        assert status is not None and status.status == "fout"
        assert status.fout_reden == cijfers_run.AFGEBROKEN_REDEN
        nieuwe = cijfers_run.start_achtergrondrun(administratie_id=administratie_id, actor_id=beheerder_id)
        assert nieuwe.status == "wachtrij"  # de stale run blokkeert geen nieuwe

    def test_voertuigfout_zet_run_zichtbaar_op_fout(
        self,
        administratie_id: uuid.UUID,  # noqa: F811
        beheerder_id: uuid.UUID,  # noqa: F811
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _kapot_voertuig(_aid: uuid.UUID) -> None:
            raise RuntimeError("job-trigger 403")

        monkeypatch.setattr(cijfers_run, "_start_voertuig", _kapot_voertuig)
        with pytest.raises(cijfers_run.CijfersSyncStartFout):
            cijfers_run.start_achtergrondrun(administratie_id=administratie_id, actor_id=beheerder_id)
        status = cijfers_run.laatste_run(administratie_id)
        assert status is not None and status.status == "fout"
        assert "job-trigger 403" in (status.fout_reden or "")
