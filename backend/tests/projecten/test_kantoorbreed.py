# ruff: noqa: F811 — pytest-fixtures als parameters
"""Inzicht › Projecten kantoorbreed (fixrun 07-09 blok C5): lijst over alle administraties in scope
(Beheerder ziet beide, een echte niet-Beheerder MÉT scope alleen de eigen — RLS-les 25-08), status-chips
uit de caches (resultaat = dezelfde marge als `cijfers.bereken_project_cijfers`, verplichtingen-verbruik,
weekstaten-stand, m²), urgentie-sortering, facetten (filter, nooit poort), paginering, de rolpoort en de
additieve detail-verrijking (verplichtingen mét verbruiksstand + weekstaten-/planningstand)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.main import app
from app.projecten import cijfers, kantoorbreed
from app.security.tokens import create_access_token
from tests.auth.conftest import beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401
from tests.uren.conftest import administratie_id, maak_gebruiker, maak_project  # noqa: F401

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _week(d: date) -> tuple[int, int]:
    c = d.isocalendar()
    return (c[0], c[1])


def _maandag_van(d: date) -> date:
    return d - timedelta(days=d.isoweekday() - 1)


@pytest.fixture
def tweede_administratie(admin_engine: Engine) -> uuid.UUID:
    """Actieve administratie ZONDER uren-opt-in en BUITEN de scope van `gescoopte_gebruiker`."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def _regel(admin_engine: Engine, aid: uuid.UUID, pid: uuid.UUID, soort: str, netto: str, datum: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_regel_cache "
                "(id, administratie_id, rlz_document_id, soort, project_id, netto_bedrag, datum) "
                "VALUES (:id, :aid, :doc, :soort, :pid, :netto, :datum)"
            ),
            {
                "id": uuid.uuid4(),
                "aid": aid,
                "doc": uuid.uuid4(),
                "soort": soort,
                "pid": pid,
                "netto": netto,
                "datum": datum,
            },
        )


def _weekstaat(
    admin_engine: Engine,
    aid: uuid.UUID,
    gid: uuid.UUID,
    pid: uuid.UUID,
    week: tuple[int, int],
    *,
    status: str,
    dagen: list[tuple[date, str, str]] = (),
) -> uuid.UUID:
    sid = uuid.uuid4()
    goedgekeurd = status == "goedgekeurd"
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.weekstaat (id, administratie_id, gebruiker_id, project_id, jaar, weeknummer, "
                " status, ingediend_op, goedgekeurd_op, goedgekeurd_door) "
                "VALUES (:id, :aid, :gid, :pid, :jaar, :week, :status, "
                " CASE WHEN :status IN ('ingediend','goedgekeurd') THEN now() END, "
                " CASE WHEN :goed THEN now() END, CASE WHEN :goed THEN CAST(:gid AS uuid) END)"
            ),
            {
                "id": sid,
                "aid": aid,
                "gid": gid,
                "pid": pid,
                "jaar": week[0],
                "week": week[1],
                "status": status,
                "goed": goedgekeurd,
            },
        )
        for datum, uren, m2 in dagen:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.weekstaat_dag "
                    "(id, weekstaat_id, administratie_id, datum, uren, m2, ingevuld_door) "
                    "VALUES (:id, :sid, :aid, :datum, :uren, :m2, :gid)"
                ),
                {"id": uuid.uuid4(), "sid": sid, "aid": aid, "datum": datum, "uren": uren, "m2": m2, "gid": gid},
            )
    return sid


def _plan(admin_engine: Engine, aid: uuid.UUID, gid: uuid.UUID, pid: uuid.UUID, datum: date, door: uuid.UUID) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.planning_toewijzing "
                "(administratie_id, gebruiker_id, project_id, datum, dagdeel, toegevoegd_door) "
                "VALUES (:aid, :gid, :pid, :datum, 'heel', :door)"
            ),
            {"aid": aid, "gid": gid, "pid": pid, "datum": datum, "door": door},
        )


