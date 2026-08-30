"""Android-signing-certificaten → assetlinks + WebAuthn-origins (Play App Signing, 30-08).

Eén bron van waarheid: de lijst SHA-256-vingerafdrukken in `settings.android_cert_sha256_vingerafdrukken`
(deploy.yml: `ANDROID_CERT_SHA256_VINGERAFDRUKKEN`). Daaruit leidt CODE — nooit een mens met de hand —
twee dingen af die exact bij elkaar moeten passen, anders weigert Android de passkey-prompt in de app:

- `/.well-known/assetlinks.json` (`sha256_cert_fingerprints`, hex mét dubbele punten, hoofdletters);
- de WebAuthn-origin per certificaat: `android:apk-key-hash:<base64url(sha256-bytes) zonder '='>` —
  Credential Manager stuurt die origin in de clientDataJSON i.p.v. een https-origin, dus hij moet in
  py_webauthn's `expected_origin` staan (`toegestane_webauthn_origins`).

Er zijn ALTIJD twee certificaten zolang er ook lokaal (bundletool/apk uit de upload-keystore)
geïnstalleerd wordt: Google's app-signing-key (élke Play-install) én onze upload-key. Beide worden
gelijk behandeld; de volgorde in de setting is de volgorde in de uitvoer.

Fail-loud: een vingerafdruk die geen 32 bytes hex is, wordt geweigerd bij het laden van de settings
(config.py-validator) — een typefout mag nooit als "werkt niet, weet niet waarom" op een toestel landen.

CLI (zelfde functies, voor het statische apex-bestand en ter controle van deploy.yml):
    python -m app.auth.android_signing "<SHA256-app-signing>" "<SHA256-upload>"
    python -m app.auth.android_signing --schrijf ../native/apex-well-known/assetlinks.json "<…>" "<…>"
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any

# NB géén module-level `from app.config import settings`: config.py gebruikt
# `normaliseer_vingerafdruk` in zijn settings-validator (fail-loud bij het laden) — de
# settings-afhankelijke functies hieronder importeren daarom lazy.

ORIGIN_PREFIX = "android:apk-key-hash:"
ASSETLINKS_RELATIES = [
    "delegate_permission/common.handle_all_urls",
    "delegate_permission/common.get_login_creds",
]

_HEX_PAAR = re.compile(r"^[0-9A-F]{2}$")


def normaliseer_vingerafdruk(waarde: str) -> str:
    """Hoofdletters, dubbele punten, exact 32 bytes — de vorm die Play Console en `keytool` printen.

    Accepteert ook de vorm zonder dubbele punten (zoals `openssl dgst` die geeft) en kleine letters;
    alles anders is een ValueError met de aangeboden waarde erin (geen geheim — certificaat-hash).
    """
    kaal = waarde.strip().upper().replace(":", "")
    if len(kaal) != 64 or not all(_HEX_PAAR.match(kaal[i : i + 2]) for i in range(0, 64, 2)):
        raise ValueError(
            f"Ongeldige SHA-256-certificaatvingerafdruk {waarde!r}: verwacht 32 bytes hex "
            "(64 hex-tekens, optioneel met dubbele punten)"
        )
    return ":".join(kaal[i : i + 2] for i in range(0, 64, 2))


def apk_key_hash_origin(vingerafdruk: str) -> str:
    """`android:apk-key-hash:<base64url>` — Chromium/Credential Manager-vorm (RFC 4648 §5, zonder '=')."""
    raw = bytes.fromhex(normaliseer_vingerafdruk(vingerafdruk).replace(":", ""))
    return ORIGIN_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def android_webauthn_origins(vingerafdrukken: list[str] | tuple[str, ...]) -> list[str]:
    """Eén origin per certificaat, in de aangeboden volgorde, zonder dubbelen."""
    uit: list[str] = []
    for v in vingerafdrukken:
        origin = apk_key_hash_origin(v)
        if origin not in uit:
            uit.append(origin)
    return uit


def toegestane_webauthn_origins() -> list[str]:
    """De volledige `expected_origin`-lijst voor py_webauthn: geconfigureerde https-origins +
    de uit de certificaten afgeleide Android-origins (afleiding in code, deploy.yml hoeft ze niet
    te dragen). Een handmatig tóch geconfigureerde apk-key-hash-origin blijft gewoon staan (dedupe)."""
    from app.config import settings

    uit = list(settings.webauthn_origins)
    for origin in android_webauthn_origins(settings.android_cert_sha256_vingerafdrukken):
        if origin not in uit:
            uit.append(origin)
    return uit


def assetlinks_inhoud(package_name: str, vingerafdrukken: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    """Exact de Digital Asset Links-statement die Android bij de apex ophaalt (één target, alle certs)."""
    return [
        {
            "relation": list(ASSETLINKS_RELATIES),
            "target": {
                "namespace": "android_app",
                "package_name": package_name,
                "sha256_cert_fingerprints": [normaliseer_vingerafdruk(v) for v in vingerafdrukken],
            },
        }
    ]


def assetlinks_json(package_name: str, vingerafdrukken: list[str] | tuple[str, ...]) -> str:
    """Canonieke serialisatie (2 spaties, newline aan het eind) — zo staat het statische bestand in
    `native/apex-well-known/` en zo vergelijkt de drift-test het met deploy.yml."""
    return json.dumps(assetlinks_inhoud(package_name, vingerafdrukken), indent=2, ensure_ascii=False) + "\n"


def _main(argv: list[str] | None = None) -> int:
    from app.config import settings

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("vingerafdrukken", nargs="+", help="SHA-256-certificaatvingerafdruk(ken), Play Console-vorm")
    parser.add_argument("--package", default=settings.native_app_bundle_id)
    parser.add_argument("--schrijf", type=Path, help="schrijf assetlinks.json naar dit pad (statisch apex-bestand)")
    args = parser.parse_args(argv)

    vingerafdrukken = [normaliseer_vingerafdruk(v) for v in args.vingerafdrukken]
    print("ANDROID_CERT_SHA256_VINGERAFDRUKKEN (deploy.yml, JSON-lijst):")
    print("  " + json.dumps(vingerafdrukken))
    print("WebAuthn-origins (door de backend zélf afgeleid — niet in WEBAUTHN_ORIGINS zetten):")
    for v, o in zip(vingerafdrukken, android_webauthn_origins(vingerafdrukken), strict=True):
        print(f"  {o}   ← {v}")
    inhoud = assetlinks_json(args.package, vingerafdrukken)
    if args.schrijf:
        args.schrijf.write_text(inhoud, encoding="utf-8")
        print(f"assetlinks.json geschreven: {args.schrijf}")
    else:
        print("assetlinks.json:")
        print(inhoud, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
