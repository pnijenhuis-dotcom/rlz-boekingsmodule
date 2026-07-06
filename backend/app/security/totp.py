from __future__ import annotations

import time

import pyotp

STEP_SECONDS = 30


def generate_secret() -> str:
    return pyotp.random_base32()


def build_otpauth_uri(secret: str, *, account_name: str, issuer: str = "RLZ Boekingsmodule") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)


def verify_code(
    secret: str, code: str, *, last_accepted_step: int | None, at: float | None = None
) -> int | None:
    """Verifieert een TOTP-code binnen één stap clock-skew (±30s) en wijst replay af: een stap
    die al eerder is geaccepteerd (of ouder) faalt altijd, ook als de code zelf geldig zou zijn.

    Retourneert de gematchte stap bij succes (voor opslag als nieuwe `last_accepted_step`),
    anders None. `at` is voor tests (deterministisch, geen echte klok/sleep nodig)."""
    now = at if at is not None else time.time()
    totp = pyotp.TOTP(secret)
    base_step = int(now // STEP_SECONDS)
    for offset in (0, -1, 1):
        step = base_step + offset
        if step < 0:
            continue
        if totp.at(step * STEP_SECONDS) == code:
            if last_accepted_step is not None and step <= last_accepted_step:
                return None
            return step
    return None
