"""Pro-rato-periode "heel jaar" (D4 fixrun 07-09, mockup-notitie ⑩): jaaromzet = Σ omzet per project over de
AFGESLOTEN maanden van een kalenderjaar (lopend jaar t/m de vorige maand, vorig jaar alle twaalf), dezelfde
uitsluitingen als de maandselectie; opslag als (1 januari, soort 'jaar') zodat januari en heel jaar niet
verwisselen; server-side poort (toekomstig jaar / jaar zonder afgesloten maand / maand 13 = 422); bevroren
jaarstand bij het boeken; hercontrole tegen de ACTUELE jaarstand (er komt een maand bij → verschuiving zichtbaar,
zelfde drempel/uitkomst als bij maanden)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, tegenboeken
from app.main import app
from app.projectverdeling import data as pv
from app.projectverdeling import hercontrole, service
from app.projectverdeling.omzet import omzet_per_project
from app.security.tokens import create_access_token
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.projectverdeling.conftest import seed_omzet
from tests.projectverdeling.test_service import AANGIFTE_Q3_INGEDIEND, _rij, _VasteDatum

VANDAAG = date(2026, 9, 15)  # → lopend jaar 2026 = afgesloten t/m augustus
JAAR_2026 = pv.Periode.jaar(2026)
JAAR_2025 = pv.Periode.jaar(2025)


class _Sept15(date):
    @classmethod
    def today(cls) -> date:  # type: ignore[override]
        return VANDAAG


class TestPeriodePuur:
    def test_parse_codes(self) -> None:
        assert pv.Periode.parse("2026") == JAAR_2026 and JAAR_2026.code == "2026" and JAAR_2026.is_jaar
        assert pv.Periode.parse("2026-07") == pv.Periode.maand(date(2026, 7, 1))
        assert pv.Periode.parse("2026-07-01").code == "2026-07"  # oude vorm blijft leesbaar
        assert not pv.Periode.parse("2026-07").is_jaar
        for slecht in ("2026-13", "2026-00", "26", "2026-7", "2026/07", "", "2026-07-15"):
            with pytest.raises(pv.PeriodeFout):
                pv.Periode.parse(slecht)
        assert pv.als_periode(date(2026, 7, 1)) == pv.Periode.maand(date(2026, 7, 1))
        with pytest.raises(pv.PeriodeFout):
            pv.als_periode(date(2026, 7, 2))

    def test_jaar_eind_is_eerste_dag_lopende_maand_of_volgend_jaar(self) -> None:
        assert pv.periode_eind(JAAR_2026, VANDAAG) == date(2026, 9, 1)
        assert pv.periode_eind(JAAR_2025, VANDAAG) == date(2026, 1, 1)
        assert pv.periode_eind(JAAR_2026, date(2026, 1, 10)) == date(2026, 1, 1)  # leeg bereik
        assert pv.laatste_afgesloten_maand(JAAR_2026, VANDAAG) == 8
        assert pv.laatste_afgesloten_maand(JAAR_2025, VANDAAG) == 12
        assert pv.laatste_afgesloten_maand(JAAR_2026, date(2026, 1, 10)) == 0
        # maand ongewijzigd
        assert pv.periode_eind(pv.Periode.maand(date(2026, 7, 1)), VANDAAG) == date(2026, 8, 1)

    def test_labels(self) -> None:
        assert pv.periode_label(JAAR_2026, VANDAAG) == "2026 (t/m augustus)"
        assert pv.periode_label(JAAR_2025, VANDAAG) == "2025"
        assert pv.periode_label(JAAR_2026, date(2027, 3, 1)) == "2026"
        assert pv.periode_label(JAAR_2026, None) == "2026"
        assert pv.periode_label(JAAR_2026, date(2026, 1, 5)) == "2026 (nog geen afgesloten maand)"
        assert pv.periode_label(pv.Periode.maand(date(2026, 7, 1)), VANDAAG) == "juli 2026"
        assert pv.periode_label(None) == ""

    def test_validatie(self) -> None:
        with pytest.raises(pv.PeriodeFout, match="toekomst"):
            pv.valideer_periode(pv.Periode.jaar(2027), VANDAAG)
        with pytest.raises(pv.PeriodeFout, match="geen afgesloten maand"):
            pv.valideer_periode(JAAR_2026, date(2026, 1, 20))
        pv.valideer_periode(JAAR_2025, date(2026, 1, 20))
        pv.valideer_periode(JAAR_2026, VANDAAG)
        with pytest.raises(pv.PeriodeFout, match="toekomst"):
            pv.valideer_periode(pv.Periode.maand(date(2026, 10, 1)), VANDAAG)
        pv.valideer_periode(pv.Periode.maand(date(2026, 9, 1)), VANDAAG)

    def test_uit_opslag_onderscheidt_januari_van_heel_jaar(self) -> None:
        assert pv.Periode.uit_opslag(date(2026, 1, 1), "maand").code == "2026-01"
        assert pv.Periode.uit_opslag(date(2026, 1, 1), "jaar").code == "2026"
        assert pv.Periode.uit_opslag(None, "jaar") is None

    def test_bereken_blokkade_noemt_de_jaarperiode(self) -> None:
        b = pv.bereken(
            basisbedrag=Decimal("100.00"),
            vaste_regels=[],
            pro_rato=True,
            periode=JAAR_2026,
            omzetstanden=[],
            vandaag=VANDAAG,
        )
        assert not b.compleet and b.blokkade is not None
        assert "Geen omzet in 2026 (t/m augustus)" in b.blokkade


class TestJaaromzet:
    def test_lopend_jaar_is_som_afgesloten_maanden_met_dezelfde_uitsluitingen(
        self, administratie_id, projecten
    ) -> None:
        with scoped_session(administratie_id) as session:
            sel = omzet_per_project(session, administratie_id=administratie_id, periode=JAAR_2026, vandaag=VANDAAG)
        # jan–aug 2026: Eindhoven 99.999 (30-06) + 6.000 (juli) + 99.999 (01-08); Tilburg/Venlo alleen juli.
        # OVH, inactief project, inkoop-regel en verdwenen regel tellen — net als bij een maand — niet mee.
        assert {s.project_id: s.omzet for s in sel.standen} == {
            projecten["eindhoven"]: Decimal("205998.00"),
            projecten["tilburg"]: Decimal("2500.00"),
            projecten["venlo"]: Decimal("1500.00"),
        }
        assert not sel.cache_leeg
        # Peildatum 12-08: augustus is nog niet afgesloten → de 01-08-factuur telt niet mee.
        with scoped_session(administratie_id) as session:
            tm_juli = omzet_per_project(
                session, administratie_id=administratie_id, periode=JAAR_2026, vandaag=date(2026, 8, 12)
            )
        assert {s.project_id: s.omzet for s in tm_juli.standen}[projecten["eindhoven"]] == Decimal("105999.00")

    def test_vorig_jaar_telt_alle_twaalf_maanden(self, administratie_id, projecten, admin_engine: Engine) -> None:
        seed_omzet(admin_engine, administratie_id, projecten["venlo"], "1000.00", date(2025, 1, 1))
        seed_omzet(admin_engine, administratie_id, projecten["venlo"], "1000.00", date(2025, 12, 31))
        seed_omzet(admin_engine, administratie_id, projecten["venlo"], "5000.00", date(2024, 12, 31))
        seed_omzet(admin_engine, administratie_id, projecten["ovh"], "800.00", date(2025, 6, 1))
        with scoped_session(administratie_id) as session:
            sel = omzet_per_project(session, administratie_id=administratie_id, periode=JAAR_2025, vandaag=VANDAAG)
        assert {s.project_id: s.omzet for s in sel.standen} == {projecten["venlo"]: Decimal("2000.00")}
        assert not sel.cache_leeg


def _opslag(admin_engine: Engine, document_id: uuid.UUID) -> tuple[date | None, str]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT pro_rato_periode, pro_rato_soort FROM boekhouding.projectverdeling WHERE document_id = :id"),
            {"id": document_id},
        ).one()  # type: ignore[return-value]


class TestOpslaanJaar:
    def test_sla_op_jaar_terugleesbaar_en_januari_blijft_een_maand(
        self, administratie_id, gescoopte_gebruiker, document_zonder_project, projecten, admin_engine, monkeypatch
    ) -> None:
        monkeypatch.setattr(service, "date", _Sept15)
        data = service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode="2026",
        )
        assert data is not None and data.pro_rato and data.pro_rato_periode == JAAR_2026
        assert data.pro_rato_periode_label == "2026 (t/m augustus)"
        assert data.compleet and sum(d.bedrag for d in data.delen) == Decimal("2000.00")
        assert {d.project_id: d.omzet for d in data.delen}[projecten["eindhoven"]] == Decimal("205998.00")
        assert {s.project_id for s in data.omzetstanden} == {
            projecten["eindhoven"],
            projecten["tilburg"],
            projecten["venlo"],
        }
        assert _opslag(admin_engine, document_zonder_project) == (date(2026, 1, 1), "jaar")
        assert "pro rato omzet 2026 (t/m augustus)" in service.samenvatting(data)

        # Januari als MAAND: zelfde startdatum, andere soort — nooit verwisseld met het hele jaar.
        januari = service.sla_op(
            administratie_id=administratie_id,
            document_id=document_zonder_project,
            actor_id=gescoopte_gebruiker,
            vaste_regels=[],
            pro_rato_periode="2026-01",
        )
        assert januari is not None and januari.pro_rato_periode == pv.Periode.maand(date(2026, 1, 1))
        assert _opslag(admin_engine, document_zonder_project) == (date(2026, 1, 1), "maand")
        gelezen = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=document_zonder_project
        ).projectverdeling
        assert gelezen is not None and gelezen.pro_rato_periode is not None
        assert gelezen.pro_rato_periode.code == "2026-01" and not gelezen.compleet  # geen omzet in januari

    def test_validatie_toekomst_jaar_maand_13_en_jaar_zonder_afgesloten_maand(
        self, administratie_id, gescoopte_gebruiker, document_zonder_project, projecten
    ) -> None:
        def poging(code: str, vandaag: date = VANDAAG):
            return service.sla_op(
                administratie_id=administratie_id,
                document_id=document_zonder_project,
                actor_id=gescoopte_gebruiker,
                vaste_regels=[],
                pro_rato_periode=code,
                vandaag=vandaag,
            )

        with pytest.raises(service.ProjectverdelingServiceFout, match="toekomst"):
            poging("2027")
        with pytest.raises(service.ProjectverdelingServiceFout, match="bestaat niet"):
            poging("2026-13")
        with pytest.raises(service.ProjectverdelingServiceFout, match="geen afgesloten maand"):
            poging("2026", vandaag=date(2026, 1, 10))
        # Vorig jaar in januari mag wél.
        assert poging("2025", vandaag=date(2026, 1, 10)) is not None


class TestRouterJaar:
    def test_put_jaar_200_en_ongeldige_codes_422(
        self, administratie_id, gescoopte_gebruiker, document_zonder_project, projecten, monkeypatch
    ) -> None:
        monkeypatch.setattr(service, "date", _Sept15)
        client = TestClient(app)
        pad = f"/administraties/{administratie_id}/documenten/{document_zonder_project}/projectverdeling"
        headers = {"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"}
        ok = client.put(pad, headers=headers, json={"vaste_regels": [], "pro_rato_periode": "2026"})
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["pro_rato_periode"] == "2026" and body["pro_rato_periode_label"] == "2026 (t/m augustus)"
        assert body["compleet"] is True and body["aantal_projecten_met_omzet"] == 3
        assert client.get(pad, headers=headers).json()["pro_rato_periode"] == "2026"
        for code in ("2027", "2026-13", "abc", "2026-07-15"):
            fout = client.put(pad, headers=headers, json={"vaste_regels": [], "pro_rato_periode": code})
            assert fout.status_code == 422, (code, fout.text)
        # Maandcode én de oude datumvorm blijven werken.
        assert client.put(pad, headers=headers, json={"vaste_regels": [], "pro_rato_periode": "2026-07"}).json()[
            "pro_rato_periode"
        ] == "2026-07"
        assert client.put(pad, headers=headers, json={"vaste_regels": [], "pro_rato_periode": "2026-07-01"}).json()[
            "pro_rato_periode_label"
        ] == "juli 2026"


@pytest.fixture
def geboekt_met_jaarverdeling(
    administratie_id, beheerder_id, gescoopte_gebruiker, document_zonder_project, projecten, monkeypatch
) -> tuple[uuid.UUID, FakeBoekClient]:
    """Floorbeheer geboekt op 12-08-2026 (gepind): € 600 vast Tilburg + € 1.400 pro rato jaaromzet 2026 —
    op dat moment afgesloten t/m juli (Eindhoven 105.999 / Tilburg 2.500 / Venlo 1.500)."""
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    monkeypatch.setattr(service, "date", _VasteDatum)  # today() = 12-08-2026
    service.sla_op(
        administratie_id=administratie_id,
        document_id=document_zonder_project,
        actor_id=gescoopte_gebruiker,
        vaste_regels=[pv.VasteRegel(project_id=projecten["tilburg"], bedrag=Decimal("600.00"))],
        pro_rato_periode="2026",
    )
    fake = FakeBoekClient(aangiften=[AANGIFTE_Q3_INGEDIEND])
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    monkeypatch.setattr(tegenboeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    boeken.boek_document(
        administratie_id=administratie_id, document_id=document_zonder_project, actor_id=gescoopte_gebruiker
    )
    return document_zonder_project, fake


class TestHercontroleJaar:
    def test_bevroren_jaarstand_en_hercontrole_tegen_actuele_jaarstand(
        self, geboekt_met_jaarverdeling, administratie_id, beheerder_id, projecten, admin_engine: Engine
    ) -> None:
        document_id, _ = geboekt_met_jaarverdeling
        rij = _rij(admin_engine, document_id)
        assert rij["status"] == "geboekt" and rij["pro_rato_bedrag"] == Decimal("1400.00")
        assert _opslag(admin_engine, document_id) == (date(2026, 1, 1), "jaar")
        bevroren = {s["project_id"]: Decimal(s["omzet"]) for s in rij["omzetstanden"]}
        assert bevroren[str(projecten["eindhoven"])] == Decimal("105999.00")  # t/m juli, bevroren

        # Hercontrole op 02-09 zónder nieuwe boekingen: augustus is nu afgesloten (Eindhoven +99.999) → de
        # jaarstand verschuift, maar hier onder de drempel (E 96,4 % → 98,1 %): pct > 0, geen signaal.
        tellers = hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=date(2026, 9, 2))
        assert tellers["herrekend"] == 1 and tellers["signalen"] == 0
        pct = _rij(admin_engine, document_id)["hercontrole_afwijking_pct"]
        assert Decimal("0") < pct < Decimal("5")
        # Bevroren stand blijft leesbaar als de oude stand (kernprincipe: bevroren = bevroren).
        nu = _rij(admin_engine, document_id)["omzetstanden"]
        assert {s["project_id"]: Decimal(s["omzet"]) for s in nu} == bevroren

        # Grote augustusfactuur Tilburg (€ 50.000) → Tilburg 2,3 % → 20,2 % van de jaaromzet → boven drempel.
        seed_omzet(admin_engine, administratie_id, projecten["tilburg"], "50000.00", date(2026, 8, 15))
        tellers = hercontrole.herbereken_administratie(
            administratie_id=administratie_id, vandaag=date(2026, 9, 2), forceer=True
        )
        assert tellers["signalen"] == 1
        rij = _rij(admin_engine, document_id)
        assert rij["hercontrole_afwijking_pct"] > Decimal("5")
        assert sum(Decimal(d["bedrag"]) for d in rij["hercontrole_verdeling"]) == Decimal("2000.00")
        with admin_engine.connect() as conn:
            detail = conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                    "AND detail ? 'projectverdeling_afwijking'"
                ),
                {"id": document_id},
            ).scalar_one()
        assert detail["projectverdeling_afwijking"]["periode"] == "2026"
        assert detail["projectverdeling_afwijking"]["periode_label"] == "2026 (t/m augustus)"
        assert "jaaromzet 2026" in detail["reden"] and "nu 2026 (t/m augustus)" in detail["reden"]

        # Kantoorbrede lijst + bevroren lezing dragen code én label.
        lijst = service.hercontrole_signalen(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER)
        assert lijst.totaal == 1 and lijst.rijen[0].pro_rato_periode == JAAR_2026
        assert (lijst.rijen[0].pro_rato_periode_label or "").startswith("2026")
        gelezen = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        pvd = gelezen.projectverdeling
        assert pvd is not None and pvd.status == "geboekt" and pvd.pro_rato_periode == JAAR_2026
        assert pvd.hercontrole is not None and pvd.hercontrole.signaal and pvd.hercontrole.periode == JAAR_2026
        assert {s.project_id: s.omzet for s in pvd.omzetstanden}[projecten["eindhoven"]] == Decimal("105999.00")
