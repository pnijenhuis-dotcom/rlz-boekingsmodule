#!/usr/bin/env python3
"""Genereer een VAPID-sleutelpaar (Web Push, RFC 8292) voor de accordeur-notificaties.

Draaien met de backend-venv (py-vapid/cryptography komen mee met pywebpush):
    backend/.venv/bin/python scripts/genereer_vapid_sleutels.py

Output: twee base64url-strings.
- PUSH_VAPID_PRIVATE_KEY -> Secret Manager-slot PUSH_VAPID_PRIVATE_KEY (waarde via stdin
  aanleveren met `gcloud secrets versions add ... --data-file=-`, nooit als argument — zelfde
  regel als INTAKE_IMAP_WACHTWOORD, GCP_UITROL §F3.4). Lokaal: backend/.env.
- PUSH_VAPID_PUBLIC_KEY -> gewone env-var (geen geheim; gaat als applicationServerKey naar de
  browser).

Eénmalig genereren en daarna stabiel houden: een nieuwe private key maakt álle bestaande
push-subscripties ongeldig (browsers weigeren dan de VAPID-handtekening) — roteren = bewuste
actie waarna accordeurs opnieuw moeten subscriben."""

from __future__ import annotations

import base64
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def main() -> None:
    sleutel = ec.generate_private_key(ec.SECP256R1())
    prive = sleutel.private_numbers().private_value.to_bytes(32, "big")
    publiek = sleutel.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    if "--kaal" in sys.argv:
        # Machine-leesbaar (scripts/gcp/notificaties_afronden.sh): regel 1 = private,
        # regel 2 = public — niets anders op stdout, zodat piping veilig is.
        print(_b64url(prive))
        print(_b64url(publiek))
        return
    print("PUSH_VAPID_PRIVATE_KEY (geheim — Secret Manager/.env, nooit in chat/logs):")
    print(f"  {_b64url(prive)}")
    print("PUSH_VAPID_PUBLIC_KEY (geen geheim — env-var, applicationServerKey):")
    print(f"  {_b64url(publiek)}")


if __name__ == "__main__":
    main()