def _verplichting(
    admin_engine: Engine, aid: uuid.UUID, pid: uuid.UUID, *, goedgekeurd: str, verbruikt: str, nummer: str
) -> uuid.UUID:
    """Goedgekeurde verplichting rechtstreeks in de tabellen (de accorderingsflow zelf is elders getest)."""
    doc_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.document "
                "(id, administratie_id, bron, soort, bestandsnaam, sha256_hash, status, opslag_pad) "
                "VALUES (:id, :aid, 'upload', 'verplichting', :naam, :sha, 'geaccordeerd', :pad)"
            ),
            {"id": doc_id, "aid": aid, "naam": f"{nummer}.pdf", "sha": uuid.uuid4().hex, "pad": f"t/{doc_id}.pdf"},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.verplichting "
                "(document_id, administratie_id, soort_label, project_id, offertenummer, "
                " totaalbedrag_excl, goedgekeurd_bedrag_excl, goedgekeurd_op, verbruikt_bedrag_excl, omschrijving) "
                "VALUES (:doc, :aid, 'offerte', :pid, :nummer, :goed, :goed, now(), :verbruikt, 'Steigerwerk')"
            ),
            {"doc": doc_id, "aid": aid, "pid": pid, "nummer": nummer, "goed": goedgekeurd, "verbruikt": verbruikt},
        )
    return doc_id


@pytest.fixture
def scenario(admin_engine: Engine, administratie_id, tweede_administratie, beheerder_id, gescoopte_gebruiker):
    """Administratie A (uren-opt-in, in scope van de boekhouder): project P1 mét álle signalen, P2 schoon.
    Administratie B (geen opt-in, buiten scope): project P3 zonder cijfers."""
    vandaag = date.today()
    vorige_week_ma = _maandag_van(vandaag) - timedelta(weeks=1)
    twee_weken_ma = vorige_week_ma - timedelta(weeks=1)
    drie_weken_ma = twee_weken_ma - timedelta(weeks=1)
    zzper = maak_gebruiker(admin_engine, "zzper", "Milan K.")
    p1 = maak_project(admin_engine, administratie_id, "26014 Breda (Moeskops)")
    p2 = maak_project(admin_engine, administratie_id, "26021 Tilburg (Heijmans)")
    p3 = maak_project(admin_engine, tweede_administratie, "Kantoorpand Eindhoven")
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_specificatie (project_id, administratie_id, opdrachtgever, "
                " werknummer_opdrachtgever, contract_m2, bijgewerkt_door) "
                "VALUES (:pid, :aid, 'Moeskops Bouw', 'MB-88412', 4000, :door)"
            ),
            {"pid": p1, "aid": administratie_id, "door": beheerder_id},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.veldwerker_crediteur (administratie_id, gebruiker_id, vendor_id, uurtarief, "
                " autoboeken_ingeschakeld, gekoppeld_door) VALUES (:aid, :gid, :vendor, 45.00, false, :door)"
            ),
            {"aid": administratie_id, "gid": zzper, "vendor": uuid.uuid4(), "door": beheerder_id},
        )
    # Resultaat P1: baten 10.000 geboekt, kosten 12.000 geboekt, 8 uur onderweg × € 45 = 360 → marge −2.360.
    _regel(admin_engine, administratie_id, p1, "verkoop", "10000.00", str(drie_weken_ma))
    _regel(admin_engine, administratie_id, p1, "inkoop", "12000.00", str(drie_weken_ma))
    _weekstaat(
        admin_engine,
        administratie_id,
        zzper,
        p1,
        _week(drie_weken_ma),
        status="goedgekeurd",
        dagen=[(drie_weken_ma, "8.00", "1000.00")],
    )
    # Weekstaten: vorige week gepland zónder staat (ontbreekt), twee weken terug ingediend (te keuren).
    _plan(admin_engine, administratie_id, zzper, p1, vorige_week_ma, beheerder_id)
    _plan(admin_engine, administratie_id, zzper, p1, twee_weken_ma, beheerder_id)
    _weekstaat(admin_engine, administratie_id, zzper, p1, _week(twee_weken_ma), status="ingediend")
    # Verplichting: € 5.000 goedgekeurd, € 6.000 verbruikt → overschreden.
    verplichting_id = _verplichting(
        admin_engine, administratie_id, p1, goedgekeurd="5000.00", verbruikt="6000.00", nummer="OFF-1"
    )
    return {
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "zzper": zzper,
        "verplichting": verplichting_id,
        "vorige_week": _week(vorige_week_ma),
        "twee_weken": _week(twee_weken_ma),
    }


