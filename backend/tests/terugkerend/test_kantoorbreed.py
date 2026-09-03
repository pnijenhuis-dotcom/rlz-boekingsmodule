# ruff: noqa: F811 — pytest-fixtures als parameters
"""Inzicht › Terugkerende facturen KANTOORBREED (design-ronde 03-09 blok B1; mockup inzicht-kantoorbreed
①②③; migratie 0099): kantoorbrede lijst (één rij per signaal, urgentie-sortering, status-facet,
administratie-facet, zoekterm, paginering 25, tellers), RLS-scope (niet-Beheerder MÉT scope ziet alleen
de eigen administratie), achtergrond-herbereken-run (202 + status, hergebruik, voertuig-fout zichtbaar),
concept-mail (deterministisch, ontvanger uit de vendor-cache) + versturen (mailkanaal gemockt, audit,
fail-zichtbaar). Puur code — geen AI, geen RLZ-writes."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.berichten import mail
from app.db.models import GebruikerRol
from app.main import app
from app.terugkerend import herbereken_run, kantoorbreed, service
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.terugkerend.test_terugkerend import VENDOR_A, VENDOR_B, _bearer, _factuur, vendors  # noqa: F401

client = TestClient(app)
VANDAAG = date(2026, 8, 30)
VENDOR_C = uuid.UUID("cccccccc-1111-1111-1111-111111111111")


@pytest.fixture
def tweede_administratie(admin_engine: Engine) -> uuid.UUID:
    """Een tweede actieve administratie BUITEN de scope van `gescoopte_gebruiker` (Beheerder ziet 'm wél)."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, 'Renewi', '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": VENDOR_C, "aid": aid},
        )
    return aid


def _signalen_opzetten(administratie_id, tweede_administratie, gescoopte_gebruiker, beheerder_id, opslag) -> None:
    """A/Ziggo: maandpatroon, laatste 2 april 2026 (+20 %) → ontbreekt (109 d) én prijsstijging.
    B/Renewi: maandpatroon, laatste 1 juli → ontbreekt (op 30-08: uiterlijk 11-08 → 19 d te laat)."""
    for datum, bedrag in ((date(2026, 1, 2), "100.00"), (date(2026, 2, 3), "100.00"), (date(2026, 3, 2), "100.00")):
        _factuur(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            vendor=VENDOR_A,
            datum=datum,
            bedrag=bedrag,
            naam=f"z{datum}.pdf",
        )
    _factuur(
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        vendor=VENDOR_A,
        datum=date(2026, 4, 2),
        bedrag="120.00",
        naam="z-apr.pdf",
    )
    for datum in (date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1)):
        _factuur(
            tweede_administratie,
            beheerder_id,
            opslag,
            vendor=VENDOR_C,
            datum=datum,
            bedrag="890.00",
            naam=f"r{datum}.pdf",
        )
    service.herbereken_administratie(administratie_id=administratie_id, vandaag=VANDAAG)
    service.herbereken_administratie(administratie_id=tweede_administratie, vandaag=VANDAAG)


