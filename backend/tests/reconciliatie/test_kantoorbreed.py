# ruff: noqa: F811 — pytest-fixtures als parameters
"""Inzicht › Reconciliatie kantoorbreed (opdracht 06-09 blok C): lijst uit de laatste afgeronde run
(urgentie-sortering, facetten, tellers), RLS-scope (een echte niet-Beheerder MÉT scope ziet alleen de
eigen administratie — RLS-les 25-08), handelingen via de bestaande schrijvers (accepteren/intrekken =
Beheerder; gezien = kantoorrol binnen scope, vervalt ná gezien_dagen, komt terug bij andere reden),
KPI-stand en "Nu draaien" (202 + status)."""

from __future__ import annotations

import argparse
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.berichten import mail
from app.db.models import GebruikerRol
from app.main import app
from app.reconciliatie import kantoorbreed
from app.reconciliatie import run as run_service
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie.run import vingerafdruk_opruim
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

client = TestClient(app)
ARGS = argparse.Namespace()
CONCEPT = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture(autouse=True)
def _geen_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: None)


@pytest.fixture
def tweede_administratie(admin_engine: Engine) -> uuid.UUID:
    """Actieve administratie BUITEN de scope van `gescoopte_gebruiker` (Beheerder ziet 'm wél)."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def _documenten_blok(afwijkingen_per_administratie: dict[uuid.UUID, list[tuple[uuid.UUID, str, str]]]):
    """Stub in de vorm van het echte documenten-blok: beoordeelt via de ÉCHTE acceptatie-service, zodat
    accepteren-in-de-UI in de volgende run als 'geaccepteerd' terugkomt."""

    def functie(args, verzamelaar=None) -> int:  # noqa: ANN001
        open_totaal = 0
        for aid, afwijkingen in afwijkingen_per_administratie.items():
            beoordeeld = acceptatie_service.beoordeel(bron="documenten", administratie_id=aid, afwijkingen=afwijkingen)
            for (record_id, soort, detail), b in zip(afwijkingen, beoordeeld, strict=True):
                open_totaal += b.telt_mee
                if verzamelaar is not None:
                    verzamelaar.bevinding(
                        soort="afwijking" if b.telt_mee else "geaccepteerd",
                        administratie_id=aid,
                        vingerafdruk=b.vingerafdruk,
                        tekst=f"document={record_id} soort={soort} [vaf:{b.vingerafdruk}]: {detail}",
                        detail={
                            "bron": "documenten",
                            "record_id": str(record_id),
                            "afwijking_soort": soort,
                            "detail": detail,
                            "geaccepteerd": not b.telt_mee,
                            "document_id": str(record_id),
                        },
                    )
        return 1 if open_totaal else 0

    return functie


def _opruim_blok(aid: uuid.UUID, *, reden: str = "gestorneerd"):
    def functie(args, verzamelaar=None) -> int:  # noqa: ANN001
        if verzamelaar is not None:
            verzamelaar.bevinding(
                soort="let_op",
                administratie_id=aid,
                vingerafdruk=vingerafdruk_opruim(kant="verkoop_bron", concept_administratie_id=aid, rlz_id=CONCEPT),
                tekst=f"LET-OP     opruim-kandidaat [{reden}] verkoop_bron {CONCEPT} in administratie {aid}",
                detail={
                    "kant": "verkoop_bron",
                    "rlz_id": str(CONCEPT),
                    "document_id": str(uuid.uuid4()),
                    "reden": reden,
                },
            )
        return 0

    return functie


def _draai(*blokken) -> None:
    run_service.voer_uit(blokken=list(blokken), args=ARGS, bron="cli", stdout=lambda t: None)


@pytest.fixture
def run_met_bevindingen(administratie_id, tweede_administratie, gescoopte_gebruiker, beheerder_id):
    """Eén afgeronde run: afwijking in de scope-administratie, afwijking in de andere, opruim-kandidaat in de scope."""
    afwijkingen = {
        administratie_id: [(uuid.uuid4(), "ontbreekt_in_rlz", "404 NotFound")],
        tweede_administratie: [(uuid.uuid4(), "bedrag_wijkt_af", "lokaal 100, RLZ 90")],
    }
    _draai(("documenten", _documenten_blok(afwijkingen)), ("doorbelasting", _opruim_blok(administratie_id)))
    return afwijkingen


class TestLijstEnScope:
    def test_beheerder_ziet_alles_boekhouder_alleen_eigen_scope(
        self, run_met_bevindingen, administratie_id, tweede_administratie, gescoopte_gebruiker, beheerder_id
    ) -> None:
        r = client.get("/reconciliatie/bevindingen", headers=_bearer(beheerder_id, rol="beheerder"))
        assert r.status_code == 200
        d = r.json()
        assert d["totaal"] == 3 and d["administraties_in_selectie"] == 2
        assert [x["soort"] for x in d["rijen"]] == [
            "afwijking",
            "afwijking",
            "let_op",
        ]  # urgentie: afwijking vóór let-op
        assert all(x["nieuw"] for x in d["rijen"])
        assert d["tellers"] == {
            "afwijkingen": 2,
            "let_op": 1,
            "fouten": 0,
            "geaccepteerd": 0,
            "uitgesloten": 0,
            "gezien": 0,
            "administraties": 2,
        }
        assert d["facetten"]["soort"]["aandacht"] == 3 and d["facetten"]["soort"]["let_op"] == 1
        assert {f["administratie_id"] for f in d["facetten"]["administraties"]} == {
            str(administratie_id),
            str(tweede_administratie),
        }
        assert d["laatste_run"]["status"] == "klaar"
        let_op = next(x for x in d["rijen"] if x["soort"] == "let_op")
        assert let_op["doel_pad"].startswith(f"/doorbelasting/{administratie_id}/")
        assert let_op["administratie_naam"]

        # RLS-les 25-08: échte niet-Beheerder MÉT scope — alleen de eigen administratie, nooit 'Andere BV'
        r2 = client.get("/reconciliatie/bevindingen", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["totaal"] == 2 and {x["administratie_id"] for x in d2["rijen"]} == {str(administratie_id)}
        assert d2["tellers"]["afwijkingen"] == 1
        # administratie-facet buiten scope = leeg, geen fout (filter, nooit poort)
        r3 = client.get(
            f"/reconciliatie/bevindingen?administratie_id={tweede_administratie}",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert r3.status_code == 200 and r3.json()["totaal"] == 0

    def test_facetten_zoek_en_paginering(self, run_met_bevindingen, administratie_id, beheerder_id) -> None:
        h = _bearer(beheerder_id, rol="beheerder")
        assert client.get("/reconciliatie/bevindingen?soort=let_op", headers=h).json()["totaal"] == 1
        assert client.get("/reconciliatie/bevindingen?soort=geaccepteerd", headers=h).json()["totaal"] == 0
        assert client.get("/reconciliatie/bevindingen?q=Andere BV", headers=h).json()["totaal"] == 1
        assert client.get("/reconciliatie/bevindingen?q=opruim-kandidaat", headers=h).json()["totaal"] == 1
        assert client.get("/reconciliatie/bevindingen?pagina=2", headers=h).json()["rijen"] == []
        assert client.get("/reconciliatie/bevindingen?soort=onzin", headers=h).status_code == 422

    def test_stand_kpi(self, run_met_bevindingen, gescoopte_gebruiker, beheerder_id) -> None:
        d = client.get("/reconciliatie/stand", headers=_bearer(beheerder_id, rol="beheerder")).json()
        assert d["teller"] == 3 and d["afwijkingen"] == 2 and d["let_op"] == 1 and d["laatste_run"]["exit_code"] == 1
        d2 = client.get("/reconciliatie/stand", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).json()
        assert d2["teller"] == 2

    def test_zonder_run_lege_lijst(self, beheerder_id) -> None:
        d = client.get("/reconciliatie/bevindingen", headers=_bearer(beheerder_id, rol="beheerder")).json()
        assert d["totaal"] == 0 and d["laatste_run"] is None
        assert client.get("/reconciliatie/stand", headers=_bearer(beheerder_id, rol="beheerder")).json()["teller"] == 0


class TestHandelingen:
    def test_accepteren_via_bestaande_schrijver_en_terug_als_geaccepteerd(
        self, run_met_bevindingen, administratie_id, gescoopte_gebruiker, beheerder_id
    ) -> None:
        h = _bearer(beheerder_id, rol="beheerder")
        rij = next(
            x
            for x in client.get("/reconciliatie/bevindingen", headers=h).json()["rijen"]
            if x["soort"] == "afwijking" and x["administratie_id"] == str(administratie_id)
        )
        # Boekhouding mag niet accepteren (Beheerder-only, zelfde regel als de CLI)
        r = client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/accepteren",
            json={"administratie_id": str(administratie_id), "reden": "kliktest, beoordeeld"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert r.status_code == 403
        # te korte reden
        r = client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/accepteren",
            json={"administratie_id": str(administratie_id), "reden": "ok"},
            headers=h,
        )
        assert r.status_code == 422
        r = client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/accepteren",
            json={
                "administratie_id": str(administratie_id),
                "reden": "kliktest-documenten na storno in de RLZ-UI opgeruimd",
            },
            headers=h,
        )
        assert r.status_code == 200
        acceptaties = acceptatie_service.actieve_acceptaties_overzicht(administratie_id=administratie_id)
        assert [a.vingerafdruk for a in acceptaties] == [rij["vingerafdruk"]]
        # tweede keer = 409 (al geaccepteerd — de bevinding van déze run zegt nog 'afwijking', de service weet beter)
        r = client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/accepteren",
            json={"administratie_id": str(administratie_id), "reden": "nog een keer, per ongeluk"},
            headers=h,
        )
        assert r.status_code in (200, 409)

        # volgende run: zelfde afwijking komt als 'geaccepteerd' terug mét reden/naam, KPI-teller daalt
        _draai(("documenten", _documenten_blok(run_met_bevindingen)), ("doorbelasting", _opruim_blok(administratie_id)))
        d = client.get("/reconciliatie/bevindingen?soort=geaccepteerd", headers=h).json()
        assert d["totaal"] == 1
        g = d["rijen"][0]
        assert g["acceptatie"]["reden"].startswith("kliktest-documenten") and g["acceptatie"]["geaccepteerd_door_naam"]
        assert g["nieuw"] is False  # vingerafdruk bestond al in de vorige run
        assert client.get("/reconciliatie/stand", headers=h).json()["teller"] == 2

        # intrekken → volgende run weer afwijking
        r = client.post(
            f"/reconciliatie/bevindingen/{g['id']}/intrekken",
            json={"administratie_id": str(administratie_id), "reden": "toch niet in orde"},
            headers=h,
        )
        assert r.status_code == 200
        _draai(("documenten", _documenten_blok(run_met_bevindingen)))
        assert client.get("/reconciliatie/stand", headers=h).json()["afwijkingen"] == 2

    def test_gezien_snooze_scope_vervaltermijn_en_andere_reden(
        self, run_met_bevindingen, administratie_id, tweede_administratie, gescoopte_gebruiker, beheerder_id
    ) -> None:
        hb = _bearer(gescoopte_gebruiker, rol="boekhouding")
        lijst = client.get("/reconciliatie/bevindingen?soort=let_op", headers=hb).json()
        rij = lijst["rijen"][0]
        # buiten scope = 403 (ook al bestaat de bevinding)
        r = client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/gezien",
            json={"administratie_id": str(tweede_administratie), "reden": "hoort niet bij mij"},
            headers=hb,
        )
        assert r.status_code == 403
        # afwijking is geen let-op → 422
        afw = next(
            x for x in client.get("/reconciliatie/bevindingen", headers=hb).json()["rijen"] if x["soort"] == "afwijking"
        )
        r = client.post(
            f"/reconciliatie/bevindingen/{afw['id']}/gezien",
            json={"administratie_id": str(administratie_id), "reden": "gezien hoor"},
            headers=hb,
        )
        assert r.status_code == 422
        # kantoorrol binnen scope mag 'Gezien'
        r = client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/gezien",
            json={
                "administratie_id": str(administratie_id),
                "reden": "concept blijft bewust staan tot kwartaalafsluiting",
            },
            headers=hb,
        )
        assert r.status_code == 200
        d = client.get("/reconciliatie/bevindingen?soort=alle", headers=hb).json()
        gezien = next(x for x in d["rijen"] if x["vingerafdruk"] == rij["vingerafdruk"])
        assert (
            gezien["soort"] == "gezien"
            and gezien["gezien"]["reden"].startswith("concept blijft")
            and gezien["gezien"]["gezien_door_naam"]
        )
        assert (
            client.get("/reconciliatie/bevindingen", headers=hb).json()["tellers"]["let_op"] == 0
        )  # uit de aandacht-lijst
        assert client.get("/reconciliatie/stand", headers=hb).json()["let_op"] == 0  # uit de KPI

        # volgende run: dezelfde kandidaat → géén nieuwe let-op in de mail-delta (gezien telt niet)
        verzonden: list[str] = []
        import pytest as _pt

        mp = _pt.MonkeyPatch()
        mp.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw["onderwerp"]))
        try:
            _draai(
                ("documenten", _documenten_blok(run_met_bevindingen)), ("doorbelasting", _opruim_blok(administratie_id))
            )
            assert verzonden == []  # ongewijzigd + gezien = geen mail
            # kandidaat komt met een ANDERE reden terug → telt weer als let-op én zit in de mail
            _draai(
                ("documenten", _documenten_blok(run_met_bevindingen)),
                ("doorbelasting", _opruim_blok(administratie_id, reden="gestorneerd+vervallen_run")),
            )
            assert len(verzonden) == 1
        finally:
            mp.undo()
        assert client.get("/reconciliatie/stand", headers=hb).json()["let_op"] == 1

        # vervaltermijn: Beheerder zet 1 dag; ná 2 dagen telt de snooze niet meer
        _draai(("doorbelasting", _opruim_blok(administratie_id)))
        hbeh = _bearer(beheerder_id, rol="beheerder")
        assert client.put("/reconciliatie/instelling", json={"gezien_dagen": 0}, headers=hbeh).status_code == 422
        assert client.put("/reconciliatie/instelling", json={"gezien_dagen": 1}, headers=hb).status_code == 403
        assert client.put("/reconciliatie/instelling", json={"gezien_dagen": 1}, headers=hbeh).json() == {
            "gezien_dagen": 1
        }
        assert client.get("/reconciliatie/instelling", headers=hb).json() == {"gezien_dagen": 1}
        nu = datetime.now(UTC)
        assert kantoorbreed.stand(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, nu=nu).let_op == 0
        assert (
            kantoorbreed.stand(
                actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, nu=nu + timedelta(days=2)
            ).let_op
            == 1
        )

        # 'Toch tonen' = gezien-intrekken
        rij2 = client.get("/reconciliatie/bevindingen?soort=gezien", headers=hb).json()["rijen"][0]
        r = client.post(
            f"/reconciliatie/bevindingen/{rij2['id']}/gezien-intrekken",
            json={"administratie_id": str(administratie_id), "reden": "toch opruimen deze week"},
            headers=hb,
        )
        assert r.status_code == 200
        assert client.get("/reconciliatie/stand", headers=hb).json()["let_op"] == 1

    def test_nu_draaien_202_en_status(self, beheerder_id, gescoopte_gebruiker, monkeypatch) -> None:
        monkeypatch.setattr(run_service, "_start_voertuig", lambda: None)
        assert (
            client.post("/reconciliatie/run", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code
            == 403
        )
        r = client.post("/reconciliatie/run", headers=_bearer(beheerder_id, rol="beheerder"))
        assert r.status_code == 202
        d = r.json()
        assert d["status"] == "wachtend" and d["bron"] == "handmatig"
        s = client.get(f"/reconciliatie/run/{d['run_id']}", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert s.status_code == 200 and s.json()["status"] == "wachtend"
        assert (
            client.get("/reconciliatie/run/laatste", headers=_bearer(beheerder_id, rol="beheerder")).json()["run_id"]
            == d["run_id"]
        )
        assert (
            client.get(f"/reconciliatie/run/{uuid.uuid4()}", headers=_bearer(beheerder_id, rol="beheerder")).status_code
            == 404
        )
        # de job (of dev-thread) claimt de wachtende rij
        _draai(("documenten", _documenten_blok({})))
        assert (
            client.get(f"/reconciliatie/run/{d['run_id']}", headers=_bearer(beheerder_id, rol="beheerder")).json()[
                "status"
            ]
            == "klaar"
        )


class TestAcceptatieDirectZichtbaar:
    """BUGFIX 07-09 (blok A8, opdracht Peter): een geaccepteerde afwijking bleef tot de VOLGENDE run in
    "aandacht nodig" staan (de lijst las `soort` uit de opgeslagen bevinding). Nu volgt de lijst — én de
    KPI-stand — de LIVE acceptatie-stand: accepteren → direct facet geaccepteerd; intrekken → direct terug."""

    def test_accepteren_en_intrekken_zonder_nieuwe_run(
        self, run_met_bevindingen, administratie_id, gescoopte_gebruiker, beheerder_id
    ) -> None:
        hb = _bearer(beheerder_id, rol="beheerder")
        hs = _bearer(gescoopte_gebruiker, rol="boekhouding")  # RLS-les: echte niet-Beheerder MÉT scope
        rij = next(
            x
            for x in client.get("/reconciliatie/bevindingen", headers=hb).json()["rijen"]
            if x["soort"] == "afwijking" and x["administratie_id"] == str(administratie_id)
        )
        assert client.get("/reconciliatie/stand", headers=hb).json()["afwijkingen"] == 2
        assert client.get("/reconciliatie/stand", headers=hs).json()["afwijkingen"] == 1

        r = client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/accepteren",
            json={"administratie_id": str(administratie_id), "reden": "testboeking, in de RLZ-UI opgeruimd"},
            headers=hb,
        )
        assert r.status_code == 200

        # DIRECT (zonder nieuwe run): uit "aandacht nodig", in "geaccepteerd" — voor Beheerder én scoped gebruiker.
        for h, verwacht_aandacht in ((hb, 1), (hs, 0)):
            aandacht = client.get("/reconciliatie/bevindingen", headers=h).json()
            assert rij["vingerafdruk"] not in {x["vingerafdruk"] for x in aandacht["rijen"]}
            assert aandacht["tellers"]["afwijkingen"] == verwacht_aandacht
            assert aandacht["tellers"]["geaccepteerd"] == 1
            assert aandacht["facetten"]["soort"]["geaccepteerd"] == 1
            geaccepteerd = client.get("/reconciliatie/bevindingen?soort=geaccepteerd", headers=h).json()
            assert [x["vingerafdruk"] for x in geaccepteerd["rijen"]] == [rij["vingerafdruk"]]
            g = geaccepteerd["rijen"][0]
            assert g["soort"] == "geaccepteerd" and g["id"] == rij["id"]  # dezelfde bevinding-rij, live omgezet
            assert g["acceptatie"]["reden"].startswith("testboeking") and g["acceptatie"]["geaccepteerd_door_naam"]
            assert "intrekken" in g["doe"].lower()
        assert client.get("/reconciliatie/stand", headers=hb).json()["afwijkingen"] == 1
        assert client.get("/reconciliatie/stand", headers=hs).json()["afwijkingen"] == 0

        # nog eens accepteren = 409 (live-stand), niet stil 200
        r = client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/accepteren",
            json={"administratie_id": str(administratie_id), "reden": "per ongeluk nog een keer"},
            headers=hb,
        )
        assert r.status_code == 409

        # intrekken → DIRECT weer afwijking in "aandacht nodig", KPI terug omhoog
        r = client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/intrekken",
            json={"administratie_id": str(administratie_id), "reden": "toch niet in orde"},
            headers=hb,
        )
        assert r.status_code == 200
        aandacht = client.get("/reconciliatie/bevindingen", headers=hs).json()
        terug = next(x for x in aandacht["rijen"] if x["vingerafdruk"] == rij["vingerafdruk"])
        assert terug["soort"] == "afwijking" and terug["acceptatie"] is None
        assert aandacht["tellers"]["geaccepteerd"] == 0
        assert client.get("/reconciliatie/stand", headers=hs).json()["afwijkingen"] == 1
        assert client.get("/reconciliatie/bevindingen?soort=geaccepteerd", headers=hb).json()["totaal"] == 0

        # opnieuw accepteren ná intrekken kan zonder nieuwe run (geen stale "al geaccepteerd" uit de snapshot)
        r = client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/accepteren",
            json={"administratie_id": str(administratie_id), "reden": "alsnog beoordeeld en akkoord"},
            headers=hb,
        )
        assert r.status_code == 200
        assert client.get("/reconciliatie/stand", headers=hs).json()["afwijkingen"] == 0

    def test_opgeslagen_geaccepteerd_na_intrekken_direct_afwijking(
        self, run_met_bevindingen, administratie_id, gescoopte_gebruiker, beheerder_id
    ) -> None:
        """Omgekeerde richting: de run legde de rij al als 'geaccepteerd' vast; intrekken zet 'm live terug."""
        hb = _bearer(beheerder_id, rol="beheerder")
        rij = next(
            x
            for x in client.get("/reconciliatie/bevindingen", headers=hb).json()["rijen"]
            if x["soort"] == "afwijking" and x["administratie_id"] == str(administratie_id)
        )
        client.post(
            f"/reconciliatie/bevindingen/{rij['id']}/accepteren",
            json={"administratie_id": str(administratie_id), "reden": "kliktest, beoordeeld"},
            headers=hb,
        )
        _draai(("documenten", _documenten_blok(run_met_bevindingen)))
        g = client.get("/reconciliatie/bevindingen?soort=geaccepteerd", headers=hb).json()["rijen"][0]
        assert g["soort"] == "geaccepteerd"
        r = client.post(
            f"/reconciliatie/bevindingen/{g['id']}/intrekken",
            json={"administratie_id": str(administratie_id), "reden": "toch niet in orde"},
            headers=hb,
        )
        assert r.status_code == 200
        hs = _bearer(gescoopte_gebruiker, rol="boekhouding")
        aandacht = client.get("/reconciliatie/bevindingen", headers=hs).json()
        assert g["vingerafdruk"] in {x["vingerafdruk"] for x in aandacht["rijen"] if x["soort"] == "afwijking"}
        assert client.get("/reconciliatie/stand", headers=hs).json()["afwijkingen"] == 1


