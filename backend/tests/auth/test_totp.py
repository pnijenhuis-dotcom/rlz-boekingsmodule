from __future__ import annotations

import pyotp

from app.security import totp
from app.security.envelope import unwrap_secret, wrap_secret

AT = 1_700_000_000.0  # vast tijdstip — deterministisch, geen echte klok/sleep nodig.


def test_juiste_code_slaagt() -> None:
    secret = totp.generate_secret()
    code = pyotp.TOTP(secret).at(AT)
    stap = totp.verify_code(secret, code, last_accepted_step=None, at=AT)
    assert stap is not None


def test_verkeerde_code_faalt() -> None:
    secret = totp.generate_secret()
    juiste_code = pyotp.TOTP(secret).at(AT)
    verkeerde_code = f"{(int(juiste_code) + 1) % 1_000_000:06d}"
    assert totp.verify_code(secret, verkeerde_code, last_accepted_step=None, at=AT) is None


def test_replay_van_dezelfde_stap_wordt_geweigerd() -> None:
    secret = totp.generate_secret()
    code = pyotp.TOTP(secret).at(AT)

    eerste = totp.verify_code(secret, code, last_accepted_step=None, at=AT)
    assert eerste is not None

    tweede = totp.verify_code(secret, code, last_accepted_step=eerste, at=AT)
    assert tweede is None


def test_replay_binnen_het_clock_skew_venster_wordt_ook_geweigerd() -> None:
    """Niet alleen exacte herhaling: een code die (door skew) matcht met een stap <= de laatst
    geaccepteerde stap moet ook geweigerd worden, ook al valt de aanroep op een net iets later
    moment binnen het valid_window."""
    secret = totp.generate_secret()
    stap_nu = int(AT // totp.STEP_SECONDS)
    code_vorige_stap = pyotp.TOTP(secret).at((stap_nu - 1) * totp.STEP_SECONDS)

    # De vorige stap is al geaccepteerd...
    laatste_stap = stap_nu - 1
    # ...dus dezelfde code (voor die stap) nu opnieuw aanbieden faalt, ook al ligt "nu" net na skew.
    resultaat = totp.verify_code(secret, code_vorige_stap, last_accepted_step=laatste_stap, at=AT)
    assert resultaat is None


def test_nieuwe_stap_na_replay_geweigerde_stap_werkt_wel() -> None:
    secret = totp.generate_secret()
    stap_nu = int(AT // totp.STEP_SECONDS)
    code_nu = pyotp.TOTP(secret).at(stap_nu * totp.STEP_SECONDS)

    resultaat = totp.verify_code(secret, code_nu, last_accepted_step=stap_nu - 1, at=AT)
    assert resultaat == stap_nu


def test_envelope_encryption_roundtrip() -> None:
    plaintext = b"JBSWY3DPEHPK3PXP"  # voorbeeld-secret, geen echt geheim
    ciphertext, wrapped_key = wrap_secret(plaintext)
    assert unwrap_secret(ciphertext, wrapped_key) == plaintext
    assert ciphertext != plaintext
    # Twee keer dezelfde plaintext wrappen geeft andere ciphertext/keys (verse data-key + nonce).
    ciphertext2, wrapped_key2 = wrap_secret(plaintext)
    assert (ciphertext2, wrapped_key2) != (ciphertext, wrapped_key)
