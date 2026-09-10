from __future__ import annotations

import dataclasses
import uuid

import pytest
from sqlalchemy import Engine, text

from app.credentialstore import service
from app.rlz import leesroutes
from app.rlz.client import RlzApiError
from app.rlz.credentials import resolve_credentials
from tests.sync.conftest import FakeRlzClient


def _rlz_admin_id(admin_engine: Engine, administratie_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT rlz_admin_id FROM platform.administratie WHERE id = :id"), {"id": administratie_id}
        ).scalar_one()


def test_zet_credential_envelope_roundtrip_via_store(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    service.zet_credential(
        actor_id=beheerder_id,
        administratie_id=administratie_id,
        webservice_username="AK_Nijenhuis",
        wachtwoord="een-heel-geheim-wachtwoord",
    )

    with admin_engine.connect() as conn:
        ciphertext, wrapped_key = conn.execute(
            text(
                "SELECT wachtwoord_ciphertext, wrapped_data_key FROM platform.rlz_credential "
                "WHERE administratie_id = :id"
            ),
            {"id": administratie_id},
        ).one()
    assert bytes(ciphertext) != b"een-heel-geheim-wachtwoord"

    # De echte gebruikspad: resolve_credentials() (store-first) moet het originele wachtwoord
    # teruggeven — dit is de roundtrip die er echt toe doet, niet alleen unwrap_secret() los.
    rlz_admin_id = _rlz_admin_id(admin_engine, administratie_id)
    username, wachtwoord = resolve_credentials(rlz_admin_id)
    assert username == "AK_Nijenhuis"
    assert wachtwoord == "een-heel-geheim-wachtwoord"


def test_zet_credential_is_upsert(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    service.zet_credential(
        actor_id=beheerder_id, administratie_id=administratie_id, webservice_username="oud", wachtwoord="oud-ww"
    )
    service.zet_credential(
        actor_id=beheerder_id, administratie_id=administratie_id, webservice_username="nieuw", wachtwoord="nieuw-ww"
    )

    with admin_engine.connect() as conn:
        aantal = conn.execute(
            text("SELECT count(*) FROM platform.rlz_credential WHERE administratie_id = :id"),
            {"id": administratie_id},
        ).scalar_one()
    assert aantal == 1

    metadata = service.haal_credential_metadata_op(administratie_id=administratie_id)
    assert metadata is not None
    assert metadata.webservice_username == "nieuw"

    rlz_admin_id = _rlz_admin_id(admin_engine, administratie_id)
    _, wachtwoord = resolve_credentials(rlz_admin_id)
    assert wachtwoord == "nieuw-ww"


def test_zet_credential_onbekende_administratie_faalt(beheerder_id: uuid.UUID) -> None:
    with pytest.raises(service.CredentialStoreFout, match="Onbekende administratie"):
        service.zet_credential(
            actor_id=beheerder_id, administratie_id=uuid.uuid4(), webservice_username="x", wachtwoord="y"
        )


def test_credential_metadata_bevat_nooit_wachtwoord(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    service.zet_credential(
        actor_id=beheerder_id,
        administratie_id=administratie_id,
        webservice_username="AK_Nijenhuis",
        wachtwoord="topgeheim-123456",
    )
    metadata = service.haal_credential_metadata_op(administratie_id=administratie_id)
    assert metadata is not None
    velden = {f.name for f in dataclasses.fields(metadata)}
    assert "wachtwoord" not in velden
    assert "wachtwoord_ciphertext" not in velden
    waarden = str(dataclasses.asdict(metadata))
    assert "topgeheim-123456" not in waarden


def test_zet_credential_audit_event_bevat_nooit_wachtwoord(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    service.zet_credential(
        actor_id=beheerder_id,
        administratie_id=administratie_id,
        webservice_username="AK_Nijenhuis",
        wachtwoord="nooit-in-audit-event-99",
    )
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT actie, oude_waarde, nieuwe_waarde FROM platform.audit_event "
                "WHERE tabel = 'rlz_credential' AND record_id = :id"
            ),
            {"id": administratie_id},
        ).all()
    assert len(rijen) == 1
    actie, oude_waarde, nieuwe_waarde = rijen[0]
    assert actie == "credential_aangemaakt"
    volledige_tekst = f"{oude_waarde}{nieuwe_waarde}"
    assert "nooit-in-audit-event-99" not in volledige_tekst
    assert nieuwe_waarde == {"webservice_username": "AK_Nijenhuis"}


def test_importeer_env_credentials_slaat_onbekende_prefixen_en_lege_envvars_over(
    beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine
) -> None:
    for prefix in ("RLZ", "UNIVERSAL", "TESTADMIN", "KEMPEN", "RUBICON"):
        monkeypatch.delenv(f"{prefix}_USERNAME", raising=False)
        monkeypatch.delenv(f"{prefix}_PASSWORD", raising=False)

    monkeypatch.setenv("UNIVERSAL_USERNAME", "universal-login")
    monkeypatch.setenv("UNIVERSAL_PASSWORD", "universal-ww")
    monkeypatch.setenv("KEMPEN_USERNAME", "kempen-login")
    monkeypatch.setenv("KEMPEN_PASSWORD", "kempen-ww")

    resultaten = service.importeer_env_credentials(actor_id=beheerder_id)

    assert resultaten["RLZ"] == "overgeslagen: env-vars niet gevuld"
    assert resultaten["TESTADMIN"] == "overgeslagen: env-vars niet gevuld"
    assert resultaten["RUBICON"] == "overgeslagen: env-vars niet gevuld"
    assert resultaten["KEMPEN"] == "overgeslagen: geen geregistreerd RLZ-adminId voor deze prefix"
    assert resultaten["UNIVERSAL"].startswith("geïmporteerd")

    with admin_engine.connect() as conn:
        rlz_admin_id, username = conn.execute(
            text(
                "SELECT a.rlz_admin_id, c.webservice_username FROM platform.rlz_credential c "
                "JOIN platform.administratie a ON a.id = c.administratie_id "
                "WHERE a.naam = 'Universal Steigerbouw B.V.'"
            )
        ).one()
    assert rlz_admin_id == "3d954fc7-fe8d-4067-8cfb-73b4fe48c0ac"
    assert username == "universal-login"


def test_probe_report_met_gemockte_403_en_root_client_voor_administrations(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    fout = RlzApiError(403, "GET", "/x/TaxRates", "forbidden")
    client = FakeRlzClient({}, fouten={"TaxRates": fout})

    rapport = service.voer_rechten_probe_uit(administratie_id=administratie_id, actor_id=beheerder_id, client=client)

    assert rapport["TaxRates"] == "403"
    assert rapport["Ledgers"] == "ok"
    assert rapport["Administrations"] == "ok"
    assert len(rapport) == 10

    with admin_engine.connect() as conn:
        opgeslagen = conn.execute(
            text("SELECT rapport FROM platform.rlz_rechten_probe WHERE administratie_id = :id"),
            {"id": administratie_id},
        ).scalar_one()
    assert opgeslagen == rapport

    with admin_engine.connect() as conn:
        actie = conn.execute(
            text(
                "SELECT actie FROM platform.audit_event WHERE tabel = 'rlz_rechten_probe' "
                "AND record_id = :id"
            ),
            {"id": administratie_id},
        ).scalar_one()
    assert actie == "rechten_probe_uitgevoerd"

    # Meegegeven client blijft van de aanroeper.
    assert client.closed is False


def test_probe_onbekende_administratie_faalt(beheerder_id: uuid.UUID) -> None:
    with pytest.raises(service.CredentialStoreFout, match="Onbekende administratie"):
        service.voer_rechten_probe_uit(
            administratie_id=uuid.uuid4(), actor_id=beheerder_id, client=FakeRlzClient({})
        )


# --- Facturatiemodule niet afgenomen (spoedopdracht 01-09 blok A, casus A.Y. Holding 2 + Abbegaa) ----


def _rapport(**afwijkingen: str) -> dict[str, str]:
    basis = {e: "ok" for e in service._TE_PROBEREN_ENDPOINTS}
    basis.update(afwijkingen)
    return basis


class TestProbeIsGroenMetFacturatiemoduleUitzondering:
    def test_salesinvoices_403_is_de_enige_niet_blokkerende_uitkomst(self) -> None:
        assert service.probe_is_groen(_rapport()) is True
        assert service.probe_is_groen(_rapport(SalesInvoices="403")) is True
        # Elke andere route én elke andere fout op SalesInvoices blijft hard rood.
        assert service.probe_is_groen(_rapport(Ledgers="403")) is False
        assert service.probe_is_groen(_rapport(SalesInvoices="500")) is False
        assert service.probe_is_groen(_rapport(SalesInvoices="403", Vendors="403")) is False
        assert service.probe_is_groen({}) is False

    def test_verkoopmodule_afwezig_in_kijkt_uitsluitend_naar_salesinvoices_403(self) -> None:
        assert service.verkoopmodule_afwezig_in(_rapport(SalesInvoices="403")) is True
        assert service.verkoopmodule_afwezig_in(_rapport()) is False
        assert service.verkoopmodule_afwezig_in(_rapport(SalesInvoices="500")) is False

    def test_beschrijf_probe_fouten_geeft_handelingsperspectief_bij_echte_403(self) -> None:
        tekst = service.beschrijf_probe_fouten(_rapport(Ledgers="403", JournalEntries="500", SalesInvoices="403"))
        # 10-09 blok C: mét het RLZ-recht dat gezet moet worden (leesroutes.rlz_recht)
        assert "Ledgers=403 (geef de webservice-gebruiker in RLZ leesrecht op Ledgers: leesrecht Grootboek" in tekst
        assert "JournalEntries=500" in tekst
        # De SalesInvoices-403 is geen fout (facturatiemodule) en hoort hier niet tussen.
        assert "SalesInvoices" not in tekst


class TestKenmerkVerkoopmoduleAfwezig:
    def _kenmerk(self, admin_engine: Engine, administratie_id: uuid.UUID) -> bool:
        with admin_engine.connect() as conn:
            return conn.execute(
                text("SELECT verkoopmodule_afwezig FROM platform.administratie WHERE id = :id"),
                {"id": administratie_id},
            ).scalar_one()

    def test_probe_met_salesinvoices_403_zet_het_kenmerk_en_auditeert(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        client = FakeRlzClient({}, fouten={"SalesInvoices": RlzApiError(403, "GET", "/x/SalesInvoices", "forbidden")})
        rapport = service.voer_rechten_probe_uit(
            administratie_id=administratie_id, actor_id=beheerder_id, client=client
        )
        assert service.probe_is_groen(rapport) is True
        assert self._kenmerk(admin_engine, administratie_id) is True
        with admin_engine.connect() as conn:
            oud, nieuw = conn.execute(
                text(
                    "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                    "WHERE tabel = 'administratie' AND record_id = :id AND actie = 'verkoopmodule_afwezig_gewijzigd'"
                ),
                {"id": administratie_id},
            ).one()
        assert oud == {"verkoopmodule_afwezig": False}
        assert nieuw == {"verkoopmodule_afwezig": True, "bron": "rechten_probe"}

    def test_geslaagde_herprobe_wist_het_kenmerk(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        met_403 = FakeRlzClient({}, fouten={"SalesInvoices": RlzApiError(403, "GET", "/x/SalesInvoices", "")})
        service.voer_rechten_probe_uit(administratie_id=administratie_id, actor_id=beheerder_id, client=met_403)
        assert self._kenmerk(admin_engine, administratie_id) is True
        service.voer_rechten_probe_uit(
            administratie_id=administratie_id, actor_id=beheerder_id, client=FakeRlzClient({})
        )
        assert self._kenmerk(admin_engine, administratie_id) is False

    def test_andere_salesinvoices_fout_laat_het_kenmerk_staan(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        met_403 = FakeRlzClient({}, fouten={"SalesInvoices": RlzApiError(403, "GET", "/x/SalesInvoices", "")})
        service.voer_rechten_probe_uit(administratie_id=administratie_id, actor_id=beheerder_id, client=met_403)
        met_500 = FakeRlzClient({}, fouten={"SalesInvoices": RlzApiError(500, "GET", "/x/SalesInvoices", "")})
        service.voer_rechten_probe_uit(administratie_id=administratie_id, actor_id=beheerder_id, client=met_500)
        # 500 = geen uitspraak over de facturatiemodule — het kenmerk blijft staan.
        assert self._kenmerk(admin_engine, administratie_id) is True


# --- Blok C 10-09 (Baard): letterlijk RLZ-antwoord + RLZ-recht in rapport, melding en audit --------------------


class TestProbeMeldingen:
    def test_voer_probe_uit_bewaart_het_letterlijke_rlz_antwoord_afgekapt(self) -> None:
        lang = "x" * 400
        fouten = {
            "Ledgers": RlzApiError(403, "GET", "/a/Ledgers", '{"error":{"code":"_Forbidden","message":"Geen recht"}}'),
            "Vendors": RlzApiError(403, "GET", "/a/Vendors", lang),
        }
        uitkomst = service.voer_probe_uit(FakeRlzClient({}, fouten=fouten), "a")
        assert uitkomst.rapport["Ledgers"] == "403" and uitkomst.rapport["TaxRates"] == "ok"
        assert uitkomst.meldingen["Ledgers"] == 'HTTP 403 — {"error":{"code":"_Forbidden","message":"Geen recht"}}'
        assert len(uitkomst.meldingen["Vendors"]) == service.RLZ_MELDING_MAX + len("HTTP 403 — ")
        assert uitkomst.meldingen["Vendors"].endswith("…")
        assert "TaxRates" not in uitkomst.meldingen

    def test_beschrijf_probe_fouten_noemt_rlz_recht_en_rlz_antwoord(self) -> None:
        tekst = service.beschrijf_probe_fouten(
            _rapport(Ledgers="403", PaymentAccounts="403", JournalEntries="401"),
            {"Ledgers": "HTTP 403 — _Forbidden", "PaymentAccounts": "HTTP 403 — (leeg antwoord)"},
        )
        assert "Ledgers=403 (geef de webservice-gebruiker in RLZ leesrecht op Ledgers: leesrecht Grootboek" in tekst
        assert 'RLZ zegt: "HTTP 403 — _Forbidden"' in tekst
        assert "PaymentAccounts=403" in tekst and "Bank/Kas" in tekst
        assert "JournalEntries=401 (Reeleezee weigert de login zelf" in tekst

    def test_herprobe_met_opgeslagen_login_auditeert_rapport_meldingen_en_bron(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        fout = RlzApiError(403, "GET", "/x/Projects", "_Forbidden: Projects")
        uitkomst = service.voer_herprobe_met_opgeslagen_login(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            client=FakeRlzClient({}, fouten={"Projects": fout}),
        )
        assert uitkomst.rapport["Projects"] == "403"
        assert uitkomst.meldingen == {"Projects": "HTTP 403 — _Forbidden: Projects"}
        with admin_engine.connect() as conn:
            nieuw = conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event WHERE tabel = 'rlz_rechten_probe' "
                    "AND record_id = :id ORDER BY tijdstip DESC LIMIT 1"
                ),
                {"id": administratie_id},
            ).scalar_one()
        assert nieuw["bron"] == "herprobe_opgeslagen_login"
        assert nieuw["meldingen"] == {"Projects": "HTTP 403 — _Forbidden: Projects"}
        assert nieuw["rapport"]["Projects"] == "403" and nieuw["aantal_ok"] == 9


# --- RLZ-check als knop (nachtrun 10/11-09 blok 1): rechten, zichtbare administraties, eigen id ------------------


class TestRlzCheckVelden:
    def test_voer_probe_uit_geeft_recht_per_route_ook_bij_groen(self) -> None:
        uitkomst = service.voer_probe_uit(FakeRlzClient({}), "adm-1")
        assert set(uitkomst.rechten) == set(uitkomst.rapport) and len(uitkomst.rechten) == 10
        assert uitkomst.rechten["Ledgers"].startswith("leesrecht Grootboek")
        assert uitkomst.rechten["Administrations"] == leesroutes.ADMINISTRATIONS.rlz_recht
        assert uitkomst.rlz_admin_id == "adm-1"

    def test_administraties_zichtbaar_komt_uit_dezelfde_administrations_call(self) -> None:
        """De lijst is het antwoord van de probe-route `Administrations` zelf — geen tweede request."""
        client = FakeRlzClient(
            {"Administrations": [{"id": "adm-1", "Name": "Baard beheer"}, {"id": "adm-2", "Name": "Box Beheer B.V."}]}
        )
        uitkomst = service.voer_probe_uit(client, "adm-1")
        assert uitkomst.administraties_zichtbaar == [
            {"id": "adm-1", "naam": "Baard beheer"},
            {"id": "adm-2", "naam": "Box Beheer B.V."},
        ]
        assert uitkomst.administraties_fout is None
        assert client.opgevraagde_paden.count("Administrations") == 1

    def test_administrations_fout_geeft_lege_lijst_met_letterlijke_melding(self) -> None:
        fout = RlzApiError(401, "GET", "/Administrations", '{"Message":"Unauthorized"}')
        uitkomst = service.voer_probe_uit(FakeRlzClient({}, fouten={"Administrations": fout}), "adm-1")
        assert uitkomst.rapport["Administrations"] == "401"
        assert uitkomst.administraties_zichtbaar == []
        assert uitkomst.administraties_fout == 'HTTP 401 — {"Message":"Unauthorized"}'
        # De andere routes lopen gewoon door (per route zichtbaar, niets valt stil weg).
        assert uitkomst.rapport["Ledgers"] == "ok"

    def test_eigen_id_niet_in_de_lijst_is_zichtbaar_via_rlz_admin_id(self) -> None:
        """Verkeerd administratie-id: RLZ ziet wél administraties, maar niet de geprobeerde — de UI legt
        `rlz_admin_id` naast `administraties_zichtbaar`."""
        client = FakeRlzClient({"Administrations": [{"id": "adm-2", "Name": "Andere B.V."}]})
        uitkomst = service.voer_probe_uit(client, "adm-1")
        assert uitkomst.rlz_admin_id == "adm-1"
        assert "adm-1" not in {a["id"] for a in uitkomst.administraties_zichtbaar}

    def test_onverwacht_antwoord_zonder_value_geeft_lege_lijst_zonder_fout(self) -> None:
        class RaarAntwoord(FakeRlzClient):
            def get(self, path: str) -> dict:  # type: ignore[override]
                if path == "Administrations":
                    return {"geen": "value"}
                return super().get(path)

        uitkomst = service.voer_probe_uit(RaarAntwoord({}), "adm-1")
        assert uitkomst.rapport["Administrations"] == "ok"
        assert uitkomst.administraties_zichtbaar == [] and uitkomst.administraties_fout is None

    def test_herprobe_met_opgeslagen_login_draagt_de_velden_door(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        rlz_admin_id = _rlz_admin_id(admin_engine, administratie_id)
        client = FakeRlzClient({"Administrations": [{"id": rlz_admin_id, "Name": "Eigen"}]})
        uitkomst = service.voer_herprobe_met_opgeslagen_login(
            administratie_id=administratie_id, actor_id=beheerder_id, client=client
        )
        assert uitkomst.rlz_admin_id == rlz_admin_id
        assert uitkomst.administraties_zichtbaar == [{"id": rlz_admin_id, "naam": "Eigen"}]
        assert uitkomst.rechten["PaymentAccounts"] == leesroutes.PAYMENT_ACCOUNTS.rlz_recht