class TestLeesbareLaag:
    def test_dto_draagt_titel_wat_doe_details_en_zoekt_op_namen(
        self, run_met_bevindingen, administratie_id, beheerder_id
    ) -> None:
        h = _bearer(beheerder_id, rol="beheerder")
        d = client.get("/reconciliatie/bevindingen?soort=alle", headers=h).json()
        for x in d["rijen"]:
            assert x["titel"] and x["wat"] and x["doe"], x
            assert len(x["titel"]) <= 60
            for zin in (x["titel"], x["wat"], x["doe"]):
                assert "[vaf:" not in zin and str(administratie_id) not in zin, zin
            assert x["details"][0] == {"label": "vingerafdruk", "waarde": x["vingerafdruk"]}
            assert any(r["label"] == "ruwe regel" and r["waarde"] == x["tekst"] for r in x["details"])
            assert x["tekst"]  # CLI-regel blijft beschikbaar
        weg = next(x for x in d["rijen"] if (x["detail"] or {}).get("afwijking_soort") == "ontbreekt_in_rlz")
        assert weg["titel"].startswith("RLZ-document verdwenen")
        assert "Boek opnieuw via de actie op deze rij" in weg["doe"]
        let_op = next(x for x in d["rijen"] if x["soort"] == "let_op")
        assert let_op["titel"].startswith("Achtergebleven concept in RLZ") and "Scope-test" in let_op["titel"]
        # zoeken op de leesbare tekst (niet alleen de CLI-regel)
        assert client.get("/reconciliatie/bevindingen?q=verdwenen", headers=h).json()["totaal"] == 1
        # urgentie binnen afwijkingen: ontbreekt_in_rlz vóór bedrag_wijkt_af
        soorten = [(x["detail"] or {}).get("afwijking_soort") for x in d["rijen"] if x["soort"] == "afwijking"]
        assert soorten == ["ontbreekt_in_rlz", "bedrag_wijkt_af"]
