"""Software-authenticator voor de passkey-tests: échte WebAuthn-crypto (EC P-256 + CBOR,
attestation-format "none"), geen mocks — de server-side verificatie (py_webauthn) draait
volledig. Gemodelleerd naar duo-labs' soft-webauthn-testpatroon."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(waarde: str) -> bytes:
    return base64.urlsafe_b64decode(waarde + "=" * (-len(waarde) % 4))


class SoftWebauthnApparaat:
    """Eén virtueel apparaat (één credential). `registreer()` beantwoordt creation-options,
    `onderteken()` beantwoordt request-options — beide met geldige handtekeningen."""

    def __init__(self, *, rp_id: str = "localhost", origin: str = "http://localhost:5173") -> None:
        self.rp_id = rp_id
        self.origin = origin
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(32)
        self.sign_count = 0

    def _rp_id_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest()

    def _cose_public_key(self) -> bytes:
        nummers = self.private_key.public_key().public_numbers()
        x = nummers.x.to_bytes(32, "big")
        y = nummers.y.to_bytes(32, "big")
        # COSE EC2: kty=2 (EC2), alg=-7 (ES256), crv=1 (P-256)
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: x, -3: y})

    def registreer(self, opties_json: str) -> dict:
        opties = json.loads(opties_json)
        client_data = json.dumps(
            {
                "type": "webauthn.create",
                "challenge": opties["challenge"],
                "origin": self.origin,
                "crossOrigin": False,
            }
        ).encode()
        # authData: rpIdHash(32) + flags(1: UP|UV|AT = 0x45) + signCount(4) + attestedCredData
        attested = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id
        attested += self._cose_public_key()
        auth_data = self._rp_id_hash() + bytes([0x45]) + struct.pack(">I", self.sign_count) + attested
        attestation_object = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": _b64url(self.credential_id),
            "rawId": _b64url(self.credential_id),
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": _b64url(client_data),
                "attestationObject": _b64url(attestation_object),
                "transports": ["internal"],
            },
        }

    def onderteken(self, opties_json: str) -> dict:
        opties = json.loads(opties_json)
        client_data = json.dumps(
            {
                "type": "webauthn.get",
                "challenge": opties["challenge"],
                "origin": self.origin,
                "crossOrigin": False,
            }
        ).encode()
        self.sign_count += 1
        # flags: UP|UV = 0x05 (geen attested credential data bij een assertion)
        auth_data = self._rp_id_hash() + bytes([0x05]) + struct.pack(">I", self.sign_count)
        handtekening = self.private_key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": _b64url(self.credential_id),
            "rawId": _b64url(self.credential_id),
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": _b64url(client_data),
                "authenticatorData": _b64url(auth_data),
                "signature": _b64url(handtekening),
                "userHandle": None,
            },
        }
