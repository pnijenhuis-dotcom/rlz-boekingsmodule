"""Projectspecifieke prijsafspraken per veldwerker (steigerbouw-run B1, 25-08 — mockup
projecten-invoer "Prijsafspraken veldwerkers"): CRUD (schrijfrol, overlap, intrekken, audit) én
de tariefresolutie in de factuurmatch — projectafspraak wint → koppeling-tarief → onbepaalbaar;
eenheid m² rekent met goedgekeurde weekstaat-m²; geldt óók voor bureaufacturen; de match-details
dragen altijd de gebruikte tariefbron. GELDLOGICA — uitgebreid getest."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.projecten import kantoor
from app.security.tokens import create_access_token
from app.uren import factuurmatch, service
from app.uren.models import ProjectPrijsafspraak
from tests.uren.conftest import maak_gebruiker, maak_project
from tests.uren.test_factuurmatch import koppel_crediteur, maak_factuur, zet_bureau_tarief

client = TestClient(app)
JAAR = 2026
FACTUURDATUM = date(2026, 8, 7)  # ISO-week 32


@pytest.fixture
def opslag(tmp_path: Path) -> LokaleBestandsopslag:
    return LokaleBestandsopslag(tmp_path / "documenten")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def staat_met_m2(administratie_id, zzper, project_id, uitvoerder, *, week: int, dagen: tuple[tuple[str, str | None], ...]):
    """Goedgekeurde staat mét (uren, m²) per dag."""
    maandag = date.fromisocalendar(JAAR, week, 1)
    for i, (uren, m2) in enumerate(dagen):
        service.zet_dag(
            administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=week,
            datum=maandag + timedelta(days=i), uren=Decimal(uren), m2=Decimal(m2) if m2 is not None else None, actor_id=zzper,
        )
    staat = service.dien_week_in(administratie_id=administratie_id, zzper_id=zzper, project_id=project_id, jaar=JAAR, weeknummer=week, actor_id=zzper)
    service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=uitvoerder)
    return staat.id


def _afspraak(administratie_id, project_id, zzper, actor, **kw):
    return kantoor.voeg_prijsafspraak_toe(administratie_id=administratie_id, project_id=project_id, actor_id=actor, gebruiker_id=zzper, **kw)


def _audit(admin_engine: Engine, record_id: uuid.UUID) -> list[str]:
    with admin_engine.begin() as conn:
        return [r[0] for r in conn.execute(text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"), {"id": record_id})]


class TestBeheer:
    def test_schrijfrol_en_validatie(self, administratie_id, project_id, gekoppelde_zzper, beheerder_id, admin_engine):
        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        with pytest.raises(kantoor.GeenSchrijfrecht):
            _afspraak(administratie_id, project_id, gekoppelde_zzper, boekhouder, eenheid="uur", tarief=Decimal("50"))
        with pytest.raises(kantoor.OngeldigeInvoer):
            _afspraak(administratie_id, project_id, gekoppelde_zzper, beheerder_id, eenheid="stuks", tarief=Decimal("50"))
        with pytest.raises(kantoor.OngeldigeInvoer):
            _afspraak(administratie_id, project_id, gekoppelde_zzper, beheerder_id, eenheid="uur", tarief=Decimal("-1"))
        with pytest.raises(kantoor.OngeldigeInvoer):
            _afspraak(administratie_id, project_id, gekoppelde_zzper, beheerder_id, eenheid="uur", tarief=Decimal("50"), geldig_vanaf=(2026, 40), geldig_tm=(2026, 30))
        uitvoerder = maak_gebruiker(admin_engine, "uitvoerder", "Ben")
        with pytest.raises(kantoor.OngeldigeInvoer):
            _afspraak(administratie_id, project_id, uitvoerder, beheerder_id, eenheid="uur", tarief=Decimal("50"))
        bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Anne P.")
        aid = _afspraak(administratie_id, project_id, gekoppelde_zzper, bp, eenheid="m2", tarief=Decimal("3.85"))
        assert "project_prijsafspraak_toegevoegd" in _audit(admin_engine, aid)

    def test_overlap_geweigerd_en_intrekken(self, administratie_id, project_id, gekoppelde_zzper, beheerder_id, admin_engine):
        a1 = _afspraak(administratie_id, project_id, gekoppelde_zzper, beheerder_id, eenheid="uur", tarief=Decimal("54"), geldig_tm=(2026, 40))
        # overlap: hele project vs t/m wk 40 → weigert; vanaf wk 41 → mag
        with pytest.raises(kantoor.OngeldigeInvoer):
            _afspraak(administratie_id, project_id, gekoppelde_zzper, beheerder_id, eenheid="uur", tarief=Decimal("55"))
        with pytest.raises(kantoor.OngeldigeInvoer):
            _afspraak(administratie_id, project_id, gekoppelde_zzper, beheerder_id, eenheid="uur", tarief=Decimal("55"), geldig_vanaf=(2026, 38), geldig_tm=(2026, 45))
        a2 = _afspraak(administratie_id, project_id, gekoppelde_zzper, beheerder_id, eenheid="m2", tarief=Decimal("4"), geldig_vanaf=(2026, 41))
        with pytest.raises(kantoor.OngeldigeInvoer):
            kantoor.trek_prijsafspraak_in(administratie_id=administratie_id, afspraak_id=a1, actor_id=beheerder_id, reden=" ")
        kantoor.trek_prijsafspraak_in(administratie_id=administratie_id, afspraak_id=a1, actor_id=beheerder_id, reden="Nieuw tarief afgesproken")
        kantoor.trek_prijsafspraak_in(administratie_id=administratie_id, afspraak_id=a1, actor_id=beheerder_id, reden="nogmaals")  # idempotent
        # Ná intrekken mag het venster weer gevuld worden.
        _afspraak(administratie_id, project_id, gekoppelde_zzper, beheerder_id, eenheid="uur", tarief=Decimal("56"), geldig_tm=(2026, 40))
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        per_id = {a.id: a for a in detail.prijsafspraken}
        assert per_id[a1].ingetrokken_op is not None and per_id[a1].ingetrokken_reden == "Nieuw tarief afgesproken"
        assert per_id[a2].ingetrokken_op is None and per_id[a2].eenheid == "m2"
        assert [v.gebruiker_id for v in detail.veldwerkers] == [gekoppelde_zzper]
        assert _audit(admin_engine, a1).count("project_prijsafspraak_ingetrokken") == 1

    def test_api_poorten(self, administratie_id, project_id, gekoppelde_zzper, beheerder_id, admin_engine):
        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=boekhouder, administratie_id=administratie_id)
        body = {"gebruiker_id": str(gekoppelde_zzper), "eenheid": "uur", "tarief": "54.00", "geldig_tm_jaar": 2026, "geldig_tm_week": 40}
        resp = client.post(f"/projecten/{administratie_id}/{project_id}/prijsafspraken", json=body, headers=_bearer(boekhouder, rol="boekhouding"))
        assert resp.status_code == 403
        resp = client.post(f"/projecten/{administratie_id}/{project_id}/prijsafspraken", json={**body, "geldig_tm_week": None}, headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 422
        resp = client.post(f"/projecten/{administratie_id}/{project_id}/prijsafspraken", json=body, headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 201, resp.text
        aid = resp.json()["id"]
        resp = client.get(f"/projecten/{administratie_id}/{project_id}", headers=_bearer(boekhouder, rol="boekhouding"))
        assert resp.status_code == 200 and resp.json()["prijsafspraken"][0]["id"] == aid
        assert resp.json()["prijsafspraken"][0]["standaard_tarief"] is None
        resp = client.post(f"/projecten/{administratie_id}/prijsafspraken/{aid}/intrekken", json={"reden": "test"}, headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 204


class TestTariefresolutie:
    def test_pure_resolutie_venster_en_volgorde(self):
        pid, gid = uuid.uuid4(), uuid.uuid4()
        st = factuurmatch._StaatRegel(uuid.uuid4(), gid, pid, "144 Breda", 2026, 35, Decimal("40"), Decimal("120"))
        afspraak = ProjectPrijsafspraak(id=uuid.uuid4(), administratie_id=uuid.uuid4(), project_id=pid, gebruiker_id=gid, eenheid="m2", tarief=Decimal("3.85"), geldig_tm_jaar=2026, geldig_tm_week=40)
        g = factuurmatch.prijs_staat(st, afspraken=[afspraak], koppeling_tarief=Decimal("42.50"))
        assert g.tariefbron == "projectafspraak" and g.eenheid == "m2" and g.bedrag == Decimal("462.00")
        assert g.label == "projectafspraak 144 Breda · € 3.85/m²"
        # buiten het venster → koppeling-tarief (uur)
        st_laat = factuurmatch._StaatRegel(uuid.uuid4(), gid, pid, "144 Breda", 2026, 41, Decimal("40"), Decimal("0"))
        g2 = factuurmatch.prijs_staat(st_laat, afspraken=[afspraak], koppeling_tarief=Decimal("42.50"))
        assert g2.tariefbron == "koppeling" and g2.bedrag == Decimal("1700.00")
        # ander project → koppeling; geen koppeling-tarief → onbepaalbaar
        st_ander = factuurmatch._StaatRegel(uuid.uuid4(), gid, uuid.uuid4(), "X", 2026, 35, Decimal("8"), Decimal("0"))
        assert factuurmatch.prijs_staat(st_ander, afspraken=[afspraak], koppeling_tarief=None).tariefbron is None
        # ingetrokken afspraak geldt nooit; jaargrens: wk 52-2025 < wk 1-2026
        from datetime import UTC, datetime

        afspraak.ingetrokken_op = datetime.now(UTC)
        assert factuurmatch.prijs_staat(st, afspraken=[afspraak], koppeling_tarief=None).tariefbron is None
        a_vanaf = ProjectPrijsafspraak(id=uuid.uuid4(), administratie_id=uuid.uuid4(), project_id=pid, gebruiker_id=gid, eenheid="uur", tarief=Decimal("1"), geldig_vanaf_jaar=2026, geldig_vanaf_week=1)
        assert a_vanaf.geldt_in(2025, 52) is False and a_vanaf.geldt_in(2026, 1) is True

    def test_match_m2_afspraak_wint_van_koppeling(self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag):
        zzper, uitvoerder = gekoppelde_zzper, gekoppelde_uitvoerder
        vendor = uuid.uuid4()
        koppel_crediteur(administratie_id, zzper, vendor, beheerder_id, uurtarief="42.50")
        _afspraak(administratie_id, project_id, zzper, beheerder_id, eenheid="m2", tarief=Decimal("3.85"))
        # 16 uur, 120 m² → afspraak: 120 × 3,85 = 462,00 (koppeling zou 680,00 geven)
        staat_met_m2(administratie_id, zzper, project_id, uitvoerder, week=30, dagen=(("8", "70"), ("8", "50")))
        doc = maak_factuur(administratie_id, beheerder_id, opslag, vendor, nettos=("462.00",))
        m = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=doc, actor_id=beheerder_id)
        assert m is not None and m.uitkomst == "match" and m.staten_som_bedrag == Decimal("462.00")
        assert m.details["tariefbronnen"] == ["projectafspraak 26014 Eindhoven (BAM) · € 3.85/m²"]
        assert m.details["staten"][0]["eenheid"] == "m2" and m.details["staten"][0]["m2"] == "120.00"
        assert m.details["leden"][0]["bedrag"] == "462.00" and m.details["leden"][0]["uurtarief"] == "42.50"
        # Factuur op het koppeling-bedrag = afwijking (de projectafspraak wint, nooit beide).
        doc2 = maak_factuur(administratie_id, beheerder_id, opslag, vendor, nettos=("680.00",))
        m2 = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=doc2, actor_id=beheerder_id)
        assert m2.uitkomst == "afwijking" and m2.verschil_bedrag == Decimal("218.00")

    def test_match_per_week_gemengd_venster(self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag):
        zzper, uitvoerder = gekoppelde_zzper, gekoppelde_uitvoerder
        vendor = uuid.uuid4()
        koppel_crediteur(administratie_id, zzper, vendor, beheerder_id, uurtarief="40")
        _afspraak(administratie_id, project_id, zzper, beheerder_id, eenheid="uur", tarief=Decimal("54"), geldig_tm=(2026, 30))
        staat_met_m2(administratie_id, zzper, project_id, uitvoerder, week=30, dagen=(("8", None), ("2", None)))  # 10 u × 54 = 540
        staat_met_m2(administratie_id, zzper, project_id, uitvoerder, week=31, dagen=(("8", None),))  # 8 u × 40 = 320
        doc = maak_factuur(administratie_id, beheerder_id, opslag, vendor, nettos=("860.00",))
        m = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=doc, actor_id=beheerder_id)
        assert m.uitkomst == "match" and m.staten_som_uren == Decimal("18")
        bronnen = {s["weeknummer"]: s["tariefbron"] for s in m.details["staten"]}
        assert bronnen == {30: "projectafspraak", 31: "koppeling"}
        assert set(m.details["tariefbronnen"]) == {"projectafspraak 26014 Eindhoven (BAM) · € 54.00/u", "koppeling-tarief · € 40.00/u"}

    def test_onbepaalbaar_zonder_afspraak_en_koppelingtarief(self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag, admin_engine):
        zzper, uitvoerder = gekoppelde_zzper, gekoppelde_uitvoerder
        vendor = uuid.uuid4()
        koppel_crediteur(administratie_id, zzper, vendor, beheerder_id, uurtarief=None)
        project_b = maak_project(admin_engine, administratie_id, "26099 Breda (Moeskops)")
        service.koppel_project(administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_b, actor_id=beheerder_id)
        service.koppel_project(administratie_id=administratie_id, gebruiker_id=uitvoerder, project_id=project_b, actor_id=beheerder_id)
        _afspraak(administratie_id, project_id, zzper, beheerder_id, eenheid="uur", tarief=Decimal("50"))
        staat_met_m2(administratie_id, zzper, project_id, uitvoerder, week=30, dagen=(("8", None),))  # geprijsd via afspraak
        staat_met_m2(administratie_id, zzper, project_b, uitvoerder, week=30, dagen=(("8", None),))  # onbepaalbaar
        doc = maak_factuur(administratie_id, beheerder_id, opslag, vendor, nettos=("400.00",))
        m = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=doc, actor_id=beheerder_id)
        # Eén staat zonder tarief = geen bedragtoets (nooit half optellen) → alleen uren / niet toetsbaar.
        assert m.tarief_ontbreekt is True and m.staten_som_bedrag is None
        assert m.uitkomst == "niet_toetsbaar"
        assert any(s["tariefbron"] is None for s in m.details["staten"])

    def test_bureaufactuur_gebruikt_projectafspraak_van_de_zzper(self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, detacheerder, beheerder_id, opslag):
        zzper, uitvoerder = gekoppelde_zzper, gekoppelde_uitvoerder
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=zzper, actor_id=beheerder_id)
        zet_bureau_tarief(detacheerder, zzper, beheerder_id, uurtarief="51")
        vendor = uuid.uuid4()
        koppel_crediteur(administratie_id, detacheerder, vendor, beheerder_id, uurtarief=None)
        _afspraak(administratie_id, project_id, zzper, beheerder_id, eenheid="uur", tarief=Decimal("54"))
        staat_met_m2(administratie_id, zzper, project_id, uitvoerder, week=30, dagen=(("10", None),))  # 10 × 54 = 540 (bureau 510)
        doc = maak_factuur(administratie_id, beheerder_id, opslag, vendor, nettos=("540.00",))
        m = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=doc, actor_id=beheerder_id)
        assert m.uitkomst == "match" and m.details["leden"][0]["tariefbronnen"] == ["projectafspraak 26014 Eindhoven (BAM) · € 54.00/u"]
        # Detail toont het bureau als standaard-bron voor de ZZP'er.
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert detail.prijsafspraken[0].via_bureau_naam == "Karin S." and detail.prijsafspraken[0].standaard_tarief == Decimal("51")
