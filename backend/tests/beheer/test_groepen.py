# ruff: noqa: F811 — pytest-fixtures als parameters
"""Groepskenmerk op administratie (blok 8 run 11-09 middag, opdracht Peter 11-09; migratie 0135).

Service (code-voorstel, aanmaken, hernoemen/archiveren, toekennen mét audit oud→nieuw), router (Beheerder-only muteren,
kantoorrol lezen), RLS (een echte niet-Beheerder MÉT scope leest groepen maar kan er op DB-niveau geen aanmaken — de
router-poort is dus niet de enige laag), DTO-zichtbaarheid (GET /auth/administraties voor iedereen met scope;
instellingen-lijst voor de Beheerder) en het filter op de klantenlijst-route."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import groepen
from app.beheer import service as beheer_service
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _audit(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT record_id, oude_waarde, nieuwe_waarde FROM platform.audit_event "
                "WHERE actie = :a ORDER BY tijdstip"
            ),
            {"a": actie},
        ).mappings()
        return [dict(r) for r in rijen]


class TestCodeVoorstel:
    @pytest.mark.parametrize(
        ("naam", "verwacht"),
        [
            ("Kempen groep", "KEMPENGROEP"),
            ("Jansen & Zn.", "JANSENZN"),
            ("Café Ünïcode 2026", "CAFEUNICODE2"),  # 12-tekens-afkap
            ("Vastgoedgroep Nederland Holding", "VASTGOEDGROE"),
            ("X", ""),  # te kort → leeg voorstel, de UI vraagt zelf om een code
        ],
    )
    def test_deterministisch_uit_de_naam(self, naam: str, verwacht: str) -> None:
        assert groepen.code_voorstel(naam) == verwacht

    def test_normaliseer_neemt_invoer_boven_voorstel_en_weigert_buiten_patroon(self) -> None:
        assert groepen.normaliseer_code(" kg ", naam="Kempen groep") == "KG"
        assert groepen.normaliseer_code(None, naam="Kempen groep") == "KEMPENGROEP"
        with pytest.raises(groepen.GroepOngeldig):
            groepen.normaliseer_code("K-G", naam="Kempen groep")
        with pytest.raises(groepen.GroepOngeldig):
            groepen.normaliseer_code(None, naam="X")


class TestService:
    def test_aanmaken_hernoemen_archiveren_met_audit(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        g = groepen.maak_groep(actor_id=beheerder_id, naam="  Kempen   groep ")
        assert (g.naam, g.code, g.actief, g.aantal_administraties) == ("Kempen groep", "KEMPENGROEP", True, 0)
        aangemaakt = _audit(admin_engine, "groep_aangemaakt")
        assert len(aangemaakt) == 1 and aangemaakt[0]["nieuwe_waarde"]["code"] == "KEMPENGROEP"

        g2 = groepen.wijzig_groep(actor_id=beheerder_id, groep_id=g.id, naam="Kempen Groep B.V.", actief=False)
        assert (g2.naam, g2.actief, g2.code) == ("Kempen Groep B.V.", False, "KEMPENGROEP")  # code onveranderlijk
        gewijzigd = _audit(admin_engine, "groep_gewijzigd")
        assert gewijzigd[0]["oude_waarde"] == {"naam": "Kempen groep", "actief": True}
        assert gewijzigd[0]["nieuwe_waarde"] == {"naam": "Kempen Groep B.V.", "actief": False}
        # Gearchiveerd blijft zichtbaar in de volledige lijst, niet in de actieve.
        assert [x.id for x in groepen.lijst_groepen()] == [g.id]
        assert groepen.lijst_groepen(inclusief_gearchiveerd=False) == []

    def test_code_uniek_ook_over_gearchiveerde_groepen(self, beheerder_id: uuid.UUID) -> None:
        g = groepen.maak_groep(actor_id=beheerder_id, naam="Kempen groep", code="KG")
        groepen.wijzig_groep(actor_id=beheerder_id, groep_id=g.id, actief=False)
        with pytest.raises(groepen.GroepCodeBezet):
            groepen.maak_groep(actor_id=beheerder_id, naam="Andere", code="kg")

    def test_lege_naam_of_onbekende_groep(self, beheerder_id: uuid.UUID) -> None:
        with pytest.raises(groepen.GroepOngeldig):
            groepen.maak_groep(actor_id=beheerder_id, naam="   ")
        with pytest.raises(groepen.GroepOnbekend):
            groepen.wijzig_groep(actor_id=beheerder_id, groep_id=uuid.uuid4(), naam="x")

    def test_toekennen_wissen_en_audit_oud_naar_nieuw(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        kg = groepen.maak_groep(actor_id=beheerder_id, naam="Kempen groep")
        vgg = groepen.maak_groep(actor_id=beheerder_id, naam="Vastgoedgroep", code="VGG")

        r1 = groepen.zet_administratie_groep(actor_id=beheerder_id, administratie_id=administratie_id, groep_id=kg.id)
        assert r1 is not None and r1.id == kg.id and r1.aantal_administraties == 1
        r2 = groepen.zet_administratie_groep(actor_id=beheerder_id, administratie_id=administratie_id, groep_id=vgg.id)
        assert r2 is not None and r2.code == "VGG"
        assert (
            groepen.zet_administratie_groep(actor_id=beheerder_id, administratie_id=administratie_id, groep_id=None)
            is None
        )

        sporen = _audit(admin_engine, "administratie_groep_gewijzigd")
        assert [s["record_id"] for s in sporen] == [administratie_id] * 3
        assert (
            sporen[0]["oude_waarde"]["groep_id"] is None and sporen[0]["nieuwe_waarde"]["groep_code"] == "KEMPENGROEP"
        )
        assert (
            sporen[1]["oude_waarde"]["groep_code"] == "KEMPENGROEP"
            and sporen[1]["nieuwe_waarde"]["groep_naam"] == "Vastgoedgroep"
        )
        assert sporen[2]["oude_waarde"]["groep_code"] == "VGG" and sporen[2]["nieuwe_waarde"]["groep_id"] is None
        # Ledental telt alleen actieve leden; hoogstens één groep per administratie (de kolom is één FK).
        assert groepen.administratie_ids_in_groep(kg.id) == set()
        assert groepen.administratie_ids_in_groep(vgg.id) == set()

    def test_gearchiveerde_groep_niet_toekenbaar_maar_lid_blijft_lid(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        g = groepen.maak_groep(actor_id=beheerder_id, naam="Kempen groep")
        groepen.zet_administratie_groep(actor_id=beheerder_id, administratie_id=administratie_id, groep_id=g.id)
        groepen.wijzig_groep(actor_id=beheerder_id, groep_id=g.id, actief=False)
        with pytest.raises(groepen.GroepGearchiveerd):
            groepen.zet_administratie_groep(actor_id=beheerder_id, administratie_id=administratie_id, groep_id=g.id)
        # Bestaande leden houden hun groep — de instellingen-lijst toont 'm als gearchiveerd.
        rij = next(
            r for r in beheer_service.overzicht_administratie_instellingen() if r.administratie_id == administratie_id
        )
        assert (rij.groep_id, rij.groep_naam, rij.groep_code, rij.groep_actief) == (
            g.id,
            "Kempen groep",
            "KEMPENGROEP",
            False,
        )
        assert groepen.administratie_ids_in_groep(g.id) == {administratie_id}

    def test_onbekende_administratie_of_groep(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        with pytest.raises(groepen.GroepOnbekend):
            groepen.zet_administratie_groep(
                actor_id=beheerder_id, administratie_id=administratie_id, groep_id=uuid.uuid4()
            )
        with pytest.raises(beheer_service.BeheerFout):
            groepen.zet_administratie_groep(actor_id=beheerder_id, administratie_id=uuid.uuid4(), groep_id=None)


class TestRls:
    """Conventies §RLS punt 6: de app-rol (boekhouding_app, FORCE RLS) — geen owner-test."""

    def test_niet_beheerder_leest_groepen_maar_kan_er_geen_aanmaken_op_db_niveau(
        self, beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        groepen.maak_groep(actor_id=beheerder_id, naam="Kempen groep")
        assert [g.code for g in groepen.lijst_groepen()] == ["KEMPENGROEP"]
        # De servicelaag zelf, mét een echte niet-Beheerder als actor: de INSERT-policy weigert (router-poort is dus
        # niet de enige laag). SQLAlchemy vertaalt de RLS-weigering naar een DB-fout.
        with pytest.raises(Exception, match="row-level security|policy"):
            groepen.maak_groep(actor_id=gescoopte_gebruiker, naam="Smokkel", code="SMOK")
        # UPDATE: de USING-policy laat de rij niet zien → 0 rijen geraakt (StaleDataError) — niets gewijzigd.
        with pytest.raises(Exception, match="row-level security|policy|0 were matched"):
            groepen.wijzig_groep(actor_id=gescoopte_gebruiker, groep_id=groepen.lijst_groepen()[0].id, naam="Gekaapt")
        assert [g.naam for g in groepen.lijst_groepen()] == ["Kempen groep"]


class TestRouter:
    def test_kantoorrol_leest_beheerder_muteert(
        self, beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        bh = _bearer(beheerder_id, rol="beheerder")
        bk = _bearer(gescoopte_gebruiker, rol="boekhouding")

        assert client.post("/groepen", headers=bk, json={"naam": "Kempen groep"}).status_code == 403
        r = client.post("/groepen", headers=bh, json={"naam": "Kempen groep"})
        assert r.status_code == 201, r.text
        g = r.json()
        assert (g["naam"], g["code"], g["actief"], g["aantal_administraties"]) == (
            "Kempen groep",
            "KEMPENGROEP",
            True,
            0,
        )
        assert client.post("/groepen", headers=bh, json={"naam": "Dubbel", "code": "KEMPENGROEP"}).status_code == 409
        assert client.post("/groepen", headers=bh, json={"naam": "Fout", "code": "k-g"}).status_code == 422

        # Lezen mag élke kantoorrol (filter-keuzelijst).
        lijst = client.get("/groepen", headers=bk)
        assert lijst.status_code == 200 and [x["code"] for x in lijst.json()["groepen"]] == ["KEMPENGROEP"]

        assert (
            client.put(f"/administraties/{administratie_id}/groep", headers=bk, json={"groep_id": g["id"]}).status_code
            == 403
        )
        r = client.put(f"/administraties/{administratie_id}/groep", headers=bh, json={"groep_id": g["id"]})
        assert r.status_code == 200, r.text
        assert r.json() == {"groep_id": g["id"], "groep_naam": "Kempen groep", "groep_code": "KEMPENGROEP"}
        assert (
            client.put(
                f"/administraties/{administratie_id}/groep", headers=bh, json={"groep_id": str(uuid.uuid4())}
            ).status_code
            == 404
        )
        assert (
            client.put(f"/administraties/{uuid.uuid4()}/groep", headers=bh, json={"groep_id": None}).status_code == 404
        )

        # Zichtbaar in de administratie-DTO voor iedereen met scope én in de Beheerder-lijst.
        mijn = client.get("/auth/administraties", headers=bk).json()["administraties"]
        rij = next(a for a in mijn if a["id"] == str(administratie_id))
        assert (rij["groep_id"], rij["groep_naam"]) == (g["id"], "Kempen groep")
        inst = client.get("/instellingen/administraties", headers=bh).json()["administraties"]
        rij = next(a for a in inst if a["id"] == str(administratie_id))
        assert (rij["groep_id"], rij["groep_naam"], rij["groep_code"], rij["groep_actief"]) == (
            g["id"],
            "Kempen groep",
            "KEMPENGROEP",
            True,
        )

        # Archiveren (nooit verwijderen) → toekennen = 409, ledental blijft.
        assert client.put(f"/groepen/{g['id']}", headers=bk, json={"actief": False}).status_code == 403
        r = client.put(f"/groepen/{g['id']}", headers=bh, json={"actief": False, "naam": "Kempen Groep"})
        assert r.status_code == 200 and r.json()["actief"] is False and r.json()["aantal_administraties"] == 1
        assert (
            client.put(f"/administraties/{administratie_id}/groep", headers=bh, json={"groep_id": g["id"]}).status_code
            == 409
        )
        assert client.put(f"/groepen/{uuid.uuid4()}", headers=bh, json={"naam": "x"}).status_code == 404
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM platform.groep")).scalar_one() == 1

    def test_wissen_geeft_lege_dto(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        bh = _bearer(beheerder_id, rol="beheerder")
        r = client.put(f"/administraties/{administratie_id}/groep", headers=bh, json={"groep_id": None})
        assert r.status_code == 200 and r.json() == {"groep_id": None, "groep_naam": None, "groep_code": None}


class TestKlantenlijstFilter:
    def test_groep_id_filtert_de_klantenlijst_op_de_administratie_set(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Kernprincipe 7: administratie is een FILTER; de groep is er één meer. Onbekende groep = lege lijst,
        geen fout.
        Router-hunk in documenten/router.py::werkvoorraad_overzicht (vóór de service-call) — de gouden set dekt dezelfde
        route met échte documenten (tests/keten/test_t_groep_filter_klantenlijst.py)."""
        ander = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV', :rlz)"),
                {"id": ander, "rlz": f"rlz-{ander}"},
            )
        bh = _bearer(beheerder_id, rol="beheerder")
        g = client.post("/groepen", headers=bh, json={"naam": "Kempen groep"}).json()
        client.put(f"/administraties/{administratie_id}/groep", headers=bh, json={"groep_id": g["id"]})

        alles = client.get("/werkvoorraad/overzicht", headers=bh).json()["klanten"]
        assert {k["administratie_id"] for k in alles} == {str(administratie_id), str(ander)}
        gefilterd = client.get("/werkvoorraad/overzicht", params={"groep_id": g["id"]}, headers=bh).json()["klanten"]
        assert [k["administratie_id"] for k in gefilterd] == [str(administratie_id)]
        leeg = client.get("/werkvoorraad/overzicht", params={"groep_id": str(uuid.uuid4())}, headers=bh)
        assert leeg.status_code == 200 and leeg.json()["klanten"] == []
