from __future__ import annotations

import dataclasses
import uuid

import pytest
from sqlalchemy import Engine, text

from app.credentialstore import service
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
