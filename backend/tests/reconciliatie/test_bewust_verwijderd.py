# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Acceptatie "Bewust verwijderd in Reeleezee (dubbel/test)" op `ontbreekt_in_rlz` (blok D 16-09, opdracht Peter;
casus Kempen Facilities). Eén klik = (1) acceptatie-rij mét de vaste reden + audit `reconciliatie_afwijking_geaccepteerd`,
(2) document van geboekt naar `afgevoerd_duplicaat` mét tijdlijnregel "In Reeleezee verwijderd door <naam> … boekstuk …"
(marker `bewust_verwijderd`) + audit `document_bewust_verwijderd_afgevoerd`; boekstuknummer blijft staan. Geen
Afwijzing-rij: de DB-CHECK `afwijzing_herkomst_herstelbaar` verbiedt herkomst `geboekt` (geen migratie in dit blok).
Terugweg = `herstel_bewust_verwijderd` → geboekt + acceptatie ingetrokken; een gewone duplicaat-afvoer is NIET zo te
herstellen. Poorten: verkeerde soort = fout, niet-Beheerder = fout; routes 200/403/404/409/422."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.models import GebruikerRol
from app.documenten.models import DocumentStatus
from app.documenten.rlz_ids import rlz_herboeking_id
from app.main import app
from app.reconciliatie import bewust_verwijderd
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.reconciliatie.test_opnieuw_boeken_endpoint import (  # noqa: F401
    _bearer,
    _bevinding_id,
    _geen_mail,
    _run_met,
    _status,
    geboekt,
)
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)


def _bevinding_uuid(beheerder_id: uuid.UUID) -> uuid.UUID:
    return uuid.UUID(_bevinding_id(_bearer(beheerder_id, rol="beheerder")))


def _boekstuknummer(admin_engine: Engine, document_id: uuid.UUID) -> str | None:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT rlz_boekstuknummer FROM boekhouding.boekvoorstel WHERE document_id = :id"), {"id": document_id}
        ).scalar_one()


def _jongste_tijdlijn(admin_engine: Engine, document_id: uuid.UUID) -> tuple[str | None, str, dict]:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT van_status, naar_status, detail FROM boekhouding.document_gebeurtenis "
                "WHERE document_id = :id ORDER BY tijdstip DESC, id DESC LIMIT 1"
            ),
            {"id": document_id},
        ).first()
    assert rij is not None
    return rij[0], rij[1], rij[2]


def _audit_aantal(admin_engine: Engine, actie: str) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM platform.audit_event WHERE actie = :a"), {"a": actie}).scalar_one()