class TestLijstEnScope:
    def test_beheerder_ziet_beide_administraties_urgentste_bovenaan(
        self, scenario, administratie_id, tweede_administratie, beheerder_id
    ) -> None:
        r = client.get("/projecten/kantoorbreed", headers=_bearer(beheerder_id, rol="beheerder"))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["totaal"] == 3 and d["administraties_in_selectie"] == 2 and d["per_pagina"] == 25
        assert d["tellers"] == {
            "projecten": 3,
            "administraties": 2,
            "met_signaal": 1,
            "verplichting_overschreden": 1,
            "marge_negatief": 1,
            "weekstaat_ontbreekt": 1,
            "te_keuren": 1,
        }
        p1 = d["rijen"][0]
        assert p1["project_id"] == str(scenario["p1"]) and p1["administratie_id"] == str(administratie_id)
        assert p1["opdrachtgever"] == "Moeskops Bouw" and p1["werknummer_opdrachtgever"] == "MB-88412"
        assert p1["signalen"] == ["verplichting_overschreden", "marge_negatief", "weekstaat_ontbreekt", "te_keuren"]
        assert p1["urgentie"] == 15
        # Chips.
        assert p1["resultaat"]["heeft_cijfers"] is True
        assert Decimal(p1["resultaat"]["marge"]) == Decimal("-2360.00")
        assert Decimal(p1["resultaat"]["marge_pct"]) == Decimal("-23.6")
        assert p1["verplichtingen"] == {
            "aantal": 1,
            "goedgekeurd_excl": "5000.00",
            "verbruikt_excl": "6000.00",
            "percentage": 120,
            "overschreden": 1,
        }
        ws = p1["weekstaten"]
        assert ws["van_toepassing"] is True and ws["ontbrekend"] == 1 and ws["te_keuren"] == 1
        assert (ws["oudste_ontbrekende_jaar"], ws["oudste_ontbrekende_week"]) == scenario["vorige_week"]
        assert Decimal(p1["m2"]["gebouwd_m2"]) == Decimal("1000") and Decimal(p1["m2"]["contract_m2"]) == Decimal(
            "4000"
        )
        assert p1["m2"]["percentage"] == 25 and p1["m2"]["doorlopende_huur"] is False
        # Daarna alfabetisch op administratie/project: Andere BV (P3) vóór Universal (P2).
        assert [x["project_id"] for x in d["rijen"][1:]] == [str(scenario["p3"]), str(scenario["p2"])]
        p3 = d["rijen"][1]
        assert p3["weekstaten"]["van_toepassing"] is False  # geen uren-opt-in
        assert p3["resultaat"]["heeft_cijfers"] is False and p3["resultaat"]["marge_pct"] is None
        assert p3["signalen"] == [] and p3["m2"]["percentage"] is None
        # Facetten.
        assert d["facetten"]["status"]["alle"] == 3 and d["facetten"]["status"]["signaal"] == 1
        assert d["facetten"]["status"]["op_schema"] == 2
        assert {(f["administratie_id"], f["aantal"]) for f in d["facetten"]["administraties"]} == {
            (str(administratie_id), 2),
            (str(tweede_administratie), 1),
        }

    def test_niet_beheerder_met_scope_ziet_alleen_eigen_administratie(
        self, scenario, administratie_id, gescoopte_gebruiker
    ) -> None:
        r = client.get("/projecten/kantoorbreed", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["totaal"] == 2 and d["administraties_in_selectie"] == 1
        assert {x["administratie_id"] for x in d["rijen"]} == {str(administratie_id)}
        assert d["tellers"]["projecten"] == 2 and d["tellers"]["administraties"] == 1

    def test_facetten_zoek_en_paginering(
        self, scenario, administratie_id, tweede_administratie, beheerder_id, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kop = _bearer(beheerder_id, rol="beheerder")
        assert client.get("/projecten/kantoorbreed?status=signaal", headers=kop).json()["totaal"] == 1
        assert client.get("/projecten/kantoorbreed?status=op_schema", headers=kop).json()["totaal"] == 2
        assert client.get("/projecten/kantoorbreed?status=marge_negatief", headers=kop).json()["totaal"] == 1
        d = client.get(f"/projecten/kantoorbreed?administratie_id={tweede_administratie}", headers=kop).json()
        assert d["totaal"] == 1 and d["rijen"][0]["administratie_naam"] == "Andere BV"
        # Het administratie-facet blijft de status-tellers binnen die administratie tonen (filter, geen poort).
        assert d["facetten"]["status"]["alle"] == 1 and d["tellers"]["projecten"] == 3
        assert client.get("/projecten/kantoorbreed?q=moeskops", headers=kop).json()["totaal"] == 1
        assert client.get("/projecten/kantoorbreed?q=MB-88412", headers=kop).json()["totaal"] == 1
        assert client.get("/projecten/kantoorbreed?q=andere%20bv", headers=kop).json()["totaal"] == 1
        assert client.get("/projecten/kantoorbreed?q=bestaatniet", headers=kop).json()["totaal"] == 0
        assert client.get("/projecten/kantoorbreed?status=onzin", headers=kop).status_code == 422
        monkeypatch.setattr(kantoorbreed, "PER_PAGINA", 2)
        p1 = client.get("/projecten/kantoorbreed?pagina=1", headers=kop).json()
        p2 = client.get("/projecten/kantoorbreed?pagina=2", headers=kop).json()
        assert len(p1["rijen"]) == 2 and len(p2["rijen"]) == 1 and p2["totaal"] == 3 and p2["per_pagina"] == 2

    def test_rolpoort_externe_rol_403(self, scenario) -> None:
        r = client.get("/projecten/kantoorbreed", headers=_bearer(scenario["zzper"], rol="zzper"))
        assert r.status_code == 403


class TestChipsSluitenOpDeRekenlaag:
    def test_resultaatchip_is_dezelfde_marge_als_bereken_project_cijfers(
        self, scenario, administratie_id, beheerder_id
    ) -> None:
        """De gebatchte lijst-berekening en de per-project-rekenfunctie van het detail geven dezelfde marge."""
        lijst = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, administratie_id=administratie_id)
        per_project = {r.project_id: r for r in lijst.rijen}
        with scoped_session(administratie_id) as session:
            for pid in (scenario["p1"], scenario["p2"]):
                detail = cijfers.bereken_project_cijfers(session, administratie_id=administratie_id, project_id=pid)
                chip = per_project[pid].resultaat
                assert chip.marge == detail.verwachte_marge
                assert chip.marge_pct == detail.marge_pct
                assert chip.onbepaalbaar_uren == detail.onbepaalbaar_uren

    def test_afmelding_en_lopende_week_tellen_niet_als_ontbrekend(
        self, admin_engine: Engine, scenario, administratie_id, beheerder_id
    ) -> None:
        # De lopende week gepland zonder staat → nooit "ontbrekend".
        _plan(
            admin_engine, administratie_id, scenario["zzper"], scenario["p2"], _maandag_van(date.today()), beheerder_id
        )
        # Vorige week op P1 afgemeld (actieve afmelding) → telt niet meer.
        jaar, week = scenario["vorige_week"]
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.planning_signaal_afhandeling "
                    "(id, administratie_id, gebruiker_id, project_id, "
                    " jaar, weeknummer, soort, reden, door) VALUES (:id, :aid, :gid, :pid, :jaar, :week, 'afgemeld', "
                    " 'ziek gemeld', :door)"
                ),
                {
                    "id": uuid.uuid4(),
                    "aid": administratie_id,
                    "gid": scenario["zzper"],
                    "pid": scenario["p1"],
                    "jaar": jaar,
                    "week": week,
                    "door": beheerder_id,
                },
            )
        lijst = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, administratie_id=administratie_id)
        per_project = {r.project_id: r for r in lijst.rijen}
        assert per_project[scenario["p1"]].weekstaten.ontbrekend == 0
        assert "weekstaat_ontbreekt" not in per_project[scenario["p1"]].signalen
        assert per_project[scenario["p2"]].weekstaten.ontbrekend == 0 and per_project[scenario["p2"]].signalen == ()


