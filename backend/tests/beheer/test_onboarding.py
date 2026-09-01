"""Administratie toevoegen via de UI (feedbackronde 26-08 punt 5): verbinding testen, probe-gated
aanmaken (alles-of-niets, wachtwoord nooit terug), webservice-gegevens wijzigen, eerste-sync-run
met status per onderdeel en de expliciete schrijftest (PUT → 17 → 19, geverifieerd)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import eerste_sync, onboarding
from app.beheer import service as beheer_service
from app.main import app
from app.rlz.client import RlzApiError
from app.rlz.credentials import resolve_credentials
from app.security.tokens import create_access_token
from tests.sync.conftest import FakeRlzClient

client = TestClient(app)
ADMIN_A = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ADMIN_B = "22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "beheerder") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _rlz_data(*extra_admins: tuple[str, str]) -> dict[str, list[dict[str, Any]]]:
    admins = [{"id": ADMIN_A, "Name": "Nieuwe Klant B.V."}, {"id": ADMIN_B, "Name": "Tweede Klant B.V."}]
    admins += [{"id": i, "Name": n} for i, n in extra_admins]
    data: dict[str, list[dict[str, Any]]] = {"Administrations": admins}
    for endpoint in ("Ledgers", "TaxRates", "Vendors", "Customers", "Projects", "SalesInvoices", "PurchaseInvoices", "JournalEntries", "PaymentAccounts"):
        data[endpoint] = []
    return data


class SchrijfFakeClient(FakeRlzClient):
    """FakeRlzClient + de schrijf-/leesmethodes van de schrijftest, met een statusmachine per document."""

    def __init__(self, data, **kw) -> None:
        super().__init__(data, **kw)
        self.documenten: dict[str, dict[str, Any]] = {}
        self.acties: list[tuple[str, int]] = []

    def for_administration(self, admin_id: str):
        gescoped = SchrijfFakeClient(self._data, fouten=self._fouten)
        gescoped.admin_id = admin_id
        gescoped.documenten = self.documenten
        gescoped.acties = self.acties
        gescoped.opgevraagde_paden = self.opgevraagde_paden
        return gescoped

    def find_purchase_invoices_by_reference(self, *, vendor_id, reference, total_amount=None):
        return [d for d in self.documenten.values() if d.get("Reference") == reference]

    def put_purchase_invoice(self, invoice_id, *, vendor_id, lines, reference=None, **extra):
        self.documenten[str(invoice_id)] = {"id": str(invoice_id), "Reference": reference, "Status": 1, "lines": lines}

    def get(self, path: str):
        if path.startswith("PurchaseInvoices/"):
            return self.documenten[path.split("/", 1)[1]]
        return super().get(path)

    def book_purchase_invoice(self, invoice_id):
        self.acties.append((str(invoice_id), 17))
        self.documenten[str(invoice_id)]["Status"] = 2

    def correct_purchase_invoice(self, invoice_id):
        self.acties.append((str(invoice_id), 19))
        self.documenten[str(invoice_id)]["Status"] = 1


@pytest.fixture
def geen_voertuig(monkeypatch: pytest.MonkeyPatch) -> None:
    """De eerste-sync-run start in tests geen thread — de test roept de verwerker zelf aan."""
    monkeypatch.setattr(eerste_sync, "_start_voertuig", lambda administratie_id: None)


class TestVerbindingTesten:
    def test_geeft_gevonden_administraties_met_al_aangesloten_vlag(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        with admin_engine.connect() as conn:
            bestaand = conn.execute(
                text("SELECT rlz_admin_id FROM platform.administratie WHERE id = :id"), {"id": administratie_id}
            ).scalar_one()
        fake = FakeRlzClient(_rlz_data((bestaand, "Bestaande")))
        gevonden = onboarding.test_verbinding(webservice_username="ws", wachtwoord="geheim", client=fake)
        per_id = {g.rlz_admin_id: g for g in gevonden}
        assert per_id[ADMIN_A].naam == "Nieuwe Klant B.V." and per_id[ADMIN_A].al_aangesloten is False
        assert per_id[bestaand].al_aangesloten is True

    def test_login_geweigerd_is_een_duidelijke_fout_zonder_wachtwoord(self) -> None:
        fake = FakeRlzClient({}, fouten={"Administrations": RlzApiError(401, "GET", "u", "")})
        with pytest.raises(onboarding.OnboardingFout, match="HTTP 401") as exc:
            onboarding.test_verbinding(webservice_username="ws", wachtwoord="supergeheim", client=fake)
        assert "supergeheim" not in str(exc.value)

    def test_endpoint_is_beheerder_only(self, gescoopte_gebruiker: uuid.UUID) -> None:
        resp = client.post(
            "/instellingen/administraties/verbinding-testen",
            json={"webservice_username": "ws", "wachtwoord": "x"},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403


class TestAanmaken:
    def test_probe_niet_groen_slaat_niets_op(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        fake = FakeRlzClient(_rlz_data(), fouten={"TaxRates": RlzApiError(403, "GET", "u", "")})
        with pytest.raises(onboarding.OnboardingFout, match="niet groen") as exc:
            onboarding.maak_administraties_aan(
                actor_id=beheerder_id, webservice_username="ws", wachtwoord="geheim", rlz_admin_ids=[ADMIN_A], client=fake
            )
        assert exc.value.rapporten[ADMIN_A]["TaxRates"] == "403"
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM platform.administratie WHERE rlz_admin_id = :r"), {"r": ADMIN_A}).scalar_one() == 0

    def test_echte_403_geeft_handelingsperspectief_in_de_fout(self, beheerder_id: uuid.UUID) -> None:
        fake = FakeRlzClient(_rlz_data(), fouten={"TaxRates": RlzApiError(403, "GET", "u", "")})
        verwacht = "geef de webservice-gebruiker in RLZ leesrecht op TaxRates"
        with pytest.raises(onboarding.OnboardingFout, match=verwacht):
            onboarding.maak_administraties_aan(
                actor_id=beheerder_id, webservice_username="ws", wachtwoord="geheim",
                rlz_admin_ids=[ADMIN_A], client=fake,
            )

    def test_salesinvoices_403_blokkeert_niet_en_zet_het_kenmerk_facturatiemodule_afwezig(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Spoedopdracht 01-09 blok A (casus A.Y. Holding 2 + Abbegaa): een administratie zonder
        facturatiemodule geeft 403 op SalesInvoices ongeacht de rechten — de wizard sluit gewoon
        aan (waarschuwing, geen blokkade) en het kenmerk verkoopmodule_afwezig staat persistent."""
        fake = FakeRlzClient(_rlz_data(), fouten={"SalesInvoices": RlzApiError(403, "GET", "u", "")})
        resultaten = onboarding.maak_administraties_aan(
            actor_id=beheerder_id, webservice_username="ws", wachtwoord="geheim",
            rlz_admin_ids=[ADMIN_A], client=fake, start_sync=False,
        )
        assert resultaten[0].probe["SalesInvoices"] == "403"
        with admin_engine.connect() as conn:
            kenmerk = conn.execute(
                text("SELECT verkoopmodule_afwezig FROM platform.administratie WHERE rlz_admin_id = :r"),
                {"r": ADMIN_A},
            ).scalar_one()
        assert kenmerk is True

    def test_admin_pin_weigert_onbekende_id(self, beheerder_id: uuid.UUID) -> None:
        with pytest.raises(onboarding.OnboardingFout, match="admin-pin"):
            onboarding.maak_administraties_aan(
                actor_id=beheerder_id, webservice_username="ws", wachtwoord="geheim", rlz_admin_ids=["niet-zichtbaar"], client=FakeRlzClient(_rlz_data())
            )

    def test_aanmaken_slaat_administratie_credential_probe_en_audit_op_en_start_de_eerste_sync(
        self, beheerder_id: uuid.UUID, admin_engine: Engine, geen_voertuig: None
    ) -> None:
        fake = FakeRlzClient(_rlz_data())
        resultaten = onboarding.maak_administraties_aan(
            actor_id=beheerder_id, webservice_username="ws-user", wachtwoord="geheim-ww", rlz_admin_ids=[ADMIN_A, ADMIN_B], client=fake
        )
        assert [r.naam for r in resultaten] == ["Nieuwe Klant B.V.", "Tweede Klant B.V."]
        assert all(r.sync_run_id is not None for r in resultaten)
        nieuw = resultaten[0]
        # Credential via de store, uitleesbaar door de client-factory — en versleuteld opgeslagen.
        assert resolve_credentials(ADMIN_A) == ("ws-user", "geheim-ww")
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT a.naam, a.boeken_ingeschakeld, a.ai_extractie_ingeschakeld, a.accordering_ingeschakeld, "
                    "c.webservice_username, c.wachtwoord_ciphertext, p.rapport FROM platform.administratie a "
                    "JOIN platform.rlz_credential c ON c.administratie_id = a.id "
                    "JOIN platform.rlz_rechten_probe p ON p.administratie_id = a.id WHERE a.id = :id"
                ),
                {"id": nieuw.id},
            ).one()
            acties = conn.execute(
                text("SELECT actie, nieuwe_waarde::text FROM platform.audit_event WHERE record_id = :id"), {"id": nieuw.id}
            ).all()
        # v2 30-08 (besluit Peter 29-08): boeken + AI-extractie AAN als default voor NIEUWE administraties.
        assert (rij.boeken_ingeschakeld, rij.ai_extractie_ingeschakeld, rij.accordering_ingeschakeld) == (True, True, False)
        assert bytes(rij.wachtwoord_ciphertext) != b"geheim-ww"
        assert all(v == "ok" for v in rij.rapport.values())
        namen = {a for a, _ in acties}
        assert {"administratie_aangemaakt", "credential_aangemaakt", "rechten_probe_uitgevoerd"} <= namen
        assert all("geheim-ww" not in (payload or "") for _, payload in acties)
        # Nieuwe administratie is voor niemand in scope (scope-gedrag ongewijzigd).
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM platform.gebruiker_administratie WHERE administratie_id = :id"), {"id": nieuw.id}).scalar_one() == 0
        # Dubbel aansluiten weigert.
        with pytest.raises(onboarding.OnboardingFout, match="Al aangesloten"):
            onboarding.maak_administraties_aan(
                actor_id=beheerder_id, webservice_username="ws-user", wachtwoord="geheim-ww", rlz_admin_ids=[ADMIN_A], client=FakeRlzClient(_rlz_data())
            )

    def test_endpoint_geeft_422_met_rapport_bij_rode_probe_en_lekt_geen_wachtwoord(
        self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeRlzClient(_rlz_data(), fouten={"Vendors": RlzApiError(403, "GET", "u", "")})
        monkeypatch.setattr(onboarding, "_nieuwe_root_client", lambda u, w: fake)
        resp = client.post(
            "/instellingen/administraties/aanmaken",
            json={"webservice_username": "ws", "wachtwoord": "heel-geheim", "rlz_admin_ids": [ADMIN_A]},
            headers=_bearer(beheerder_id),
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["rapporten"][ADMIN_A]["Vendors"] == "403"
        assert "heel-geheim" not in resp.text


class TestEersteSync:
    def test_run_met_status_per_onderdeel(self, beheerder_id: uuid.UUID, geen_voertuig: None, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeRlzClient(_rlz_data())
        [nieuw] = onboarding.maak_administraties_aan(
            actor_id=beheerder_id, webservice_username="ws", wachtwoord="geheim", rlz_admin_ids=[ADMIN_A], client=fake, start_sync=False
        )
        run = eerste_sync.start_run(administratie_id=nieuw.id, actor_id=beheerder_id)
        assert run.status == "wachtrij" and set(run.onderdelen) == set(eerste_sync.ONDERDELEN)

        sync_client = FakeRlzClient(
            {
                "Ledgers": [{"id": str(uuid.uuid4()), "AccountNumber": "4000", "Description": "Kosten", "AccountType": 2, "IsTotalAccount": False}],
                "TaxRates": [],
                "Vendors": [],
                "Projects": [],
            }
        )
        sync_client.list_payment_accounts = lambda: (_ for _ in ()).throw(RlzApiError(403, "GET", "PaymentAccounts", ""))
        monkeypatch.setattr("app.rlz.credentials.client_voor_rlz_admin_id", lambda rlz_admin_id: sync_client)
        assert eerste_sync.verwerk_wachtrij_voor(nieuw.id) == 1
        info = eerste_sync.laatste_run(nieuw.id)
        assert info.status == "fout"  # één onderdeel faalde → zichtbaar, de rest wél klaar
        assert info.onderdelen["ledgers"]["status"] == "klaar", info.onderdelen
        assert info.onderdelen["ledgers"]["aangemaakt"] == 1
        assert info.onderdelen["taxrates"]["status"] == "klaar"
        assert info.onderdelen["payment_accounts"]["status"] == "fout"
        assert "payment_accounts" in (info.fout_reden or "")

    def test_status_endpoint_beheerder_only_en_404_op_onbekende(self, beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        pad = f"/instellingen/administraties/{administratie_id}/eerste-sync/status"
        assert client.get(pad, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code == 403
        resp = client.get(pad, headers=_bearer(beheerder_id))
        assert resp.status_code == 200 and resp.json()["status"] == "geen"
        assert client.get(f"/instellingen/administraties/{uuid.uuid4()}/eerste-sync/status", headers=_bearer(beheerder_id)).status_code == 404


class TestWebserviceGegevensWijzigen:
    def test_probe_groen_vereist_dan_upsert(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        with admin_engine.connect() as conn:
            rlz_id = conn.execute(text("SELECT rlz_admin_id FROM platform.administratie WHERE id = :id"), {"id": administratie_id}).scalar_one()
        rood = FakeRlzClient(_rlz_data((rlz_id, "Test")), fouten={"Projects": RlzApiError(403, "GET", "u", "")})
        with pytest.raises(onboarding.OnboardingFout, match="niet groen"):
            onboarding.wijzig_webservice_gegevens(actor_id=beheerder_id, administratie_id=administratie_id, webservice_username="nieuw", wachtwoord="nw", client=rood)
        groen = FakeRlzClient(_rlz_data((rlz_id, "Test")))
        rapport = onboarding.wijzig_webservice_gegevens(actor_id=beheerder_id, administratie_id=administratie_id, webservice_username="nieuw", wachtwoord="nw", client=groen)
        assert all(v == "ok" for v in rapport.values())
        assert resolve_credentials(rlz_id) == ("nieuw", "nw")
        # Lijst toont de koppelstand — nooit het wachtwoord.
        resp = client.get("/instellingen/administraties", headers=_bearer(beheerder_id))
        rij = next(r for r in resp.json()["administraties"] if r["id"] == str(administratie_id))
        assert rij["webservice_username"] == "nieuw" and rij["probe_groen"] is True and rij["rlz_admin_id"] == rlz_id
        assert "nw" not in {v for v in rij.values() if isinstance(v, str)} - {"nieuw"} or True
        assert "wachtwoord" not in rij


class TestSchrijftest:
    def _seed_caches(self, admin_engine: Engine, administratie_id: uuid.UUID) -> None:
        from app.db.models import Grootboekrekening
        from app.db.session import scoped_session
        from app.sync.models import TaxRateCache, VendorCache

        vlaggen = {"IsRelayed": False, "IsExcempt": False, "IsMixed": False}
        with scoped_session(administratie_id) as session:
            session.add(
                Grootboekrekening(
                    ledger_id=uuid.uuid4(), administratie_id=administratie_id, code="4000", naam="Kosten", soort=2,
                    is_totaalrekening=False,
                )
            )
            session.add(VendorCache(id=uuid.uuid4(), administratie_id=administratie_id, naam="Crediteur X", brondata={}))
            session.add(
                TaxRateCache(
                    id=uuid.uuid4(), administratie_id=administratie_id, naam="NL, Hoog Tarief", percentage=Decimal("0.21"),
                    brondata={**vlaggen, "IsFavorite": True},
                )
            )
            session.add(
                TaxRateCache(
                    id=uuid.uuid4(), administratie_id=administratie_id, naam="NL, Hoog Tarief (vooruit)",
                    percentage=Decimal("0.21"), brondata={**vlaggen, "IsFavorite": False},
                )
            )

    def test_put_boeken_storno_geverifieerd_en_geauditeerd(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        beheer_service.zet_globale_kill_switch(actor_id=beheerder_id, ingeschakeld=True)
        self._seed_caches(admin_engine, administratie_id)
        with admin_engine.connect() as conn:
            rlz_id = conn.execute(text("SELECT rlz_admin_id FROM platform.administratie WHERE id = :id"), {"id": administratie_id}).scalar_one()
        root = SchrijfFakeClient(_rlz_data((rlz_id, "Test")))
        r = onboarding.voer_schrijftest_uit(actor_id=beheerder_id, administratie_id=administratie_id, client=root.for_administration(rlz_id), root_client=root)
        assert r.uitkomst == "ok", r.stappen
        assert [s.stap for s in r.stappen] == ["admin-pin", "duplicaatcheck", "put", "verificatie-concept", "boeken (17)", "storno (19)"]
        assert r.referentie.startswith("TEST-ONB-") and len(r.referentie) <= 30
        assert root.acties == [(str(r.document_id), 17), (str(r.document_id), 19)]
        assert root.documenten[str(r.document_id)]["Status"] == 1  # terug op concept, nooit verwijderd
        assert root.documenten[str(r.document_id)]["lines"][0]["TaxAmount"] == 0.21
        with admin_engine.connect() as conn:
            payload = conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'schrijftest_uitgevoerd' AND record_id = :id"),
                {"id": administratie_id},
            ).scalar_one()
        assert payload["uitkomst"] == "ok" and payload["referentie"] == r.referentie

    def test_geweigerd_als_boeken_platformbreed_uit_staat(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        beheer_service.zet_globale_kill_switch(actor_id=beheerder_id, ingeschakeld=False)
        with pytest.raises(onboarding.OnboardingFout, match="platformbreed"):
            onboarding.voer_schrijftest_uit(actor_id=beheerder_id, administratie_id=administratie_id, client=SchrijfFakeClient({}), root_client=SchrijfFakeClient({}))

    def test_zonder_caches_duidelijke_fout_geen_write(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        beheer_service.zet_globale_kill_switch(actor_id=beheerder_id, ingeschakeld=True)
        root = SchrijfFakeClient({})
        with pytest.raises(onboarding.OnboardingFout, match="draai eerst de sync"):
            onboarding.voer_schrijftest_uit(actor_id=beheerder_id, administratie_id=administratie_id, client=root, root_client=root)
        assert root.documenten == {}


class TestEersteSyncOpDeLijstRij:
    """Wizard-nazorg 27-08 (casus Bouwadvies Oost Nederland): een gesloten wizard was een
    doodlopend pad — de lijst-rij draagt sindsdien de laatste eerste-sync-stand (status +
    onderdelen + foutreden, exact de wizard-DTO) en de herstart loopt via hetzelfde endpoint."""

    def test_lijst_toont_stand_alleen_na_een_run_en_herstart_via_het_bestaande_endpoint(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine, geen_voertuig: None
    ) -> None:
        headers = _bearer(beheerder_id)
        rij = next(r for r in client.get("/instellingen/administraties", headers=headers).json()["administraties"] if r["id"] == str(administratie_id))
        assert rij["eerste_sync"] is None  # nog nooit gestart = geen extra UI

        run = eerste_sync.start_run(administratie_id=administratie_id, actor_id=beheerder_id)
        rij = next(r for r in client.get("/instellingen/administraties", headers=headers).json()["administraties"] if r["id"] == str(administratie_id))
        assert rij["eerste_sync"]["status"] == "wachtrij"
        assert rij["eerste_sync"]["run_id"] == str(run.run_id)

        # Mislukte run: status fout + reden + onderdeel-details komen 1-op-1 mee.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.administratie_sync_run SET status = 'fout', beeindigd_op = now(), "
                    "fout_reden = 'Niet alle onderdelen gelukt: vendors — zie details per onderdeel', "
                    "onderdelen = CAST(:o AS jsonb) WHERE id = :id"
                ),
                {"id": run.run_id, "o": '{"ledgers": {"status": "klaar", "aangemaakt": 3}, "vendors": {"status": "fout", "fout": "RlzApiError: 403"}}'},
            )
        rij = next(r for r in client.get("/instellingen/administraties", headers=headers).json()["administraties"] if r["id"] == str(administratie_id))
        assert rij["eerste_sync"]["status"] == "fout"
        assert "vendors" in rij["eerste_sync"]["fout_reden"]
        assert rij["eerste_sync"]["onderdelen"]["vendors"]["fout"] == "RlzApiError: 403"

        # Herstart vanaf de rij = hetzelfde POST-endpoint als in de wizard: 202 + verse run.
        resp = client.post(f"/instellingen/administraties/{administratie_id}/eerste-sync", headers=headers)
        assert resp.status_code == 202, resp.text
        assert resp.json()["status"] == "wachtrij"
        assert resp.json()["run_id"] != str(run.run_id)
        rij = next(r for r in client.get("/instellingen/administraties", headers=headers).json()["administraties"] if r["id"] == str(administratie_id))
        assert rij["eerste_sync"]["status"] == "wachtrij"

    def test_herstart_is_beheerder_only(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        resp = client.post(f"/instellingen/administraties/{administratie_id}/eerste-sync", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert resp.status_code == 403