class TestService:
    def test_happy_path_accepteert_en_voert_document_af(self, geboekt, administratie_id, beheerder_id, admin_engine) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]  # door Peter zelf in de RLZ-UI verwijderd (dubbel)
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "GET PurchaseInvoices/x -> 404: NotFound")
        boekstuk_voor = _boekstuknummer(admin_engine, document_id)
        assert boekstuk_voor  # het geboekte document draagt een boekstuknummer

        r = bewust_verwijderd.accepteer_bewust_verwijderd(
            bevinding_id=_bevinding_uuid(beheerder_id),
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            rol=GebruikerRol.BEHEERDER,
        )
        assert r.document_id == document_id
        assert r.document_status_gewijzigd is True and r.document_status_nieuw == "afgevoerd_duplicaat"
        assert r.boekstuknummer == boekstuk_voor and r.reden == bewust_verwijderd.VASTE_REDEN

        with admin_engine.connect() as conn:
            acc = conn.execute(
                text("SELECT reden FROM boekhouding.reconciliatie_acceptatie WHERE id = :id AND ingetrokken_op IS NULL"),
                {"id": r.acceptatie_id},
            ).scalar_one()
        assert acc == bewust_verwijderd.VASTE_REDEN
        assert _audit_aantal(admin_engine, "reconciliatie_afwijking_geaccepteerd") == 1
        assert _audit_aantal(admin_engine, bewust_verwijderd.AUDIT_AFGEVOERD) == 1
        assert _status(admin_engine, document_id) == "afgevoerd_duplicaat"
        # Boekstuknummer blijft als historie staan — niets gewist.
        assert _boekstuknummer(admin_engine, document_id) == boekstuk_voor
        # Tijdlijnregel: geboekt → afgevoerd_duplicaat mét leesbare reden (naam + boekstuk) en de marker.
        van, naar, detail = _jongste_tijdlijn(admin_engine, document_id)
        assert (van, naar) == ("geboekt", "afgevoerd_duplicaat")
        assert detail[bewust_verwijderd.TIJDLIJN_MARKER] is True and detail["acceptatie_id"] == str(r.acceptatie_id)
        assert "In Reeleezee verwijderd door" in detail["reden"] and boekstuk_voor in detail["reden"] and "dubbel/test" in detail["reden"]
        assert detail["rlz_boekstuknummer"] == boekstuk_voor
        # De bevinding staat nu onder "geaccepteerd" mét de vaste reden.
        lijst = client.get("/reconciliatie/bevindingen?soort=geaccepteerd", headers=_bearer(beheerder_id, rol="beheerder")).json()
        [rij] = lijst["rijen"]
        assert rij["acceptatie"]["reden"] == bewust_verwijderd.VASTE_REDEN

    def test_toelichting_reist_mee_in_beide_redenen(self, geboekt, administratie_id, beheerder_id, admin_engine) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "404")
        r = bewust_verwijderd.accepteer_bewust_verwijderd(
            bevinding_id=_bevinding_uuid(beheerder_id),
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            rol=GebruikerRol.BEHEERDER,
            toelichting="  TEST-exemplaar uit de kliktest  ",
        )
        assert r.reden == f"{bewust_verwijderd.VASTE_REDEN} — TEST-exemplaar uit de kliktest"
        _van, _naar, detail = _jongste_tijdlijn(admin_engine, document_id)
        assert detail["reden"].endswith("— TEST-exemplaar uit de kliktest")

    def test_herstel_zet_document_terug_op_geboekt_en_trekt_acceptatie_in(self, geboekt, administratie_id, beheerder_id, admin_engine) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "404")
        r = bewust_verwijderd.accepteer_bewust_verwijderd(
            bevinding_id=_bevinding_uuid(beheerder_id), administratie_id=administratie_id, actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER
        )
        assert _status(admin_engine, document_id) == "afgevoerd_duplicaat"
        with pytest.raises(bewust_verwijderd.BewustVerwijderdFout, match="inhoudelijke reden"):
            bewust_verwijderd.herstel_bewust_verwijderd(
                administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, reden="ok"
            )
        h = bewust_verwijderd.herstel_bewust_verwijderd(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER,
            reden="toch niet dubbel — stuk hoort in RLZ",
        )
        assert h.document_status_nieuw == DocumentStatus.GEBOEKT.value and h.acceptatie_ingetrokken_id == r.acceptatie_id
        assert _status(admin_engine, document_id) == "geboekt"
        assert _audit_aantal(admin_engine, bewust_verwijderd.AUDIT_HERSTELD) == 1
        with admin_engine.connect() as conn:
            ingetrokken = conn.execute(
                text("SELECT ingetrokken_op IS NOT NULL FROM boekhouding.reconciliatie_acceptatie WHERE id = :id"), {"id": r.acceptatie_id}
            ).scalar_one()
        assert ingetrokken is True
        # Tweede keer: het document staat niet meer op afgevoerd_duplicaat → niet terugdraaibaar.
        with pytest.raises(bewust_verwijderd.NietTerugdraaibaar):
            bewust_verwijderd.herstel_bewust_verwijderd(
                administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, reden="nog een keer"
            )

    def test_andere_soort_is_fout_en_laat_niets_achter(self, geboekt, administratie_id, beheerder_id, admin_engine) -> None:
        document_id, _fake = geboekt
        _run_met(administratie_id, document_id, "bedrag_wijkt_af", "eigen=€121.00 rlz=€120.00")
        with pytest.raises(bewust_verwijderd.VerkeerdeSoort, match="verdwenen"):
            bewust_verwijderd.accepteer_bewust_verwijderd(
                bevinding_id=_bevinding_uuid(beheerder_id), administratie_id=administratie_id, actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER
            )
        assert _status(admin_engine, document_id) == "geboekt"
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM boekhouding.reconciliatie_acceptatie")).scalar_one() == 0

    def test_niet_beheerder_is_fout(self, geboekt, administratie_id, beheerder_id, gescoopte_gebruiker, admin_engine) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "404")
        with pytest.raises(bewust_verwijderd.GeenToegang, match="Beheerder"):
            bewust_verwijderd.accepteer_bewust_verwijderd(
                bevinding_id=_bevinding_uuid(beheerder_id), administratie_id=administratie_id, actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING
            )
        assert _status(admin_engine, document_id) == "geboekt"

    def test_tweede_keer_is_al_geaccepteerd(self, geboekt, administratie_id, beheerder_id) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "404")
        bid = _bevinding_uuid(beheerder_id)
        bewust_verwijderd.accepteer_bewust_verwijderd(bevinding_id=bid, administratie_id=administratie_id, actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER)
        with pytest.raises(bewust_verwijderd.BewustVerwijderdFout, match="al geaccepteerd"):
            bewust_verwijderd.accepteer_bewust_verwijderd(bevinding_id=bid, administratie_id=administratie_id, actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER)


