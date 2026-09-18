"""Veld-app PROJECT-EERST (Peter 18-09: "Niet beter om eerst het project te selecteren en dan de uren-/meerwerkknop?";
opdracht 2026-09-18-veldapp-project-eerst-flow, bouwnorm `mockup/uren-uitvoerder-v2.html` scherm ①).

`week_projecten_zzp` levert standaard de KAARTEN van de week: gepland ∪ mét regels (staat) ∪ mét eigen meerwerk;
met `alles=True` álle actieve projecten in de scope (keuzelijst "+ Ander project toevoegen aan mijn week"). Per kaart
reizen de kaartvelden mee (uren per dag, laatste omschrijving, dagen "niet doorfactureren", projectdefault,
meerwerk-aantal).
Set-based: het aantal statements per aanroep is onafhankelijk van het aantal kaarten (querytelling-meetlat)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.db import session as db_session
from app.main import app
from app.security.tokens import create_access_token
from app.uren import overzichten, planning, service
from tests.uren.conftest import maak_project

client = TestClient(app)

JAAR, WEEK = 2026, 34
MA, DI, WO = date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19)


class _Teller:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        self.statements.append(statement)

    def __enter__(self) -> _Teller:
        event.listen(db_session.engine, "before_cursor_execute", self)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(db_session.engine, "before_cursor_execute", self)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _plan(administratie_id, wie, project_id, datum, actor):  # noqa: ANN001
    planning.plan_toewijzing(
        administratie_id=administratie_id, gebruiker_id=wie, project_id=project_id, datum=datum, actor_id=actor
    )


def _uren(administratie_id, wie, project_id, datum, *, uren="8", opmerking=None, doorfactureren=None):  # noqa: ANN001
    return service.zet_dag(
        administratie_id=administratie_id,
        zzper_id=wie,
        project_id=project_id,
        jaar=JAAR,
        weeknummer=WEEK,
        datum=datum,
        uren=Decimal(uren),
        opmerking=opmerking,
        doorfactureren=doorfactureren,
        actor_id=wie,
    )


def _meld(administratie_id, project_id, wie, datum):  # noqa: ANN001
    return service.meld_meerwerk(
        administratie_id=administratie_id,
        project_id=project_id,
        actor_id=wie,
        omschrijving="Extra trapsteiger achterzijde",
        aantal=Decimal("12"),
        eenheid="m2",
        datum_uitgevoerd=datum,
    )


def _staffel(admin_engine: Engine, administratie_id, project_id, beheerder_id) -> None:  # noqa: ANN001
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_staffel (id, administratie_id, project_id, omschrijving, eenheid, "
                "prijs_per_eenheid, verrekenbaar, bron, aangemaakt_door) VALUES (:id, :a, :p, 'Steiger per m²', 'm2', "
                "9.20, true, 'handmatig', :b)"
            ),
            {"id": uuid.uuid4(), "a": administratie_id, "p": project_id, "b": beheerder_id},
        )


@pytest.fixture
def uitvoerder_met_scope(uitvoerder, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=uitvoerder, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=uitvoerder)
    return uitvoerder


def _kaarten(wie, **kw):  # noqa: ANN001
    return overzichten.week_projecten_zzp(zzper_id=wie, actor_id=wie, jaar=JAAR, weeknummer=WEEK, **kw)


class TestKaartsamenstelling:
    def test_kaarten_zijn_gepland_of_met_regels_of_met_meerwerk_niet_alle_projecten(
        self, admin_engine, administratie_id, project_id, tweede_project_id, uitvoerder_met_scope, beheerder_id
    ):
        """Peter 18-09: de week = kaarten van geplande projecten + projecten waar al uren/meerwerk op staan — niet meer
        élk actief project (dat is de keuzelijst achter "+ Ander project")."""
        wie = uitvoerder_met_scope
        derde = maak_project(admin_engine, administratie_id, "26030 Venlo (Dura)")
        vierde = maak_project(admin_engine, administratie_id, "26041 Almelo (Ter Steege)")
        _plan(administratie_id, wie, project_id, MA, beheerder_id)  # gepland
        _uren(administratie_id, wie, tweede_project_id, MA, uren="4")  # mét regel, niet gepland
        _meld(administratie_id, derde, wie, DI)  # alleen meerwerk deze week

        kaarten = _kaarten(wie)
        # Volgorde: te doen (gepland zonder staat, concept) → gepland vóór ongepland → de rest op naam.
        assert [k.project_id for k in kaarten] == [project_id, tweede_project_id, derde]
        per = {k.project_id: k for k in kaarten}
        assert vierde not in per  # actief, maar geen planning/regel/meerwerk → géén kaart
        assert per[project_id].gepland and per[project_id].status == "nieuw"
        assert not per[tweede_project_id].gepland and per[tweede_project_id].status == "concept"
        assert per[derde].meerwerk_aantal == 1 and per[derde].status == "nieuw" and not per[derde].gepland
        assert per[derde].project_naam == "26030 Venlo (Dura)"

        # De keuzelijst: álle actieve projecten, dezelfde kaartvorm en volgorde-regel (gepland/mét staat bovenaan).
        alle = _kaarten(wie, alles=True)
        assert [k.project_id for k in alle] == [project_id, tweede_project_id, derde, vierde]
        assert not alle[-1].gepland and alle[-1].weekstaat_id is None and alle[-1].meerwerk_aantal == 0

    def test_inactief_project_met_oud_meerwerk_geeft_geen_kaart(
        self, admin_engine, administratie_id, project_id, uitvoerder_met_scope
    ):
        wie = uitvoerder_met_scope
        _meld(administratie_id, project_id, wie, MA)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.project_cache SET is_actief = false WHERE id = :id"), {"id": project_id}
            )
        assert _kaarten(wie) == []

    def test_meerwerk_buiten_de_week_telt_niet(self, administratie_id, project_id, uitvoerder_met_scope):
        wie = uitvoerder_met_scope
        _meld(administratie_id, project_id, wie, date(2026, 8, 10))  # week 33
        assert _kaarten(wie) == []


class TestKaartvelden:
    def test_dag_uren_laatste_omschrijving_niet_doorfactureren_en_default(
        self, admin_engine, administratie_id, project_id, tweede_project_id, uitvoerder_met_scope, beheerder_id
    ):
        wie = uitvoerder_met_scope
        _staffel(admin_engine, administratie_id, project_id, beheerder_id)  # verrekenbaar → default Doorfactureren
        _uren(administratie_id, wie, project_id, MA, uren="8", opmerking="opbouwen zijgevel")
        _uren(administratie_id, wie, project_id, WO, uren="4", opmerking="afbreken", doorfactureren=False)
        _uren(administratie_id, wie, tweede_project_id, DI, uren="2")

        per = {k.project_id: k for k in _kaarten(wie)}
        kaart = per[project_id]
        assert kaart.dag_uren == {"2026-08-17": Decimal("8"), "2026-08-19": Decimal("4")}
        assert kaart.laatste_omschrijving == "afbreken"  # de laatste dag mét omschrijving wint
        assert kaart.dagen_niet_doorfactureren == 1
        assert kaart.doorfactureren_standaard is True
        assert kaart.totaal_uren == Decimal("12")
        ander = per[tweede_project_id]
        assert ander.dag_uren == {"2026-08-18": Decimal("2")}
        assert ander.laatste_omschrijving is None
        # Geen verrekenbare staffel → default Niet doorfactureren; de regel zonder expliciete keuze volgt die default.
        assert ander.doorfactureren_standaard is False
        assert ander.dagen_niet_doorfactureren == 1

    def test_api_draagt_de_kaartvelden_en_alles_parameter(
        self, administratie_id, project_id, tweede_project_id, uitvoerder_met_scope
    ):
        wie = uitvoerder_met_scope
        _uren(administratie_id, wie, project_id, MA, uren="6", opmerking="transport")
        headers = _bearer(wie, rol="uitvoerder")
        resp = client.get(f"/uren/zzp/week-projecten?jaar={JAAR}&weeknummer={WEEK}", headers=headers)
        assert resp.status_code == 200, resp.text
        (kaart,) = resp.json()
        assert kaart["project_id"] == str(project_id)
        assert {d: Decimal(u) for d, u in kaart["dag_uren"].items()} == {"2026-08-17": Decimal("6")}
        assert kaart["laatste_omschrijving"] == "transport"
        assert kaart["dagen_niet_doorfactureren"] == 1 and kaart["doorfactureren_standaard"] is False  # default Niet
        assert kaart["meerwerk_aantal"] == 0
        resp = client.get(f"/uren/zzp/week-projecten?jaar={JAAR}&weeknummer={WEEK}&alles=true", headers=headers)
        assert resp.status_code == 200, resp.text
        assert [p["project_id"] for p in resp.json()] == [str(project_id), str(tweede_project_id)]


class TestQuerytelling:
    def test_aantal_statements_onafhankelijk_van_aantal_kaarten(
        self, admin_engine, administratie_id, project_id, tweede_project_id, uitvoerder_met_scope, beheerder_id
    ):
        """Set-based (opdracht): één query per bron per administratie — 2 kaarten en 6 kaarten kosten hetzelfde."""
        wie = uitvoerder_met_scope
        _plan(administratie_id, wie, project_id, MA, beheerder_id)
        _uren(administratie_id, wie, tweede_project_id, MA, uren="4")
        with _Teller() as klein:
            assert len(_kaarten(wie)) == 2
        extra = [maak_project(admin_engine, administratie_id, f"2605{i} Extra {i}") for i in range(4)]
        for i, p in enumerate(extra):
            if i % 2 == 0:
                _plan(administratie_id, wie, p, DI, beheerder_id)
            else:
                _uren(administratie_id, wie, p, WO, uren="3", opmerking=f"extra {i}")
        with _Teller() as groot:
            assert len(_kaarten(wie)) == 6
        assert len(groot.statements) == len(klein.statements), (len(klein.statements), len(groot.statements))
        with _Teller() as alles:
            assert len(_kaarten(wie, alles=True)) == 6
        # `alles` kost hooguit één extra statement per administratie (de projectenlijst).
        assert len(alles.statements) <= len(klein.statements) + 1
