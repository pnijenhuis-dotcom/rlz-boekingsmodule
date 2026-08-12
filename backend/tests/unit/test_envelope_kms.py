"""KmsMasterKeyProvider (GCP-draaiboek F1.3b): unit-tests tegen een fake-KMS-client — geen
netwerk, wel de volledige request/respons-vorm van google-cloud-kms incl. de
CRC32C-integriteitsvelden. De fake 'versleutelt' met een omkeerbare XOR zodat wrap/unwrap
een echte roundtrip is en een verkeerde sleutelnaam echt stukloopt."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.security import envelope
from app.security.envelope import (
    KmsMasterKeyProvider,
    LocalMasterKeyProvider,
    _crc32c,
    standaard_masterkey_provider,
    unwrap_secret,
    wrap_secret,
)


class FakeKmsClient:
    """Bootst KeyManagementServiceClient.encrypt/decrypt na. XOR met een uit de sleutelnaam
    afgeleide bytereeks: deterministisch, omkeerbaar, en per sleutelnaam verschillend."""

    def __init__(self, *, knoei_met_encrypt_crc: bool = False, knoei_met_decrypt_crc: bool = False) -> None:
        self.knoei_met_encrypt_crc = knoei_met_encrypt_crc
        self.knoei_met_decrypt_crc = knoei_met_decrypt_crc

    @staticmethod
    def _xor(naam: str, data: bytes) -> bytes:
        import hashlib

        digest = hashlib.sha256(naam.encode()).digest()
        sleutel = (digest * (len(data) // len(digest) + 1))[: len(data)]
        return bytes(a ^ b for a, b in zip(data, sleutel, strict=True))

    def encrypt(self, request: dict) -> SimpleNamespace:
        assert request["plaintext_crc32c"] == _crc32c(request["plaintext"])
        ciphertext = self._xor(request["name"], request["plaintext"])
        return SimpleNamespace(
            ciphertext=ciphertext,
            ciphertext_crc32c=_crc32c(ciphertext) + (1 if self.knoei_met_encrypt_crc else 0),
            verified_plaintext_crc32c=True,
        )

    def decrypt(self, request: dict) -> SimpleNamespace:
        assert request["ciphertext_crc32c"] == _crc32c(request["ciphertext"])
        plaintext = self._xor(request["name"], request["ciphertext"])
        return SimpleNamespace(
            plaintext=plaintext,
            plaintext_crc32c=_crc32c(plaintext) + (1 if self.knoei_met_decrypt_crc else 0),
        )


SLEUTEL = "projects/rlz-boekhouding/locations/europe-west4/keyRings/rlz/cryptoKeys/masterkey"


def test_wrap_unwrap_roundtrip() -> None:
    provider = KmsMasterKeyProvider(SLEUTEL, client=FakeKmsClient())
    data_key = b"\x07" * 32
    wrapped = provider.wrap(data_key)
    assert wrapped != data_key
    assert provider.unwrap(wrapped) == data_key


def test_andere_sleutelnaam_geeft_andere_wrap() -> None:
    client = FakeKmsClient()
    a = KmsMasterKeyProvider(SLEUTEL, client=client)
    b = KmsMasterKeyProvider(SLEUTEL + "-2", client=client)
    assert a.wrap(b"\x07" * 32) != b.wrap(b"\x07" * 32)


def test_envelope_roundtrip_via_kms_provider() -> None:
    provider = KmsMasterKeyProvider(SLEUTEL, client=FakeKmsClient())
    ciphertext, wrapped_key = wrap_secret(b"rlz-webservice-wachtwoord", provider=provider)
    assert unwrap_secret(ciphertext, wrapped_key, provider=provider) == b"rlz-webservice-wachtwoord"


def test_encrypt_crc_mismatch_is_harde_fout() -> None:
    provider = KmsMasterKeyProvider(SLEUTEL, client=FakeKmsClient(knoei_met_encrypt_crc=True))
    with pytest.raises(RuntimeError, match="CRC32C"):
        provider.wrap(b"\x07" * 32)


def test_decrypt_crc_mismatch_is_harde_fout() -> None:
    goede = KmsMasterKeyProvider(SLEUTEL, client=FakeKmsClient())
    wrapped = goede.wrap(b"\x07" * 32)
    kapotte = KmsMasterKeyProvider(SLEUTEL, client=FakeKmsClient(knoei_met_decrypt_crc=True))
    with pytest.raises(RuntimeError, match="CRC32C"):
        kapotte.unwrap(wrapped)


def test_standaard_provider_kiest_lokaal_zonder_kms_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "kms_masterkey_sleutel", None)
    assert isinstance(standaard_masterkey_provider(), LocalMasterKeyProvider)


def test_standaard_provider_kiest_kms_met_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "kms_masterkey_sleutel", SLEUTEL)
    gezien: list[str] = []

    class StubKms:
        def __init__(self, sleutel_naam: str, **_: object) -> None:
            gezien.append(sleutel_naam)

    monkeypatch.setattr(envelope, "KmsMasterKeyProvider", StubKms)
    provider = standaard_masterkey_provider()
    assert isinstance(provider, StubKms)
    assert gezien == [SLEUTEL]