class TestRoute:
    def test_beheerder_200_en_tweede_keer_409(self, geboekt, administratie_id, beheerder_id, admin_engine) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "404")
        h = _bearer(beheerder_id, rol="beheerder")
        bid = _bevinding_id(h)
        r = client.post(
            f"/reconciliatie/bevindingen/{bid}/bewust-verwijderd",
            json={"administratie_id": str(administratie_id), "toelichting": "dubbel geboekt"},
            headers=h,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["document_id"] == str(document_id) and d["document_status_nieuw"] == "afgevoerd_duplicaat"
        assert d["document_status_gewijzigd"] is True and d["boekstuknummer"] == _boekstuknummer(admin_engine, document_id)
        assert d["reden"] == f"{bewust_verwijderd.VASTE_REDEN} — dubbel geboekt"
        assert _status(admin_engine, document_id) == "afgevoerd_duplicaat"
        r = client.post(f"/reconciliatie/bevindingen/{bid}/bewust-verwijderd", json={"administratie_id": str(administratie_id)}, headers=h)
        assert r.status_code == 409 and "al geaccepteerd" in r.json()["detail"]

    def test_toelichting_te_lang_422(self, geboekt, administratie_id, beheerder_id) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "404")
        h = _bearer(beheerder_id, rol="beheerder")
        r = client.post(
            f"/reconciliatie/bevindingen/{_bevinding_id(h)}/bewust-verwijderd",
            json={"administratie_id": str(administratie_id), "toelichting": "x" * 501},
            headers=h,
        )
        assert r.status_code == 422

    def test_andere_soort_422_en_onbekend_404(self, geboekt, administratie_id, beheerder_id) -> None:
        document_id, _fake = geboekt
        _run_met(administratie_id, document_id, "bedrag_wijkt_af", "eigen=€121.00 rlz=€120.00")
        h = _bearer(beheerder_id, rol="beheerder")
        r = client.post(f"/reconciliatie/bevindingen/{_bevinding_id(h)}/bewust-verwijderd", json={"administratie_id": str(administratie_id)}, headers=h)
        assert r.status_code == 422 and "verdwenen" in r.json()["detail"]
        r = client.post(f"/reconciliatie/bevindingen/{uuid.uuid4()}/bewust-verwijderd", json={"administratie_id": str(administratie_id)}, headers=h)
        assert r.status_code == 404

    def test_kantoorrol_en_accordeur_403(self, geboekt, administratie_id, beheerder_id, gescoopte_gebruiker, admin_engine) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "404")
        bid = _bevinding_id(_bearer(beheerder_id, rol="beheerder"))
        body = {"administratie_id": str(administratie_id)}
        r = client.post(f"/reconciliatie/bevindingen/{bid}/bewust-verwijderd", json=body, headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert r.status_code == 403
        accordeur = maak_gebruiker(admin_engine, "klant_accordeur", "Accordeur")
        r = client.post(f"/reconciliatie/bevindingen/{bid}/bewust-verwijderd", json=body, headers=_bearer(accordeur, rol="klant_accordeur"))
        assert r.status_code == 403
        assert _status(admin_engine, document_id) == "geboekt"

    def test_herstel_route_200_en_gewoon_duplicaat_409(self, geboekt, administratie_id, beheerder_id, admin_engine) -> None:
        document_id, fake = geboekt
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]
        _run_met(administratie_id, document_id, "ontbreekt_in_rlz", "404")
        h = _bearer(beheerder_id, rol="beheerder")
        bid = _bevinding_id(h)
        pad = f"/reconciliatie/documenten/{document_id}/bewust-verwijderd-herstellen"
        body = {"administratie_id": str(administratie_id), "reden": "toch niet dubbel — stuk hoort in RLZ"}
        # Nog geboekt (niet afgevoerd) → 409.
        r = client.post(pad, json=body, headers=h)
        assert r.status_code == 409
        assert client.post(f"/reconciliatie/bevindingen/{bid}/bewust-verwijderd", json={"administratie_id": str(administratie_id)}, headers=h).status_code == 200
        r = client.post(pad, json=body, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["document_status_nieuw"] == "geboekt" and r.json()["acceptatie_ingetrokken_id"] is not None
        assert _status(admin_engine, document_id) == "geboekt"
        # Niet-Beheerder → 403 (router-poort).
        buiten = maak_gebruiker(admin_engine, "boekhouding", "Kantoor")
        assert client.post(pad, json=body, headers=_bearer(buiten, rol="boekhouding")).status_code == 403
