from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.documenten import boeken
from app.main import app
from app.security.tokens import create_access_token
from tests.documenten.fake_rlz_client import FakeBoekClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _geen_echte_rlz_aanroepen_voor_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """De boekvoorstel-endpoints (PUT/checks) draaien de harde checks meteen mee, incl. de
    duplicaatcheck (een echte RLZ-aanroep als er geen client meegegeven wordt) — hier altijd een
    lege fake, zodat deze routertests geen echte credentials nodig hebben. De boek-actie zelf
    (TestBoekenEndpoint) geeft altijd zijn eigen client mee via `boeken.client_voor_rlz_admin_id`."""
    monkeypatch.setattr("app.documenten.boekvoorstel.client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _upload(headers: dict[str, str], administratie_id: uuid.UUID, *, bestandsnaam: str = "factuur.pdf") -> str:
    resp = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": (bestandsnaam, b"%PDF-1.4 " + uuid.uuid4().bytes, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["document_id"]


_REGEL = {
    "ledger_id": str(uuid.uuid4()),
    "taxrate_id": str(uuid.uuid4()),
    "netto_bedrag": "100.00",
    "btw_bedrag": "21.00",
}


class TestBoekvoorstelEndpoints:
    def test_get_zonder_opgeslagen_voorstel_geeft_leeg_niet_opgeslagen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)

        resp = client.get(f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["opgeslagen"] is False

    def test_put_slaat_op_en_geeft_checkrapport_terug(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)

        resp = client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": "F-1",
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "121.00",
                "regels": [_REGEL],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["boekvoorstel"]["opgeslagen"] is True
        assert body["checks"]["geblokkeerd"] is False
        assert {r["naam"] for r in body["checks"]["resultaten"]} == {
            "Verplichte velden",
            "Afdeling",
            "Betaalstatus (declaraties)",  # blok 3 bundel 08-09: buiten het declaraties-kanaal informatief
            "Projectverdeling",
            "Regeltelling vs totaal",
            "Btw-bedrag past bij tarief",  # 18-09 (Peter, casus Rituals): btw volgt het tarief — lokale harde check
            "Vervaldatum",
            "Btw-tarief buitenland",
            "IBAN-wissel",
            "Duplicaatcheck",
            "Duplicaat bij andere crediteur",
            "Duplicaat (module)",  # blok 1 07-09
            "Factuurdatum valt in een ingediende aangifteperiode",  # blok 4 feedbackrun A 25-09 (FV-16): oranje, nooit blokkerend
        }

    def test_put_met_mismatch_totaal_geeft_geblokkeerd_checkrapport(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)

        resp = client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": "F-1",
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "999.00",
                "regels": [_REGEL],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["checks"]["geblokkeerd"] is True

    def test_put_met_nl_komma_bedragen_geeft_zelfde_checkrapport_als_punt_decimaal(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        """Design-pass P2/P3: de volledige keten met komma-notatie — vóór de fix zou dit óf een
        422 geven, óf (na een client-side normalisatie-bug) een fout regeltelling-resultaat. Hier
        rechtstreeks de HTTP-laag geraakt (geen mock op de pydantic-validatie), met dezelfde
        bedragen als het punt-decimaal-equivalent in test_put_slaat_op_en_geeft_checkrapport_terug."""
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)

        resp = client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": "F-1",
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "121,00",
                "regels": [{**_REGEL, "netto_bedrag": "100,00", "btw_bedrag": "21,00"}],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["boekvoorstel"]["totaalbedrag"] == "121.00"
        assert body["boekvoorstel"]["regels"][0]["netto_bedrag"] == "100.00"
        assert body["checks"]["geblokkeerd"] is False
        assert {r["naam"] for r in body["checks"]["resultaten"]} == {
            "Verplichte velden",
            "Afdeling",
            "Betaalstatus (declaraties)",  # blok 3 bundel 08-09: buiten het declaraties-kanaal informatief
            "Projectverdeling",
            "Regeltelling vs totaal",
            "Btw-bedrag past bij tarief",  # 18-09 (Peter, casus Rituals): btw volgt het tarief — lokale harde check
            "Vervaldatum",
            "Btw-tarief buitenland",
            "IBAN-wissel",
            "Duplicaatcheck",
            "Duplicaat bij andere crediteur",
            "Duplicaat (module)",  # blok 1 07-09
            "Factuurdatum valt in een ingediende aangifteperiode",  # blok 4 feedbackrun A 25-09 (FV-16): oranje, nooit blokkerend
        }
        assert all(r["ok"] for r in body["checks"]["resultaten"])

    def test_checks_endpoint_herberekent_zonder_op_te_slaan(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)
        client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": "F-1",
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "121.00",
                "regels": [_REGEL],
            },
        )
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel/checks", headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["geblokkeerd"] is False

    def test_boekvoorstel_op_onbekend_document_geeft_404(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        resp = client.get(
            f"/administraties/{administratie_id}/documenten/{uuid.uuid4()}/boekvoorstel",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 404


class TestBoekenEndpoint:
    def _klaar_document(self, headers: dict[str, str], administratie_id: uuid.UUID) -> str:
        document_id = _upload(headers, administratie_id)
        client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": f"F-{document_id}",
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "121.00",
                "regels": [_REGEL],
            },
        )
        return document_id

    def test_boeken_zonder_toggle_geeft_403(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id)

        resp = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/boeken", headers=headers)
        assert resp.status_code == 403

    def test_boeken_geblokkeerd_door_checks_geeft_409_met_rapport(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)  # geen boekvoorstel -> geblokkeerd

        resp = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/boeken", headers=headers)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["checks"]["geblokkeerd"] is True

    def test_boeken_gelukt_geeft_200_met_boekstuknummer(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id)

        # Boeken sneller (18-09): `?direct=1` = het synchrone pad (het gedrag vóór 18-09); default = 202, zie hieronder.
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boeken?direct=1", headers=headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "geboekt"
        assert body["rlz_boekstuknummer"] == "RLZ-TEST-00001"

    def test_boeken_rlz_fout_geeft_502(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient(faal_op="put"))
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id)

        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boeken?direct=1", headers=headers
        )
        assert resp.status_code == 502
        assert "PUT mislukt" in resp.json()["detail"]

    def test_boeken_zonder_scope_faalt(self, gescoopte_gebruiker: uuid.UUID) -> None:
        resp = client.post(
            f"/administraties/{uuid.uuid4()}/documenten/{uuid.uuid4()}/boeken",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403

    def test_boeken_onverwachte_fout_geeft_nette_500_geen_kale_internal_server_error(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De derde kale 500 uit de kliktest, end-to-end via de HTTP-laag: een onverwachte fout
        (geen RlzApiError) tijdens het boeken mag nooit als tekstuele "Internal Server Error" bij
        de gebruiker komen — de globale exception-handler (app/main.py) maakt er een nette
        Nederlandse JSON-melding + correlatie-id van, en het document komt op boeken_mislukt te
        staan (niet in limbo). raise_server_exceptions=False: anders reraiset Starlette's
        ServerErrorMiddleware de fout ook nog richting de testclient (bedoeld voor bv. Sentry-
        integraties), wat deze test zou laten falen op de exception zelf i.p.v. de response."""
        geen_raise_client = TestClient(app, raise_server_exceptions=False)
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(
            boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient(faal_op="put_onverwacht")
        )
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id)

        resp = geen_raise_client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boeken?direct=1", headers=headers
        )

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "Internal Server Error" not in detail
        assert "Er ging iets mis bij het boeken van de factuur" in detail

        with admin_engine.connect() as conn:
            document_status = conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
            ).scalar_one()
        assert document_status == "boeken_mislukt"  # niet in limbo blijven staan

    def test_geboekt_document_kan_niet_verwijderd_worden_via_http(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Design-pass taak 4, hard geëist: bewaarplicht geldt ook via de echte HTTP-laag, niet
        alleen op de servicefunctie."""
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id)
        boek_resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boeken?direct=1", headers=headers
        )
        assert boek_resp.status_code == 200, boek_resp.text

        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verwijderen", json={"reden": "test"}, headers=headers
        )
        assert resp.status_code == 409, resp.text
        assert "bewaarplicht" in resp.json()["detail"]

    def test_geboekt_document_weigert_put_en_checks_via_http_en_blijft_ongewijzigd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kliktest-fix: het boekvoorstel bleek nog bewerkbaar na boeken. Dit test de échte
        bescherming (backend), niet alleen dat de knoppen in de UI verborgen zijn."""
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id)
        boek_resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boeken?direct=1", headers=headers
        )
        assert boek_resp.status_code == 200, boek_resp.text

        voor_de_poging = client.get(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel", headers=headers
        ).json()

        put_resp = client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": "GEPOOGDE-WIJZIGING",
                "factuurdatum": "2026-01-01",
                "totaalbedrag": "999.99",
                "regels": [{**_REGEL, "omschrijving": "Gepoogde wijziging"}],
            },
        )
        assert put_resp.status_code == 409, put_resp.text
        assert "geboekt" in put_resp.json()["detail"]

        checks_resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel/checks", headers=headers
        )
        assert checks_resp.status_code == 409, checks_resp.text

        na_de_poging = client.get(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel", headers=headers
        ).json()
        assert na_de_poging == voor_de_poging


class TestBoekenIngediend:
    """Boeken sneller (Peter 18-09): POST …/boeken antwoordt standaard 202 `wordt_geboekt` + het volgende document; de
    RLZ-write loopt in de achtergrond-schrijver (in de suite direct, zie conftest `_boek_wachtrij_direct`). Een
    mislukking is een zichtbare `boeken_mislukt`, geen 502 meer op de knop."""

    def _klaar_document(self, headers: dict[str, str], administratie_id: uuid.UUID, referentie: str) -> str:
        document_id = _upload(headers, administratie_id)
        resp = client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": referentie,
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "121.00",
                "regels": [_REGEL],
            },
        )
        assert resp.status_code == 200, resp.text
        return document_id

    def _status(self, admin_engine: Engine, document_id: str) -> str:
        with admin_engine.connect() as conn:
            return conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
            ).scalar_one()

    def test_default_geeft_202_wordt_geboekt_en_de_worker_boekt(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id, "F-202")

        resp = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/boeken", headers=headers)
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "wordt_geboekt"
        assert body["sleutel"] == f"boek-{document_id}-0"
        assert body["volgende_document_id"] is None  # geen ander verwerkbaar document in deze administratie
        # Server-Timing (stap 0): de synchrone stappen zijn meetbaar.
        assert "checks.lokaal" in resp.headers.get("server-timing", "")
        # De directe wachtrij (suite) heeft de boeking al afgerond: precies één PUT, document geboekt.
        assert len(fake.puts) == 1
        assert self._status(admin_engine, document_id) == "geboekt"
        with admin_engine.connect() as conn:
            acties = conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"),
                {"id": document_id},
            ).scalars().all()
        assert "boek_wachtrij_ingediend" in acties and "boek_wachtrij_afgerond" in acties
        with admin_engine.connect() as conn:
            claim = conn.execute(
                text("SELECT uitkomst, afgerond_op FROM boekhouding.boek_wachtrij_claim WHERE sleutel = :s"),
                {"s": body["sleutel"]},
            ).one()
        assert claim.uitkomst == "geboekt" and claim.afgerond_op is not None

    def test_lijst_volgorde_bepaalt_het_volgende_document_positioneel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        huidig = self._klaar_document(headers, administratie_id, "F-1")
        b = self._klaar_document(headers, administratie_id, "F-2")  # te_controleren
        c = _upload(headers, administratie_id)  # ontvangen → niet verwerkbaar
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{huidig}/boeken",
            headers=headers,
            json={"lijst_volgorde": [c, huidig, b]},
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        # Ná `huidig` komt `b` (verwerkbaar); `c` (ontvangen) telt niet — exact de kiesVolgendDocument-regels.
        assert body["volgende_document_id"] == b
        assert body["volgende_document_soort"] == "inkoopfactuur"

    def test_rlz_fout_in_de_worker_is_een_zichtbare_boeken_mislukt_geen_502(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient(faal_op="put"))
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id, "F-502")

        resp = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/boeken", headers=headers)
        assert resp.status_code == 202, resp.text
        assert self._status(admin_engine, document_id) == "boeken_mislukt"
        with admin_engine.connect() as conn:
            fout = conn.execute(
                text(
                    "SELECT nieuwe_waarde->>'uitkomst', nieuwe_waarde->>'fout' FROM platform.audit_event "
                    "WHERE record_id = :id AND actie = 'boek_wachtrij_afgerond'"
                ),
                {"id": document_id},
            ).one()
        assert fout[0] == "mislukt" and "PUT mislukt" in (fout[1] or "")
        # "Opnieuw" = opnieuw indienen vanuit boeken_mislukt (mét VERSE externe checks) — hier lukt de PUT.
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        resp2 = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/boeken", headers=headers)
        assert resp2.status_code == 202, resp2.text
        assert self._status(admin_engine, document_id) == "geboekt"

    def test_checks_route_extern_cache_en_voorverwarm(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id, "F-CACHE")
        pad = f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel/checks"
        # De PUT in _klaar_document draaide de checks al (AUTO) → het externe rapport staat in de cache.
        eerste = client.post(pad, headers=headers)
        assert eerste.status_code == 200, eerste.text
        assert eerste.json()["extern_uit_cache"] is True and eerste.json()["extern_gecontroleerd_op"]
        vers = client.post(pad + "?extern=vers", headers=headers)
        assert vers.json()["extern_uit_cache"] is False and vers.json()["extern_gecontroleerd_op"]
        tweede = client.post(pad, headers=headers)
        assert tweede.json()["extern_uit_cache"] is True  # zelfde vingerafdruk, ≤ 15 min → cache
        lokaal = client.post(pad + "?extern=cache", headers=headers)
        assert lokaal.json()["extern_uit_cache"] is True and lokaal.json()["extern_nog_niet"] is False
        # De PUT mét X-Checks: lokaal = opslaan + lokale checks; externe rijen uit de cache (geen 'loopt nog' hier).
        put = client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers={**headers, "X-Checks": "lokaal"},
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": "F-CACHE-2",
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "121.00",
                "regels": [_REGEL],
            },
        )
        assert put.status_code == 200, put.text
        # Andere crediteur + referentie = andere vingerafdruk → geen geldige cache → 'loopt nog' (blokkerend, nooit stil).
        assert put.json()["checks"]["extern_nog_niet"] is True and put.json()["checks"]["geblokkeerd"] is True
        voorverwarm = client.post(pad + "?voorverwarm=1", headers=headers)
        assert voorverwarm.status_code == 200
        assert voorverwarm.json()["voorverwarm"] in ("gedaan", "uit_cache")
        with admin_engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE record_id = :id AND actie = 'checks_voorverwarmd'"),
                {"id": document_id},
            ).scalar_one()
        assert n == 1


class TestBoekWachtrijOpnieuwIndienenRoute:
    """21-09: `POST …/boek-wachtrij/opnieuw-indienen` — alleen op wordt_geboekt (anders 409), scope-poort,
    trigger-uitkomst
    in het antwoord."""

    def test_opnieuw_indienen_route(
        self, gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.documenten import boek_wachtrij

        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id,
        ingeschakeld=True)
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)
        # Nog niet ingediend → 409, nooit stil.
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boek-wachtrij/opnieuw-indienen", headers=headers
        )
        assert resp.status_code == 409 and "Wordt geboekt" in resp.json()["detail"]
        # Op wordt_geboekt (statusrij direct gezet, zoals ná een indiening) → 200 mét trigger-uitkomst.
        opgevangen: list[uuid.UUID] = []

        class _Wachtrij:
            def enqueue(self, *, administratie_id, document_id):  # noqa: ANN001, ANN202
                opgevangen.append(document_id)
                return None

        monkeypatch.setattr(boek_wachtrij, "_standaard_wachtrij", lambda: _Wachtrij())
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET status = 'wordt_geboekt' WHERE id = :id"), {"id": document_id})
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boek-wachtrij/opnieuw-indienen", headers=headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "wordt_geboekt" and body["trigger_uitkomst"] == "lokaal" and body["trigger_fout"] is None
        assert opgevangen == [uuid.UUID(document_id)]
        # Buiten de scope: 403 (bestaande poort).
        vreemde = _bearer(uuid.uuid4(), rol="boekhouding")
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boek-wachtrij/opnieuw-indienen", headers=vreemde
        )
        assert resp.status_code in (401, 403)
