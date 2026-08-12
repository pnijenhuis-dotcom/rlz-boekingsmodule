from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class DocumentOpslag(ABC):
    """Interface voor documentopslag. `pad` is een opaque sleutel voor de implementatie (geen
    filesystem-aanname buiten LokaleBestandsopslag) — een Cloud Storage-implementatie (productie,
    7 jaar bewaarplicht met retentie) volgt dezelfde interface zodat aanroepende code niet
    verandert bij de overstap."""

    @abstractmethod
    def opslaan(self, *, pad: str, inhoud: bytes) -> None: ...

    @abstractmethod
    def lezen(self, *, pad: str) -> bytes: ...

    @abstractmethod
    def bestaat(self, *, pad: str) -> bool: ...


class LokaleBestandsopslag(DocumentOpslag):
    """Dev-implementatie: bestanden op de lokale schijf onder één basismap."""

    def __init__(self, basismap: Path) -> None:
        self._basismap = basismap.resolve()
        self._basismap.mkdir(parents=True, exist_ok=True)

    def _volledig_pad(self, pad: str) -> Path:
        volledig = (self._basismap / pad).resolve()
        if volledig != self._basismap and self._basismap not in volledig.parents:
            raise ValueError(f"Pad buiten de opslagmap: {pad!r}")
        return volledig

    def opslaan(self, *, pad: str, inhoud: bytes) -> None:
        volledig = self._volledig_pad(pad)
        volledig.parent.mkdir(parents=True, exist_ok=True)
        volledig.write_bytes(inhoud)

    def lezen(self, *, pad: str) -> bytes:
        return self._volledig_pad(pad).read_bytes()

    def bestaat(self, *, pad: str) -> bool:
        return self._volledig_pad(pad).exists()


def _geldige_sleutel(pad: str) -> str:
    """Zelfde vangrail als LokaleBestandsopslag._volledig_pad, maar dan voor object-sleutels:
    een absolute of `..`-houdende sleutel is altijd een programmeerfout — in GCS is er geen
    filesystem om uit te breken, maar dezelfde aanroep mag lokaal en in de cloud nooit
    verschillend gedrag hebben (contracttest dekt beide implementaties)."""
    delen = pad.split("/")
    if pad.startswith("/") or ".." in delen:
        raise ValueError(f"Pad buiten de opslagmap: {pad!r}")
    return pad


class GcsDocumentOpslag(DocumentOpslag):
    """Cloud Storage-implementatie (GCP-draaiboek F1.5): zelfde interface, object-sleutel =
    `pad`. De bucket draagt het 7-jaars-retentiebeleid (F1.4) — NB onder retentie kan een
    object niet overschreven worden; sleutels zijn in de praktijk uniek per document
    (uuid-paden), dus overschrijven komt alleen in tests/dev voor. Authenticatie via
    Application Default Credentials (Cloud Run: de service-account van de service);
    `client` is injecteerbaar voor tests (fake-client draait de contracttests)."""

    def __init__(self, bucket_naam: str, *, client: Any | None = None) -> None:
        if client is None:  # pragma: no cover — echte client alleen buiten tests
            from google.cloud import storage as gcs_storage

            client = gcs_storage.Client()
        self._bucket = client.bucket(bucket_naam)

    def opslaan(self, *, pad: str, inhoud: bytes) -> None:
        blob = self._bucket.blob(_geldige_sleutel(pad))
        blob.upload_from_string(inhoud, content_type="application/octet-stream")

    def lezen(self, *, pad: str) -> bytes:
        from google.api_core.exceptions import NotFound

        blob = self._bucket.blob(_geldige_sleutel(pad))
        try:
            return blob.download_as_bytes()
        except NotFound as exc:
            # Pariteit met LokaleBestandsopslag (Path.read_bytes) — aanroepende code hoeft
            # geen google-exceptions te kennen.
            raise FileNotFoundError(pad) from exc

    def bestaat(self, *, pad: str) -> bool:
        return self._bucket.blob(_geldige_sleutel(pad)).exists()


def standaard_opslag() -> DocumentOpslag:
    """Config-gedreven keuze (draaiboek F1.5): `DOCUMENT_GCS_BUCKET` gezet = Cloud Storage,
    anders het lokale bestandssysteem (dev-default). Bewust op bucketnaam en niet op
    ENVIRONMENT — zo is de GCS-route ook vóór de productie-cutover tegen een testbucket te
    draaien."""
    from app.config import settings

    if settings.document_gcs_bucket:
        return GcsDocumentOpslag(settings.document_gcs_bucket)
    return LokaleBestandsopslag(Path(settings.document_opslag_basismap))
