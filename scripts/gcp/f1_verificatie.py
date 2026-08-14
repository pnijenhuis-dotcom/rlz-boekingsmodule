"""F1-verificatie (docs/GCP_UITROL.md §F1, definition of done):

1. een testdocument uploaden én teruglezen via GcsDocumentOpslag tegen de échte bucket;
2. een KMS-wrap/unwrap-rondje met KmsMasterKeyProvider tegen de échte key, plus het
   volledige envelope-pad (wrap_secret/unwrap_secret) zoals de credential-store het gebruikt.

Bewust GEEN herbouw: dit script gebruikt uitsluitend de bestaande productiecode
(app/documenten/storage.py, app/security/envelope.py) — precies wat Cloud Run straks draait.

Draaien (vanuit de repo-root, met de backend-venv):

    backend/.venv/bin/python scripts/gcp/f1_verificatie.py

Authenticatie via Application Default Credentials; eenmalig instellen met
`gcloud auth application-default login` (het uitvoerende account heeft de
KMS-encrypt/decrypt-binding uit f1_data.sh stap 3.2 nodig, plus lees/schrijf op
de bucket — het org-owner-account voldoet).

NB het testobject blijft staan: de bucket-retentie (7 jaar, bewaarplicht)
verbiedt verwijderen — daarom een uniek pad per run en een minimale inhoud.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

PROJECT_ID = "rlz-boekhouding"
REGION = "europe-west4"
BUCKET = os.environ.get("DOCUMENT_GCS_BUCKET", f"{PROJECT_ID}-documenten")
KMS_SLEUTEL = os.environ.get(
    "KMS_MASTERKEY_SLEUTEL",
    f"projects/{PROJECT_ID}/locations/{REGION}/keyRings/rlz/cryptoKeys/masterkey",
)


def main() -> int:
    from app.documenten.storage import GcsDocumentOpslag
    from app.security.envelope import KmsMasterKeyProvider, unwrap_secret, wrap_secret

    fouten: list[str] = []

    # --- 1. GCS: upload + teruglezen via de bestaande implementatie -------------
    print(f"== GCS-verificatie tegen gs://{BUCKET} ==")
    opslag = GcsDocumentOpslag(BUCKET)
    pad = f"verificatie/f1-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.txt"
    inhoud = f"F1-verificatie {datetime.now(UTC).isoformat()}".encode()
    opslag.opslaan(pad=pad, inhoud=inhoud)
    terug = opslag.lezen(pad=pad)
    if terug == inhoud and opslag.bestaat(pad=pad):
        print(f"   OK: {pad} geüpload en byte-identiek teruggelezen ({len(inhoud)} bytes).")
        print("   NB: object blijft staan — retentie 7 jaar verbiedt verwijderen (bedoeld).")
    else:
        fouten.append(f"GCS: teruggelezen inhoud wijkt af voor {pad!r}")

    # --- 2. KMS: wrap/unwrap-rondje + volledig envelope-pad ---------------------
    print(f"== KMS-verificatie tegen {KMS_SLEUTEL} ==")
    provider = KmsMasterKeyProvider(KMS_SLEUTEL)
    data_key = os.urandom(32)
    if provider.unwrap(provider.wrap(data_key)) == data_key:
        print("   OK: KMS-wrap/unwrap-rondje (32-byte data-key) byte-identiek.")
    else:
        fouten.append("KMS: unwrap(wrap(x)) != x")

    geheim = b"f1-verificatie-envelope-proef"
    ciphertext, wrapped = wrap_secret(geheim, provider=provider)
    if unwrap_secret(ciphertext, wrapped, provider=provider) == geheim:
        print("   OK: volledig envelope-pad (wrap_secret/unwrap_secret) via KMS.")
    else:
        fouten.append("KMS: envelope-pad levert niet het oorspronkelijke geheim terug")

    if fouten:
        print("\nMISLUKT:\n- " + "\n- ".join(fouten))
        return 1
    print("\nF1-verificatie GESLAAGD (GCS + KMS).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