class TestKantoorbredeLijst:
    def test_sortering_facetten_zoek_paginering_en_tellers(
        self, administratie_id, tweede_administratie, gescoopte_gebruiker, beheerder_id, opslag, vendors
    ) -> None:
        _signalen_opzetten(administratie_id, tweede_administratie, gescoopte_gebruiker, beheerder_id, opslag)
        lijst = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, vandaag=VANDAAG)
        # Eén rij per signaal: Ziggo levert er twee (ontbreekt + prijsstijging), Renewi één.
        assert [(r.leverancier, r.soort) for r in lijst.rijen] == [
            ("Ziggo Zakelijk", "ontbreekt"),  # 109 d te laat
            ("Renewi", "ontbreekt"),  # 19 d te laat
            ("Ziggo Zakelijk", "prijsstijging"),  # daarna de prijsstijgingen
        ]
        assert lijst.rijen[0].dagen_te_laat == 109 and lijst.rijen[1].dagen_te_laat == 19
        assert lijst.rijen[2].prijsstijging_pct == Decimal("20.00") and lijst.rijen[2].dagen_te_laat is None
        assert lijst.rijen[2].laatste_document_id is not None  # "Naar de boeking →"
        assert lijst.totaal == 3 and lijst.administraties_in_selectie == 2
        assert lijst.tellers.__dict__ == {"ontbrekend": 2, "prijsstijging": 1, "administraties": 2}
        assert lijst.facetten.status == {"aandacht": 3, "gesnoozed": 0, "afgemeld": 0, "alle": 3}
        assert [(f.naam, f.aantal) for f in lijst.facetten.administraties] == [("Andere BV", 1), ("Scope-test", 2)]

        # Zoekterm op leverancier + administratie-facet + paginering (per_pagina 1 → pagina 2 = Renewi).
        assert [
            r.leverancier
            for r in kantoorbreed.lijst(
                actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, q="ren", vandaag=VANDAAG
            ).rijen
        ] == ["Renewi"]
        alleen_a = kantoorbreed.lijst(
            actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, administratie_id=administratie_id, vandaag=VANDAAG
        )
        assert alleen_a.totaal == 2 and {r.administratie_id for r in alleen_a.rijen} == {administratie_id}
        assert alleen_a.tellers.ontbrekend == 2  # tellers blijven kantoorbreed (paneelkop-chips)
        p2 = kantoorbreed.lijst(
            actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, per_pagina=1, pagina=2, vandaag=VANDAAG
        )
        assert p2.totaal == 3 and [r.leverancier for r in p2.rijen] == ["Renewi"] and p2.per_pagina == 1

        # Snooze Ziggo: de ontbreekt-rij verhuist naar het facet "gesnoozed", de prijsstijging-rij blijft aandacht.
        service.snooze(
            administratie_id=administratie_id, vendor_id=VENDOR_A, tot=date(2099, 1, 1), actor_id=gescoopte_gebruiker
        )
        na = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, vandaag=VANDAAG)
        assert [(r.leverancier, r.soort) for r in na.rijen] == [
            ("Renewi", "ontbreekt"),
            ("Ziggo Zakelijk", "prijsstijging"),
        ]
        assert na.facetten.status == {"aandacht": 2, "gesnoozed": 1, "afgemeld": 0, "alle": 3}
        gesnoozed = kantoorbreed.lijst(
            actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, status="gesnoozed", vandaag=VANDAAG
        )
        assert [(r.leverancier, r.soort, r.status) for r in gesnoozed.rijen] == [
            ("Ziggo Zakelijk", "ontbreekt", "gesnoozed")
        ]
        # Afmelden = per leverancier: beide Ziggo-rijen naar "afgemeld".
        service.zet_afgemeld(
            administratie_id=administratie_id, vendor_id=VENDOR_A, afgemeld=True, actor_id=gescoopte_gebruiker
        )
        afgemeld = kantoorbreed.lijst(
            actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, status="afgemeld", vandaag=VANDAAG
        )
        assert sorted(r.soort for r in afgemeld.rijen) == ["ontbreekt", "prijsstijging"]
        assert (
            kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, status="alle", vandaag=VANDAAG).totaal
            == 3
        )
        with pytest.raises(service.TerugkerendFout):
            kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, status="boem")

    def test_scope_niet_beheerder_ziet_alleen_eigen_administratie(
        self, administratie_id, tweede_administratie, gescoopte_gebruiker, beheerder_id, opslag, vendors
    ) -> None:
        _signalen_opzetten(administratie_id, tweede_administratie, gescoopte_gebruiker, beheerder_id, opslag)
        resp = client.get("/terugkerend/signalen", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["totaal"] == 2 and {r["administratie_id"] for r in body["rijen"]} == {str(administratie_id)}
        assert body["tellers"] == {"ontbrekend": 1, "prijsstijging": 1, "administraties": 1}
        assert [f["naam"] for f in body["facetten"]["administraties"]] == ["Scope-test"]
        # Administratie-facet op een administratie BUITEN de scope = leeg, nooit een lek.
        resp = client.get(
            f"/terugkerend/signalen?administratie_id={tweede_administratie}",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200 and resp.json()["totaal"] == 0
        # Beheerder: beide administraties, urgentste bovenaan, status-facet in de URL.
        resp = client.get("/terugkerend/signalen?status=alle&pagina=1", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200 and resp.json()["totaal"] == 3 and resp.json()["per_pagina"] == 25
        # Via HTTP telt de echte kalender (geen vandaag-injectie): uiterlijk 13-05-2026 → dagen te laat t.o.v. vandaag.
        assert resp.json()["rijen"][0]["leverancier"] == "Ziggo Zakelijk"
        assert resp.json()["rijen"][0]["dagen_te_laat"] == (date.today() - date(2026, 5, 13)).days
        assert (
            client.get("/terugkerend/signalen?status=boem", headers=_bearer(beheerder_id, rol="beheerder")).status_code
            == 422
        )


class TestHerberekenRun:
    def test_202_status_hergebruik_en_verwerking(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, opslag, vendors, monkeypatch
    ) -> None:
        # Het voertuig (thread/job) wordt in de test niet gestart: we verwerken de wachtrij zelf, synchroon.
        monkeypatch.setattr(herbereken_run, "_start_voertuig", lambda: None)
        for datum in (date(2026, 1, 2), date(2026, 2, 3), date(2026, 3, 2)):
            _factuur(
                administratie_id,
                gescoopte_gebruiker,
                opslag,
                vendor=VENDOR_A,
                datum=datum,
                bedrag="100.00",
                naam=f"h{datum}.pdf",
            )
        resp = client.post("/terugkerend/herbereken", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert resp.status_code == 202, resp.text
        run = resp.json()
        assert run["status"] == "wachtend" and run["aantal_administraties"] >= 1 and run["aantal_verwerkt"] == 0
        # Tweede klik terwijl de run wacht = dezelfde run (nooit twee tegelijk).
        resp2 = client.post("/terugkerend/herbereken", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp2.status_code == 202 and resp2.json()["run_id"] == run["run_id"]
        assert (
            client.get("/terugkerend/herbereken/laatste", headers=_bearer(beheerder_id, rol="beheerder")).json()[
                "run_id"
            ]
            == run["run_id"]
        )
        # Verwerker (job/thread-entrypoint): claimt, draait herbereken_alle, zet klaar mét tellers.
        assert herbereken_run.verwerk_wachtrij() == 1
        assert herbereken_run.verwerk_wachtrij() == 0  # lege wachtrij = no-op
        resp = client.get(
            f"/terugkerend/herbereken/{run['run_id']}", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert resp.status_code == 200, resp.text
        stand = resp.json()
        assert stand["status"] == "klaar" and stand["klaar_op"] is not None and stand["foutreden"] is None
        assert stand["aantal_verwerkt"] >= 1 and stand["aantal_fouten"] == 0
        assert stand["resultaat"][str(administratie_id)]["terugkerend"] == 1
        # De signaallaag is werkelijk herberekend.
        assert service.overzicht(administratie_id=administratie_id)[0].leverancier == "Ziggo Zakelijk"
        # Onbekende run = 404; nieuwe run ná klaar = nieuwe rij.
        assert (
            client.get(
                f"/terugkerend/herbereken/{uuid.uuid4()}", headers=_bearer(beheerder_id, rol="beheerder")
            ).status_code
            == 404
        )
        resp3 = client.post("/terugkerend/herbereken", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp3.status_code == 202 and resp3.json()["run_id"] != run["run_id"]

    def test_voertuig_fout_is_zichtbaar_op_de_run(self, beheerder_id, monkeypatch) -> None:
        def kapot() -> None:
            raise RuntimeError("Cloud Run-job onbereikbaar")

        monkeypatch.setattr(herbereken_run, "_start_voertuig", kapot)
        resp = client.post("/terugkerend/herbereken", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 502 and "onbereikbaar" in resp.json()["detail"]
        laatste = herbereken_run.laatste_run()
        assert (
            laatste is not None
            and laatste.status == "fout"
            and "Achtergrondrun starten mislukt" in (laatste.foutreden or "")
        )
        # Ná een fout-run kan er gewoon een nieuwe gestart worden (geen eeuwige blokkade).
        monkeypatch.setattr(herbereken_run, "_start_voertuig", lambda: None)
        assert (
            client.post("/terugkerend/herbereken", headers=_bearer(beheerder_id, rol="beheerder")).json()["status"]
            == "wachtend"
        )


class TestConceptMail:
    def test_concept_deterministisch_ontvanger_uit_cache_en_versturen_met_audit(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, opslag, vendors, admin_engine, monkeypatch
    ) -> None:
        for datum, bedrag in ((date(2026, 1, 2), "100.00"), (date(2026, 2, 3), "100.00"), (date(2026, 3, 2), "100.00")):
            _factuur(
                administratie_id,
                gescoopte_gebruiker,
                opslag,
                vendor=VENDOR_A,
                datum=datum,
                bedrag=bedrag,
                naam=f"c{datum}.pdf",
            )
        _factuur(
            administratie_id,
            gescoopte_gebruiker,
            opslag,
            vendor=VENDOR_A,
            datum=date(2026, 4, 2),
            bedrag="1240.00",
            naam="c-apr.pdf",
        )
        service.herbereken_administratie(administratie_id=administratie_id, vandaag=VANDAAG)
        kop = _bearer(gescoopte_gebruiker, rol="boekhouding")
        pad = f"/terugkerend/{administratie_id}/{VENDOR_A}/conceptmail"
        resp = client.get(pad, headers=kop)
        assert resp.status_code == 200, resp.text
        concept = resp.json()
        assert concept["ontvanger_e_mail"] is None  # brondata zonder Email → mens vult in
        assert concept["leverancier"] == "Ziggo Zakelijk" and concept["administratie_naam"] == "Scope-test"
        assert concept["onderwerp"] == "Vraag over de factuur voor mei 2026 — Scope-test"
        assert "Beste Ziggo Zakelijk," in concept["tekst"]
        assert "de laatste die wij hebben is die van 02-04-2026 (€ 1.240,00)" in concept["tekst"]
        assert "De factuur voor mei 2026 hebben wij nog niet ontvangen" in concept["tekst"]
        assert "facturen@ak-nijenhuis.nl" in concept["tekst"]
        assert client.get(pad, headers=kop).json() == concept  # deterministisch, geen AI
        # E-mail uit de vendor-cache (RLZ-veld Email) wordt de vooringevulde ontvanger.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    'UPDATE boekhouding.vendor_cache SET brondata = \'{"Email": "facturatie@ziggo.nl"}\' WHERE id = :id'
                ),
                {"id": VENDOR_A},
            )
        assert client.get(pad, headers=kop).json()["ontvanger_e_mail"] == "facturatie@ziggo.nl"
        # Geen patroon = 404; buiten scope = 403 (vereis_administratie_scope).
        assert client.get(f"/terugkerend/{administratie_id}/{VENDOR_B}/conceptmail", headers=kop).status_code == 404

        # Versturen: mailkanaal gemockt, audit_event geschreven, ontvanger door de mens gekozen.
        mails: list[dict] = []
        monkeypatch.setattr(mail, "verzend_mail", lambda **kw: mails.append(kw))
        resp = client.post(
            f"{pad}/versturen",
            json={
                "naar": "crediteuren@ziggo.nl",
                "onderwerp": "Aangepast onderwerp",
                "tekst": concept["tekst"] + "\nPS",
            },
            headers=kop,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"verzonden_aan": "crediteuren@ziggo.nl"}
        assert mails == [
            {"naar": "crediteuren@ziggo.nl", "onderwerp": "Aangepast onderwerp", "tekst": concept["tekst"] + "\nPS"}
        ]
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT nieuwe_waarde->>'aan', nieuwe_waarde->>'vendor_id', administratie_id "
                    "FROM platform.audit_event "
                    "WHERE actie = 'terugkerend_navraag_verzonden' ORDER BY tijdstip DESC LIMIT 1"
                )
            ).one()
        assert rij[0] == "crediteuren@ziggo.nl" and rij[1] == str(VENDOR_A) and rij[2] == administratie_id
        # Ongeldig adres / leeg = 422, niets verzonden.
        assert (
            client.post(
                f"{pad}/versturen", json={"naar": "geen-adres", "onderwerp": "x", "tekst": "y"}, headers=kop
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{pad}/versturen", json={"naar": "a@b.nl", "onderwerp": "   ", "tekst": "y"}, headers=kop
            ).status_code
            == 422
        )
        assert len(mails) == 1

    def test_mailkanaal_fouten_zichtbaar_niets_vastgelegd(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors, admin_engine, monkeypatch
    ) -> None:
        for datum in (date(2026, 1, 2), date(2026, 2, 3), date(2026, 3, 2)):
            _factuur(
                administratie_id,
                gescoopte_gebruiker,
                opslag,
                vendor=VENDOR_A,
                datum=datum,
                bedrag="100.00",
                naam=f"m{datum}.pdf",
            )
        service.herbereken_administratie(administratie_id=administratie_id, vandaag=VANDAAG)
        kop = _bearer(gescoopte_gebruiker, rol="boekhouding")
        pad = f"/terugkerend/{administratie_id}/{VENDOR_A}/conceptmail/versturen"
        body = {"naar": "a@b.nl", "onderwerp": "x", "tekst": "y"}

        def niet_geconfigureerd(**kw):
            raise mail.MailNietGeconfigureerd("Mailkanaal niet geconfigureerd")

        def verzendfout(**kw):
            raise mail.MailVerzendFout("SMTP weigerde")

        monkeypatch.setattr(mail, "verzend_mail", niet_geconfigureerd)
        assert client.post(pad, json=body, headers=kop).status_code == 503
        monkeypatch.setattr(mail, "verzend_mail", verzendfout)
        assert client.post(pad, json=body, headers=kop).status_code == 424
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE actie = 'terugkerend_navraag_verzonden' AND administratie_id = :aid"
                ),
                {"aid": administratie_id},
            ).scalar_one()
        assert aantal == 0
        # Externe rol komt er niet in (router-brede kantoorpoort), ook niet op de kantoorbrede lijst.
        accordeur = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'A', :m, 'klant_accordeur', 'actief')"
                ),
                {"id": accordeur, "m": f"{accordeur}@test.local"},
            )
        assert client.get("/terugkerend/signalen", headers=_bearer(accordeur, rol="klant_accordeur")).status_code == 403
        assert (
            client.post("/terugkerend/herbereken", headers=_bearer(accordeur, rol="klant_accordeur")).status_code == 403
        )