class TestDetailVerrijking:
    def test_detail_draagt_verplichtingen_met_verbruiksbalk_en_weekstand(
        self, scenario, administratie_id, gescoopte_gebruiker
    ) -> None:
        r = client.get(
            f"/projecten/{administratie_id}/{scenario['p1']}", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert r.status_code == 200, r.text
        d = r.json()
        [v] = d["verplichtingen"]
        assert v["document_id"] == str(scenario["verplichting"])
        assert v["offertenummer"] == "OFF-1" and v["soort_label"] == "offerte" and v["omschrijving"] == "Steigerwerk"
        assert v["goedgekeurd_excl"] == "5000.00" and v["verbruikt_excl"] == "6000.00"
        assert v["percentage"] == 120 and v["over_excl"] == "1000.00" and v["status"] == "overschreden"
        assert v["open_facturen_aantal"] == 0
        ws = d["weekstaten_stand"]
        assert ws["van_toepassing"] is True
        assert ws["ontbrekend_totaal"] == 1 and ws["te_keuren_totaal"] == 1
        assert (ws["oudste_ontbrekende_jaar"], ws["oudste_ontbrekende_week"]) == scenario["vorige_week"]
        assert len(ws["weken"]) == kantoorbreed.WEKEN_IN_DETAIL
        # Nieuwste eerst: index 0 = lopende week, 1 = vorige week (gepland, ontbrekend),
        # 2 = twee weken terug (ingediend).
        weken = ws["weken"]
        assert (weken[1]["jaar"], weken[1]["weeknummer"]) == scenario["vorige_week"]
        assert weken[1]["gepland_personen"] == 1 and weken[1]["gepland_dagen"] == "1" and weken[1]["ontbrekend"] == 1
        assert (weken[2]["jaar"], weken[2]["weeknummer"]) == scenario["twee_weken"]
        assert weken[2]["ingediend"] == 1 and weken[2]["ontbrekend"] == 0
        assert weken[0]["ontbrekend"] == 0
        # Bestaande velden blijven staan (additief).
        assert d["naam"] == "26014 Breda (Moeskops)" and "staffels" in d and "prijsafspraken" in d

    def test_detail_zonder_uren_opt_in_meldt_niet_van_toepassing(
        self, scenario, tweede_administratie, beheerder_id
    ) -> None:
        r = client.get(
            f"/projecten/{tweede_administratie}/{scenario['p3']}", headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["verplichtingen"] == []
        assert d["weekstaten_stand"] == {
            "van_toepassing": False,
            "weken": [],
            "ontbrekend_totaal": 0,
            "te_keuren_totaal": 0,
            "oudste_ontbrekende_jaar": None,
            "oudste_ontbrekende_week": None,
        }

    def test_vervallen_verplichting_staat_als_historie_onderaan(
        self, admin_engine: Engine, scenario, administratie_id, beheerder_id
    ) -> None:
        doc = _verplichting(
            admin_engine, administratie_id, scenario["p1"], goedgekeurd="2000.00", verbruikt="0.00", nummer="OFF-2"
        )
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.verplichting SET vervallen_op = now(), vervallen_reden = 'ingetrokken' "
                    "WHERE document_id = :d"
                ),
                {"d": doc},
            )
        v = kantoorbreed.detail_verrijking(administratie_id=administratie_id, project_id=scenario["p1"])
        assert [x.status for x in v.verplichtingen] == ["overschreden", "vervallen"]
        # De lijst-chip telt de vervallen verplichting niet mee.
        lijst = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, administratie_id=administratie_id)
        chip = next(r for r in lijst.rijen if r.project_id == scenario["p1"]).verplichtingen
        assert chip.aantal == 1 and chip.goedgekeurd_excl == Decimal("5000.00")
