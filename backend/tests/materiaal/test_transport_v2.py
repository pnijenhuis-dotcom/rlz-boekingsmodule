"""Transport-dag-agenda 31-08 (mockup planning-werkopdracht-transport.html): statusflow
gereserveerd → bevestigd (voertuig + mail transport-contact) → definitief (materiaallijst +
planner + mail materiaal-contact) → geleverd; delta-mail bij wijziging ná definitief;
dag verschuiven = terug naar gereserveerd; te-plannen-signaal; leverancier-contactpersonen +
catalogusbeheer voor B+P; legacy 'gepland' gedraagt zich als 'gereserveerd'."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.berichten import mail as mail_module
from app.main import app
from app.materiaal import service as materiaal
from app.security.tokens import create_access_token
from app.uren import service as uren_service
from tests.materiaal.conftest import product_id_op_naam
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)
JAAR, WEEK = 2026, 35
MAANDAG = date.fromisocalendar(JAAR, WEEK, 1)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _met_contacten(administratie_id, beheerder_id, leverancier_id) -> None:
    materiaal.zet_leverancier(
        administratie_id=administratie_id, actor_id=beheerder_id, leverancier_id=leverancier_id,
        naam="Universal Nederland B.V.", bestel_email="bestel@universalbv.nl", telefoon=None, adres=None,
        vendor_id=None, transport_contact_naam="Roland", transport_contact_email="roland@universalbv.nl",
        materiaal_contact_naam="Theo", materiaal_contact_email="theo@universalbv.nl",
    )


def _buis(administratie_id, leverancier_id, beheerder_id, lengte: str) -> str:
    return str(product_id_op_naam(administratie_id, leverancier_id, beheerder_id, f"Steigerbuis tubelock {lengte} mtr"))


def _reserveer(administratie_id, beheerder_id, project_id, leverancier_id, *, datum=MAANDAG, regels=None):
    return materiaal.plan_transport(
        administratie_id=administratie_id, actor_id=beheerder_id, project_id=project_id,
        leverancier_id=leverancier_id, soort="levering", datum=datum, tijdstip=None,
        regels=regels or {}, omschrijving=None,
    )


class TestStatusflow31_08:
    def test_bevestigen_mailt_transport_contact_en_zet_voertuig(
        self, administratie_id, project_id, leverancier_id, beheerder_id, mail_log
    ):
        _met_contacten(administratie_id, beheerder_id, leverancier_id)
        t = _reserveer(administratie_id, beheerder_id, project_id, leverancier_id)
        assert t.status == "gereserveerd" and t.regels == []  # werkbakje-kaart zonder materiaal mag
        with pytest.raises(uren_service.OngeldigeInvoer):
            materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="fiets")
        t = materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="combi")
        assert t.status == "bevestigd" and t.voertuig == "combi"
        assert len(mail_log) == 1 and mail_log[0]["naar"] == "roland@universalbv.nl"
        assert "definitief door" in mail_log[0]["tekst"] and "combi" in mail_log[0]["tekst"]
        # Idempotent op status: nogmaals bevestigen = 409 (geen tweede mail).
        with pytest.raises(uren_service.OngeldigeOvergang):
            materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="combi")
        assert len(mail_log) == 1

    def test_bevestig_mailfout_laat_status_staan(self, administratie_id, project_id, leverancier_id, beheerder_id, monkeypatch):
        _met_contacten(administratie_id, beheerder_id, leverancier_id)
        t = _reserveer(administratie_id, beheerder_id, project_id, leverancier_id)

        def _boem(**_):
            raise mail_module.MailVerzendFout("smtp plat")

        monkeypatch.setattr(mail_module, "verzend_mail", _boem)
        with pytest.raises(materiaal.VerzendenMislukt):
            materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="combi")
        vers = materiaal.transport_week(administratie_id=administratie_id, actor_id=beheerder_id, jaar=JAAR, weeknummer=WEEK)
        kaart = next(t2 for r in vers.projecten for items in r.per_datum.values() for t2 in items if t2.id == t.id)
        assert kaart.status == "gereserveerd" and kaart.voertuig is None

    def test_zonder_transport_contact_422(self, administratie_id, project_id, leverancier_id, beheerder_id):
        t = _reserveer(administratie_id, beheerder_id, project_id, leverancier_id)
        with pytest.raises(uren_service.OngeldigeInvoer, match="transport-contact"):
            materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="combi")

    def test_definitief_vereist_lijst_en_planner_en_mailt_theo(
        self, administratie_id, project_id, leverancier_id, beheerder_id, mail_log
    ):
        _met_contacten(administratie_id, beheerder_id, leverancier_id)
        b4 = _buis(administratie_id, leverancier_id, beheerder_id, "4")
        t = _reserveer(administratie_id, beheerder_id, project_id, leverancier_id)
        t = materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="voorwagen")
        with pytest.raises(uren_service.OngeldigeInvoer):
            materiaal.maak_definitief(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={}, transportplanner="De Jong")
        with pytest.raises(uren_service.OngeldigeInvoer):
            materiaal.maak_definitief(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={b4: 115}, transportplanner="  ")
        t = materiaal.maak_definitief(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={b4: 115}, transportplanner="De Jong Transport")
        assert t.status == "definitief" and t.transportplanner == "De Jong Transport" and t.m2 == Decimal("100.00")
        lijst_mail = mail_log[-1]
        assert lijst_mail["naar"] == "theo@universalbv.nl"
        assert "Steigerbuis tubelock 4 mtr: 115" in lijst_mail["tekst"] and "100.00 m²" in lijst_mail["tekst"]

    def test_delta_mail_alleen_gewijzigde_regels(self, administratie_id, project_id, leverancier_id, beheerder_id, mail_log):
        _met_contacten(administratie_id, beheerder_id, leverancier_id)
        b4 = _buis(administratie_id, leverancier_id, beheerder_id, "4")
        b2 = _buis(administratie_id, leverancier_id, beheerder_id, "2")
        t = _reserveer(administratie_id, beheerder_id, project_id, leverancier_id)
        t = materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="combi")
        t = materiaal.maak_definitief(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={b4: 100, b2: 50}, transportplanner="De Jong")
        # Geen wijziging = niets te versturen (bestelrevisie-patroon).
        with pytest.raises(uren_service.OngeldigeOvergang):
            materiaal.wijzig_materiaallijst(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={b4: 100, b2: 50})
        t = materiaal.wijzig_materiaallijst(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={b4: 60, b2: 50})
        assert t.status == "definitief"
        delta_mail = mail_log[-1]
        assert delta_mail["naar"] == "theo@universalbv.nl"
        assert "100 → 60" in delta_mail["tekst"]
        assert "tubelock 2 mtr" not in delta_mail["tekst"]  # ongewijzigde regel wordt niet herhaald
        # Reguliere wijzig-route mag de lijst van een definitief transport niet stil aanraken.
        with pytest.raises(uren_service.OngeldigeOvergang):
            materiaal.wijzig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={b4: 1})

    def test_delta_mailfout_laat_lijst_staan(self, administratie_id, project_id, leverancier_id, beheerder_id, mail_log, monkeypatch):
        _met_contacten(administratie_id, beheerder_id, leverancier_id)
        b4 = _buis(administratie_id, leverancier_id, beheerder_id, "4")
        t = _reserveer(administratie_id, beheerder_id, project_id, leverancier_id)
        t = materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="combi")
        t = materiaal.maak_definitief(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={b4: 100}, transportplanner="De Jong")

        def _boem(**_):
            raise mail_module.MailVerzendFout("smtp plat")

        monkeypatch.setattr(mail_module, "verzend_mail", _boem)
        with pytest.raises(materiaal.VerzendenMislukt):
            materiaal.wijzig_materiaallijst(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={b4: 60})
        week = materiaal.transport_week(administratie_id=administratie_id, actor_id=beheerder_id, jaar=JAAR, weeknummer=WEEK)
        kaart = next(t2 for r in week.projecten for items in r.per_datum.values() for t2 in items if t2.id == t.id)
        assert kaart.regels[0]["aantal"] == 100  # geen stille wijziging

    def test_verschuiven_terug_naar_gereserveerd_lijst_blijft(
        self, administratie_id, project_id, leverancier_id, beheerder_id, mail_log
    ):
        _met_contacten(administratie_id, beheerder_id, leverancier_id)
        b4 = _buis(administratie_id, leverancier_id, beheerder_id, "4")
        t = _reserveer(administratie_id, beheerder_id, project_id, leverancier_id)
        t = materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="combi")
        t = materiaal.maak_definitief(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={b4: 100}, transportplanner="De Jong")
        t = materiaal.verschuif_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_datum=MAANDAG + timedelta(days=2))
        assert t.status == "gereserveerd" and t.datum == MAANDAG + timedelta(days=2)
        assert t.voertuig is None  # toezegging vervalt — opnieuw bevestigen
        assert t.regels[0]["aantal"] == 100 and t.transportplanner == "De Jong"  # lijst + planner blijven
        # Eén bevestig-klik + definitief maken is daarna genoeg om weer groen te worden.
        t = materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="voorwagen")
        t = materiaal.maak_definitief(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, regels={b4: 100}, transportplanner="De Jong")
        assert t.status == "definitief"
        # Geleverd verschuift nooit.
        t = materiaal.zet_transport_status(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_status="geleverd")
        with pytest.raises(uren_service.OngeldigeOvergang):
            materiaal.verschuif_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, nieuwe_datum=MAANDAG)

    def test_legacy_gepland_gedraagt_zich_als_gereserveerd(
        self, administratie_id, project_id, leverancier_id, beheerder_id, admin_engine: Engine, mail_log
    ):
        t = _reserveer(administratie_id, beheerder_id, project_id, leverancier_id)
        with admin_engine.begin() as conn:  # pre-0091-rij nabootsen (migratie is puur DDL)
            conn.execute(text("UPDATE boekhouding.materiaal_transport SET status = 'gepland' WHERE id = :id"), {"id": t.id})
        week = materiaal.transport_week(administratie_id=administratie_id, actor_id=beheerder_id, jaar=JAAR, weeknummer=WEEK)
        kaart = next(t2 for r in week.projecten for items in r.per_datum.values() for t2 in items if t2.id == t.id)
        assert kaart.status == "gereserveerd"  # effectieve status naar buiten
        _met_contacten(administratie_id, beheerder_id, leverancier_id)
        t = materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="combi")
        assert t.status == "bevestigd"

    def test_soort_wisselen_alleen_gereserveerd(self, administratie_id, project_id, leverancier_id, beheerder_id, mail_log):
        _met_contacten(administratie_id, beheerder_id, leverancier_id)
        t = _reserveer(administratie_id, beheerder_id, project_id, leverancier_id)
        t = materiaal.wijzig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, soort="retour")
        assert t.soort == "retour"
        t = materiaal.bevestig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, voertuig="combi")
        with pytest.raises(uren_service.OngeldigeOvergang):
            materiaal.wijzig_transport(administratie_id=administratie_id, actor_id=beheerder_id, transport_id=t.id, soort="levering")


class TestTePlannenSignaal:
    def test_verstuurde_bestelling_zonder_transport_signaleert(
        self, administratie_id, project_id, leverancier_id, beheerder_id, mail_log
    ):
        b4 = _buis(administratie_id, leverancier_id, beheerder_id, "4")
        bestelling_id = materiaal.maak_bestelling(administratie_id=administratie_id, actor_id=beheerder_id, project_id=project_id, leverancier_id=leverancier_id)
        materiaal.werk_concept_bij(administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bestelling_id, regels={b4: 10}, gewenste_leverdatum=MAANDAG + timedelta(days=1), gewenste_levertijd=None, leveradres="Bouwweg 1", contactpersoon=None, opmerking=None)
        # Versturen ZONDER automatische leveringskoppeling → het signaal moet verschijnen.
        materiaal.verstuur_bestelling(administratie_id=administratie_id, actor_id=beheerder_id, bestelling_id=bestelling_id, koppel_levering=False)
        week = materiaal.transport_week(administratie_id=administratie_id, actor_id=beheerder_id, jaar=JAAR, weeknummer=WEEK)
        assert [(s.bestelling_id, s.datum) for s in week.te_plannen] == [(bestelling_id, MAANDAG + timedelta(days=1))]
        # Transport plannen op de bestelling neemt het signaal weg.
        materiaal.plan_transport(administratie_id=administratie_id, actor_id=beheerder_id, project_id=project_id, leverancier_id=leverancier_id, soort="levering", datum=MAANDAG + timedelta(days=1), tijdstip=None, regels={}, omschrijving=None, bestelling_id=bestelling_id)
        week = materiaal.transport_week(administratie_id=administratie_id, actor_id=beheerder_id, jaar=JAAR, weeknummer=WEEK)
        assert week.te_plannen == []


class TestLeverancierContactenEnRechten:
    def test_contacten_opslaan_en_terug_in_overzicht(self, administratie_id, leverancier_id, beheerder_id):
        _met_contacten(administratie_id, beheerder_id, leverancier_id)
        lev = next(lv for lv in materiaal.leveranciers_overzicht(administratie_id=administratie_id, actor_id=beheerder_id) if lv.id == leverancier_id)
        assert (lev.transport_contact_naam, lev.transport_contact_email) == ("Roland", "roland@universalbv.nl")
        assert (lev.materiaal_contact_naam, lev.materiaal_contact_email) == ("Theo", "theo@universalbv.nl")
        with pytest.raises(uren_service.OngeldigeInvoer):
            materiaal.zet_leverancier(administratie_id=administratie_id, actor_id=beheerder_id, leverancier_id=leverancier_id, naam="Universal Nederland B.V.", bestel_email=None, telefoon=None, adres=None, vendor_id=None, transport_contact_email="geen-adres")

    def test_catalogusbeheer_voor_bp(self, administratie_id, leverancier_id, beheerder_id, admin_engine: Engine):
        """31-08: leverancier-/catalogusbeheer verruimd naar Boekhouding+Projecten."""
        bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Haci K.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=bp, administratie_id=administratie_id)
        lid = materiaal.zet_leverancier(administratie_id=administratie_id, actor_id=bp, leverancier_id=None, naam="Floor Liften", bestel_email=None, telefoon=None, adres=None, vendor_id=None)
        assert lid is not None
        resp = client.put(
            f"/materiaal/{administratie_id}/leveranciers",
            json={"id": str(lid), "naam": "Floor Liften", "transport_contact_naam": "Roland", "transport_contact_email": "r@floor.nl"},
            headers=_bearer(bp, rol="boekhouding_projecten"),
        )
        assert resp.status_code == 200, resp.text
        resp = client.put(
            f"/materiaal/{administratie_id}/leveranciers",
            json={"naam": "X"},
            headers=_bearer(maak_gebruiker(admin_engine, "boekhouding", "Rob"), rol="boekhouding"),
        )
        assert resp.status_code == 403
