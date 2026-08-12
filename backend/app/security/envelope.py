from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_DEV_ENVIRONMENTS = ("dev", "local")


class MasterKeyProvider(Protocol):
    """Wrap/unwrap-interface voor het masterkey-niveau van envelope encryption. Lokale dev
    implementeert dit symmetrisch met een sleutel uit `.env`; de productie-vervanging (Cloud KMS
    wrap/unwrap-API) biedt dezelfde interface, zodat wrap_secret()/unwrap_secret() hieronder niet
    wijzigen wanneer de masterkey-laag naar KMS verhuist."""

    def wrap(self, data_key: bytes) -> bytes: ...

    def unwrap(self, wrapped: bytes) -> bytes: ...


def _resolve_master_key(env: Mapping[str, str]) -> bytes:
    """Analoog aan migraties/0001._resolve_app_role_password: geen stil fallback buiten dev."""
    key_b64 = env.get("TOTP_MASTER_KEY")
    if key_b64:
        import base64

        return base64.b64decode(key_b64)
    environment = env.get("ENVIRONMENT", "dev")
    if environment not in _DEV_ENVIRONMENTS:
        raise RuntimeError(
            f"TOTP_MASTER_KEY ontbreekt en ENVIRONMENT={environment!r} is geen dev-omgeving "
            f"({', '.join(_DEV_ENVIRONMENTS)}). Zet TOTP_MASTER_KEY (Cloud Run: via Secret "
            "Manager/KMS) vóórdat de envelope-encryptie in productie draait."
        )
    # Vaste dev-sleutel — nooit bereikt buiten dev/local (guard hierboven), dus geen geheim.
    return b"\x00" * 32


class LocalMasterKeyProvider:
    """AES-256-GCM-wrap met een lokale masterkey (dev/Cloud Run-fallback via Secret Manager als
    env var). Zie MasterKeyProvider voor de latere KMS-vervanging."""

    def __init__(self, master_key: bytes | None = None) -> None:
        self._master_key = master_key if master_key is not None else _resolve_master_key(os.environ)

    def wrap(self, data_key: bytes) -> bytes:
        aesgcm = AESGCM(self._master_key)
        nonce = os.urandom(12)
        return nonce + aesgcm.encrypt(nonce, data_key, None)

    def unwrap(self, wrapped: bytes) -> bytes:
        aesgcm = AESGCM(self._master_key)
        nonce, ciphertext = wrapped[:12], wrapped[12:]
        return aesgcm.decrypt(nonce, ciphertext, None)


def _crc32c(data: bytes) -> int:
    import google_crc32c  # transitieve dependency van de google-cloud-clients; lazy zodat
    # dev-paden zonder KMS dit nooit importeren.

    return int(google_crc32c.value(data))


class KmsMasterKeyProvider:
    """Cloud KMS-implementatie van MasterKeyProvider (GCP-draaiboek F1.3, beslispunt 8:
    KMS meteen — koppelcontract §2b-norm). De masterkey verlaat KMS nooit: wrap = KMS-Encrypt
    over de 32-byte data-key, unwrap = KMS-Decrypt. `sleutel_naam` is de volledige
    CryptoKey-resourcenaam (projects/.../locations/europe-west4/keyRings/.../cryptoKeys/...).
    Authenticatie via Application Default Credentials (Cloud Run: de service-SA).
    CRC32C-integriteitschecks conform de KMS-documentatie — verdediging-in-de-diepte bovenop
    TLS; een mislukte check is een harde fout, nooit stil doorgaan met een corrupte key.
    `client` is injecteerbaar voor tests (fake-KMS draait de unit-tests, geen netwerk)."""

    def __init__(self, sleutel_naam: str, *, client: Any | None = None) -> None:
        if client is None:  # pragma: no cover — echte client alleen buiten tests
            from google.cloud import kms

            client = kms.KeyManagementServiceClient()
        self._client = client
        self._sleutel_naam = sleutel_naam

    def wrap(self, data_key: bytes) -> bytes:
        respons = self._client.encrypt(
            request={
                "name": self._sleutel_naam,
                "plaintext": data_key,
                "plaintext_crc32c": _crc32c(data_key),
            }
        )
        if not respons.verified_plaintext_crc32c or _crc32c(respons.ciphertext) != respons.ciphertext_crc32c:
            raise RuntimeError("KMS-encrypt-integriteitscheck mislukt (CRC32C) — wrap geweigerd.")
        return bytes(respons.ciphertext)

    def unwrap(self, wrapped: bytes) -> bytes:
        respons = self._client.decrypt(
            request={
                "name": self._sleutel_naam,
                "ciphertext": wrapped,
                "ciphertext_crc32c": _crc32c(wrapped),
            }
        )
        if _crc32c(respons.plaintext) != respons.plaintext_crc32c:
            raise RuntimeError("KMS-decrypt-integriteitscheck mislukt (CRC32C) — unwrap geweigerd.")
        return bytes(respons.plaintext)


def standaard_masterkey_provider() -> MasterKeyProvider:
    """Config-gedreven keuze (draaiboek F1.3): `KMS_MASTERKEY_SLEUTEL` gezet = Cloud KMS,
    anders de lokale provider (dev-default; buiten dev eist die zelf TOTP_MASTER_KEY — zie
    _resolve_master_key). Op sleutelnaam en niet op ENVIRONMENT, zodat de KMS-route ook vóór
    de cutover tegen een test-keyring te draaien is."""
    from app.config import settings

    if settings.kms_masterkey_sleutel:
        return KmsMasterKeyProvider(settings.kms_masterkey_sleutel)
    return LocalMasterKeyProvider()


def wrap_secret(plaintext: bytes, *, provider: MasterKeyProvider | None = None) -> tuple[bytes, bytes]:
    """Envelope encryption: verse data-key per secret; de masterkey wrapt uitsluitend de
    data-key, nooit de data zelf direct. Retourneert (ciphertext, wrapped_data_key)."""
    provider = provider or standaard_masterkey_provider()
    data_key = os.urandom(32)
    aesgcm = AESGCM(data_key)
    nonce = os.urandom(12)
    ciphertext = nonce + aesgcm.encrypt(nonce, plaintext, None)
    wrapped_data_key = provider.wrap(data_key)
    return ciphertext, wrapped_data_key


def unwrap_secret(ciphertext: bytes, wrapped_data_key: bytes, *, provider: MasterKeyProvider | None = None) -> bytes:
    provider = provider or standaard_masterkey_provider()
    data_key = provider.unwrap(wrapped_data_key)
    aesgcm = AESGCM(data_key)
    nonce, actual_ciphertext = ciphertext[:12], ciphertext[12:]
    return aesgcm.decrypt(nonce, actual_ciphertext, None)
