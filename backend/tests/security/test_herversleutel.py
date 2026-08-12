"""Masterkey-herversleuteling (scripts/herversleutel_masterkey.py → app/security/
herversleutel.py) op een gevulde testdatabase: credential-store + TOTP-secrets gewrapt met
een oude lokale masterkey, herversleuteld naar een nieuwe provider (lokaal én fake-KMS).
Dit is de vangrail tegen de kluis-zonder-sleutel — de tests bewijzen dry-run-onschadelijkheid,
de echte omzetting, hervatbaarheid en dat een onontsleutelbare rij nooit stil passeert."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import RlzCredential, TotpSecret
from app.security.envelope import LocalMasterKeyProvider, unwrap_secret, wrap_secret
from app.security.herversleutel import ENVELOPE_TABELLEN, herversleutel_alles
from tests.unit.test_envelope_kms import SLEUTEL as KMS_SLEUTEL
from tests.unit.test_envelope_kms import FakeKmsClient

OUDE_KEY = b"\x01" * 32
NIEUWE_KEY = b"\x02" * 32
VREEMDE_KEY = b"\x03" * 32

oud = LocalMasterKeyProvider(OUDE_KEY)
nieuw = LocalMasterKeyProvider(NIEUWE_KEY)


@pytest.fixture
def sessie(admin_engine: Engine) -> Iterator[Session]:
    s = sessionmaker(bind=admin_engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture
def gevulde_database(admin_engine: Engine, beheerder_id: uuid.UUID) -> dict[str, list[uuid.UUID]]:
    """Twee administraties mét credential + twee gebruikers mét TOTP-secret, alles gewrapt
    met de OUDE masterkey — de uitgangssituatie van de echte migratie."""
    admin_ids = [uuid.uuid4(), uuid.uuid4()]
    gebruiker_ids = [beheerder_id, uuid.uuid4()]
    with admin_engine.begin() as conn:
        for admin_id in admin_ids:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
                {"id": admin_id, "naam": f"Testadministratie {admin_id.hex[:6]}", "rlz": admin_id.hex[:8]},
            )
            ciphertext, wrapped = wrap_secret(f"wachtwoord-{admin_id.hex[:6]}".encode(), provider=oud)
            conn.execute(
                text(
                    "INSERT INTO platform.rlz_credential (administratie_id, webservice_username, "
                    "wachtwoord_ciphertext, wrapped_data_key, aangemaakt_door) "
                    "VALUES (:aid, 'login', :ct, :wk, :actor)"
                ),
                {"aid": admin_id, "ct": ciphertext, "wk": wrapped, "actor": beheerder_id},
            )
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'TOTP-gebruiker', :mail, 'boekhouding', 'actief')"
            ),
            {"id": gebruiker_ids[1], "mail": f"{gebruiker_ids[1]}@test.local"},
        )
        for gid in gebruiker_ids:
            ciphertext, wrapped = wrap_secret(f"totp-{gid.hex[:6]}".encode(), provider=oud)
            conn.execute(
                text(
                    "INSERT INTO platform.totp_secret (gebruiker_id, secret_ciphertext, wrapped_data_key) "
                    "VALUES (:gid, :ct, :wk)"
                ),
                {"gid": gid, "ct": ciphertext, "wk": wrapped},
            )
    return {"administraties": admin_ids, "gebruikers": gebruiker_ids}


def test_dry_run_telt_maar_schrijft_niets(sessie: Session, gevulde_database: dict) -> None:
    resultaat = herversleutel_alles(sessie, oud=oud, nieuw=nieuw, dry_run=True)
    sessie.rollback()

    assert resultaat.geslaagd
    assert resultaat.per_tabel["rlz_credential"].herversleuteld == 2
    assert resultaat.per_tabel["totp_secret"].herversleuteld == 2
    # Niets geschreven: alles is nog steeds uitsluitend met de OUDE key te lezen.
    for credential in sessie.query(RlzCredential):
        geheim = unwrap_secret(credential.wachtwoord_ciphertext, credential.wrapped_data_key, provider=oud)
        assert geheim.startswith(b"wachtwoord-")


def test_uitvoeren_herversleutelt_alles(sessie: Session, gevulde_database: dict) -> None:
    resultaat = herversleutel_alles(sessie, oud=oud, nieuw=nieuw, dry_run=False)
    sessie.commit()

    assert resultaat.geslaagd
    for credential in sessie.query(RlzCredential):
        geheim = unwrap_secret(credential.wachtwoord_ciphertext, credential.wrapped_data_key, provider=nieuw)
        assert geheim == f"wachtwoord-{credential.administratie_id.hex[:6]}".encode()
    for totp in sessie.query(TotpSecret):
        geheim = unwrap_secret(totp.secret_ciphertext, totp.wrapped_data_key, provider=nieuw)
        assert geheim == f"totp-{totp.gebruiker_id.hex[:6]}".encode()
    # En de oude key kan er níét meer bij (de wrap is echt vervangen, niet gedupliceerd) —
    # AES-GCM weigert met InvalidTag.
    from cryptography.exceptions import InvalidTag

    credential = sessie.query(RlzCredential).first()
    assert credential is not None
    with pytest.raises(InvalidTag):
        unwrap_secret(credential.wachtwoord_ciphertext, credential.wrapped_data_key, provider=oud)


def test_tweede_run_is_hervatbaar_idempotent(sessie: Session, gevulde_database: dict) -> None:
    herversleutel_alles(sessie, oud=oud, nieuw=nieuw, dry_run=False)
    sessie.commit()

    resultaat = herversleutel_alles(sessie, oud=oud, nieuw=nieuw, dry_run=False)
    assert resultaat.geslaagd
    assert resultaat.per_tabel["rlz_credential"].al_op_nieuw == 2
    assert resultaat.per_tabel["rlz_credential"].herversleuteld == 0
    assert resultaat.per_tabel["totp_secret"].al_op_nieuw == 2


def test_onontsleutelbare_rij_faalt_zichtbaar_en_stopt_de_rest_niet(
    sessie: Session, gevulde_database: dict, admin_engine: Engine
) -> None:
    vreemde = LocalMasterKeyProvider(VREEMDE_KEY)
    kapot_admin_id = gevulde_database["administraties"][0]
    ciphertext, wrapped = wrap_secret(b"onbereikbaar", provider=vreemde)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE platform.rlz_credential SET wachtwoord_ciphertext = :ct, wrapped_data_key = :wk "
                "WHERE administratie_id = :aid"
            ),
            {"ct": ciphertext, "wk": wrapped, "aid": kapot_admin_id},
        )

    resultaat = herversleutel_alles(sessie, oud=oud, nieuw=nieuw, dry_run=True)
    telling = resultaat.per_tabel["rlz_credential"]
    assert not resultaat.geslaagd
    assert telling.mislukt == 1
    assert telling.mislukte_rijen == [f"rlz_credential:{kapot_admin_id}"]
    assert telling.herversleuteld == 1  # de gezonde rij telt gewoon door
    assert resultaat.per_tabel["totp_secret"].mislukt == 0


def test_lokaal_naar_fake_kms_roundtrip(sessie: Session, gevulde_database: dict) -> None:
    """De echte migratieroute (beslispunt 8): lokale masterkey → Cloud KMS."""
    from app.security.envelope import KmsMasterKeyProvider

    kms = KmsMasterKeyProvider(KMS_SLEUTEL, client=FakeKmsClient())
    resultaat = herversleutel_alles(sessie, oud=oud, nieuw=kms, dry_run=False)
    sessie.commit()

    assert resultaat.geslaagd
    assert resultaat.per_tabel["rlz_credential"].herversleuteld == 2
    for credential in sessie.query(RlzCredential):
        geheim = unwrap_secret(credential.wachtwoord_ciphertext, credential.wrapped_data_key, provider=kms)
        assert geheim.startswith(b"wachtwoord-")


def test_geen_onbekende_envelope_tabellen() -> None:
    """Bewaakt dat een nieuwe tabel met een `wrapped_data_key`-kolom niet stil buiten het
    herversleutel-script valt (zie de module-docstring van app/security/herversleutel.py)."""
    from app.db.models import Base

    envelope_tabellen = {
        tabel.name for tabel in Base.metadata.tables.values() if "wrapped_data_key" in tabel.columns
    }
    gedekt = {model.__tablename__ for _, model, _, _ in ENVELOPE_TABELLEN}
    assert envelope_tabellen == gedekt, (
        f"Tabellen met wrapped_data_key ({envelope_tabellen}) wijken af van wat het "
        f"herversleutel-script dekt ({gedekt}) — voeg de nieuwe tabel toe aan "
        "app/security/herversleutel.py::ENVELOPE_TABELLEN."
    )
