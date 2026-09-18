"""Veld-app uitvoerder — feedback Peter 18-09 (opdracht 2026-09-18-veldapp-uitvoerder-feedback…).

Blok A: m² optioneel (guard: indienen zonder m² = 200; de som telt alleen ingevulde regels).
Blok B: doorfactureren-keuze per regel (default uit het project — verrekenbare staffel → Doorfactureren, anders Niet;
mens wint; audit oud→nieuw; totalen "niet doorfactureren" apart).
Blok C: de uitvoerder schrijft eigen weekstaten op élk actief project (nooit zelf keuren; te-keuren-lijst zonder eigen
staten; projectenlijst = alle actieve projecten, gekoppeld bovenaan; projectdetail en meerwerk op elk actief project).
Blok D is frontend-only (allowlist `auth/rollen.ts`, vitest)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.main import app
from app.security.tokens import create_access_token
from app.tijd import vandaag_nl
from app.uren import overzichten, service
from tests.uren.conftest import maak_gebruiker, maak_project

client = TestClient(app)

VANDAAG = vandaag_nl()
JAAR, WEEK = VANDAAG.isocalendar()[0], VANDAAG.isocalendar()[1]
MAANDAG = date.fromisocalendar(JAAR, WEEK, 1)
DINSDAG = date.fromisocalendar(JAAR, WEEK, 2)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _met_scope(gebruiker_id: uuid.UUID, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=gebruiker_id, administratie_id=administratie_id
    )
    voorwaarden.leg_akkoord_vast(gebruiker_id=gebruiker_id)
    return gebruiker_id


def _staffel(admin_engine: Engine, administratie_id, project_id, beheerder_id, *, verrekenbaar: bool) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_staffel (id, administratie_id, project_id, omschrijving, eenheid, "
                "prijs_per_eenheid, verrekenbaar, bron, aangemaakt_door) VALUES (:id, :a, :p, 'Steiger per m²', 'm2', "
                "9.20, :v, 'handmatig', :b)"
            ),
            {"id": uuid.uuid4(), "a": administratie_id, "p": project_id, "v": verrekenbaar, "b": beheerder_id},
        )


def _zet_dag(administratie_id, wie, project_id, *, datum=MAANDAG, uren="8", m2=None, doorfactureren=None, actor=None):
    return service.zet_dag(
        administratie_id=administratie_id,
        zzper_id=wie,
        project_id=project_id,
        jaar=JAAR,
        weeknummer=WEEK,
        datum=datum,
        uren=Decimal(uren),
        m2=Decimal(m2) if m2 is not None else None,
        doorfactureren=doorfactureren,
        actor_id=actor or wie,
    )


def _audit(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.begin() as conn:
        rijen = conn.execute(
            text("SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"),
            {"a": actie},
        ).all()
    return [{"oud": r[0], "nieuw": r[1]} for r in rijen]


# --- blok A: m² optioneel --------------------------------------------------------------------------------------------


class TestM2Optioneel:
    def test_guard_indienen_zonder_m2_is_200_via_de_api(self, zzper, administratie_id, project_id, beheerder_id):
        """Guard-test opdracht blok A: dag zonder m² opslaan én de week indienen = 200; m² blijft null (nooit 0)."""
        wie = _met_scope(zzper, administratie_id, beheerder_id)
        headers = _bearer(wie, rol="zzper")
        resp = client.put(
            "/uren/zzp/dag",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
                "datum": MAANDAG.isoformat(),
                "uren": "8",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        (dag,) = resp.json()["dagen"]
        assert dag["m2"] is None
        assert resp.json()["totaal_m2"] == "0"
        resp = client.post(
            "/uren/zzp/indienen",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ingediend"

    def test_totaal_m2_telt_alleen_ingevulde_regels(self, administratie_id, project_id, gekoppelde_zzper):
        _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="8")
        staat = _zet_dag(administratie_id, gekoppelde_zzper, project_id, datum=DINSDAG, uren="6", m2="120")
        assert staat.totaal_m2 == Decimal("120")
        assert [d.m2 for d in staat.dagen] == [None, Decimal("120")]


# --- blok B: doorfactureren per regel --------------------------------------------------------------------------------


class TestDoorfactureren:
    def test_default_zonder_verrekenbare_staffel_is_niet_doorfactureren(
        self, administratie_id, project_id, gekoppelde_zzper
    ):
        staat = _zet_dag(administratie_id, gekoppelde_zzper, project_id)
        assert staat.doorfactureren_standaard is False
        assert staat.dagen[0].doorfactureren is False
        assert staat.totaal_uren_niet_doorfactureren == Decimal("8")

    def test_default_met_verrekenbare_staffel_is_doorfactureren(
        self, admin_engine, administratie_id, project_id, gekoppelde_zzper, beheerder_id
    ):
        _staffel(admin_engine, administratie_id, project_id, beheerder_id, verrekenbaar=True)
        staat = _zet_dag(administratie_id, gekoppelde_zzper, project_id)
        assert staat.doorfactureren_standaard is True
        assert staat.dagen[0].doorfactureren is True
        assert staat.totaal_uren_niet_doorfactureren == Decimal("0")

    def test_alleen_niet_verrekenbare_staffel_blijft_niet(
        self, admin_engine, administratie_id, project_id, gekoppelde_zzper, beheerder_id
    ):
        _staffel(admin_engine, administratie_id, project_id, beheerder_id, verrekenbaar=False)
        assert _zet_dag(administratie_id, gekoppelde_zzper, project_id).dagen[0].doorfactureren is False

    def test_mens_wint_en_audit_oud_naar_nieuw(self, admin_engine, administratie_id, project_id, gekoppelde_zzper):
        _zet_dag(administratie_id, gekoppelde_zzper, project_id, doorfactureren=True)  # expliciet, tegen de default in
        staat = _zet_dag(administratie_id, gekoppelde_zzper, project_id, datum=DINSDAG, uren="4", m2="30")  # default
        assert [d.doorfactureren for d in staat.dagen] == [True, False]
        assert staat.totaal_uren_niet_doorfactureren == Decimal("4")
        assert staat.totaal_m2_niet_doorfactureren == Decimal("30")
        # Bijwerken zonder keuze houdt de bestaande stand; mét keuze wisselt hij — audit draagt oud→nieuw.
        staat = _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="7")
        assert staat.dagen[0].doorfactureren is True
        staat = _zet_dag(administratie_id, gekoppelde_zzper, project_id, uren="7", doorfactureren=False)
        assert staat.dagen[0].doorfactureren is False
        events = _audit(admin_engine, "weekstaat_dag_gezet")
        laatste = events[-1]
        assert laatste["oud"]["doorfactureren"] is True and laatste["nieuw"]["doorfactureren"] is False

    def test_lookup_zonder_staat_draagt_de_projectdefault(
        self, admin_engine, zzper, administratie_id, project_id, tweede_project_id, beheerder_id
    ):
        wie = _met_scope(zzper, administratie_id, beheerder_id)
        _staffel(admin_engine, administratie_id, tweede_project_id, beheerder_id, verrekenbaar=True)
        headers = _bearer(wie, rol="zzper")
        basis = f"/uren/zzp/weekstaat?administratie_id={administratie_id}&jaar={JAAR}&weeknummer={WEEK}"
        zonder = client.get(f"{basis}&project_id={project_id}", headers=headers).json()
        met = client.get(f"{basis}&project_id={tweede_project_id}", headers=headers).json()
        assert zonder == {"weekstaat": None, "doorfactureren_standaard": False}
        assert met == {"weekstaat": None, "doorfactureren_standaard": True}

    def test_api_neemt_de_keuze_mee(self, zzper, administratie_id, project_id, beheerder_id):
        wie = _met_scope(zzper, administratie_id, beheerder_id)
        resp = client.put(
            "/uren/zzp/dag",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
                "datum": MAANDAG.isoformat(),
                "uren": "8",
                "doorfactureren": True,
            },
            headers=_bearer(wie, rol="zzper"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["dagen"][0]["doorfactureren"] is True
        assert resp.json()["doorfactureren_standaard"] is False


# --- blok C: uitvoerder schrijft eigen weekstaten, ziet alle projecten, keurt nooit zichzelf --------------------------


class TestUitvoerderEigenUren:
    def test_uitvoerder_schrijft_eigen_weekstaat_op_ongepland_project_en_dient_in(
        self, admin_engine, uitvoerder, administratie_id, project_id, beheerder_id
    ):
        wie = _met_scope(uitvoerder, administratie_id, beheerder_id)
        staat = _zet_dag(administratie_id, wie, project_id, m2="40")
        assert staat.status == "concept" and staat.gebruiker_id == wie
        assert staat.dagen[0].buiten_planning is True and staat.dagen_buiten_planning == 1  # chip "niet gepland"
        ingediend = service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=wie,
            project_id=project_id,
            jaar=JAAR,
            weeknummer=WEEK,
            actor_id=wie,
        )
        assert ingediend.status == "ingediend"
        # De koppeling ontstond in dezelfde gang (bron 'weekstaat') — het project staat nu ook bij "gekoppeld".
        kaarten = overzichten.uitvoerder_projecten(uitvoerder_id=wie)
        assert [(k.project_id, k.gekoppeld) for k in kaarten] == [(project_id, True)]

    def test_uitvoerder_keurt_nooit_zijn_eigen_staat(self, uitvoerder, administratie_id, project_id, beheerder_id):
        wie = _met_scope(uitvoerder, administratie_id, beheerder_id)
        _zet_dag(administratie_id, wie, project_id)
        staat = service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=wie,
            project_id=project_id,
            jaar=JAAR,
            weeknummer=WEEK,
            actor_id=wie,
        )
        assert overzichten.te_keuren(uitvoerder_id=wie) == []
        with pytest.raises(service.GeenToegang, match="eigen weekstaat"):
            service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=wie)
        with pytest.raises(service.GeenToegang, match="eigen weekstaat"):
            service.keur_week_af(administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=wie, reden="test")

    def test_andere_uitvoerder_op_het_project_keurt_wel(
        self, admin_engine, uitvoerder, administratie_id, project_id, beheerder_id
    ):
        wie = _met_scope(uitvoerder, administratie_id, beheerder_id)
        _zet_dag(administratie_id, wie, project_id)
        staat = service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=wie,
            project_id=project_id,
            jaar=JAAR,
            weeknummer=WEEK,
            actor_id=wie,
        )
        ander = _met_scope(maak_gebruiker(admin_engine, "uitvoerder", "Kees A."), administratie_id, beheerder_id)
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=ander, project_id=project_id, actor_id=beheerder_id
        )
        assert [i.weekstaat_id for i in overzichten.te_keuren(uitvoerder_id=ander)] == [staat.id]
        goed = service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=ander)
        assert goed.status == "goedgekeurd"

    def test_detacheerder_werkt_nooit_namens_een_uitvoerder(
        self, uitvoerder, detacheerder, administratie_id, project_id, beheerder_id
    ):
        _met_scope(uitvoerder, administratie_id, beheerder_id)
        with pytest.raises(service.GeenToegang, match="Namens-invoer bestaat alleen voor ZZP"):
            _zet_dag(administratie_id, uitvoerder, project_id, actor=detacheerder)

    def test_uitvoerder_ziet_alle_actieve_projecten_gekoppeld_bovenaan(
        self, admin_engine, uitvoerder, administratie_id, project_id, tweede_project_id, beheerder_id
    ):
        wie = _met_scope(uitvoerder, administratie_id, beheerder_id)
        inactief = maak_project(admin_engine, administratie_id, "25001 Afgerond (oud)")
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.project_cache SET is_actief = false WHERE id = :id"), {"id": inactief}
            )
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=wie, project_id=tweede_project_id, actor_id=beheerder_id
        )
        kaarten = overzichten.uitvoerder_projecten(uitvoerder_id=wie)
        assert [(k.project_naam, k.gekoppeld) for k in kaarten] == [
            ("26021 Tilburg (Heijmans)", True),
            ("26014 Eindhoven (BAM)", False),
        ]
        # Projectdetail op het ongekoppelde actieve project mag; op het inactieve, ongekoppelde niet.
        detail = overzichten.projectdetail_uitvoerder(
            administratie_id=administratie_id, project_id=project_id, actor_id=wie
        )
        assert detail.project_id == project_id
        with pytest.raises(service.GeenToegang, match="niet \\(meer\\) actief"):
            overzichten.projectdetail_uitvoerder(administratie_id=administratie_id, project_id=inactief, actor_id=wie)

    def test_week_projecten_voor_de_uitvoerder_via_de_api(
        self, uitvoerder, administratie_id, project_id, tweede_project_id, beheerder_id
    ):
        wie = _met_scope(uitvoerder, administratie_id, beheerder_id)
        # Project-eerst (18-09): zonder planning/regels/meerwerk geen kaarten; `alles=true` = de keuzelijst.
        resp = client.get(
            f"/uren/zzp/week-projecten?jaar={JAAR}&weeknummer={WEEK}", headers=_bearer(wie, rol="uitvoerder")
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == []
        resp = client.get(
            f"/uren/zzp/week-projecten?jaar={JAAR}&weeknummer={WEEK}&alles=true", headers=_bearer(wie, rol="uitvoerder")
        )
        assert resp.status_code == 200, resp.text
        assert {p["project_id"] for p in resp.json()} == {str(project_id), str(tweede_project_id)}
        assert all(p["gepland"] is False and p["status"] == "nieuw" for p in resp.json())
