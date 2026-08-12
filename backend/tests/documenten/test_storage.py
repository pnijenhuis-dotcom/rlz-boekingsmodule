"""Contracttests documentopslag (GCP-draaiboek F1.5): élke test draait tegen beide
implementaties — lokaal bestandssysteem én de GCS-variant (tegen een fake-client die de
google-cloud-storage-API nabootst, incl. de echte NotFound-exception). Zo kan de
productie-overstap nooit stil ander gedrag introduceren dan dev."""

from __future__ import annotations

from pathlib import Path

import pytest
from google.api_core.exceptions import NotFound

from app.documenten import storage as storage_module
from app.documenten.storage import DocumentOpslag, GcsDocumentOpslag, LokaleBestandsopslag


class FakeBlob:
    def __init__(self, objecten: dict[str, bytes], naam: str) -> None:
        self._objecten = objecten
        self._naam = naam

    def upload_from_string(self, data: bytes, content_type: str | None = None) -> None:
        self._objecten[self._naam] = bytes(data)

    def download_as_bytes(self) -> bytes:
        if self._naam not in self._objecten:
            raise NotFound(f"blob {self._naam} bestaat niet")
        return self._objecten[self._naam]

    def exists(self) -> bool:
        return self._naam in self._objecten


class FakeBucket:
    def __init__(self, objecten: dict[str, bytes]) -> None:
        self._objecten = objecten

    def blob(self, naam: str) -> FakeBlob:
        return FakeBlob(self._objecten, naam)


class FakeGcsClient:
    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, bytes]] = {}

    def bucket(self, naam: str) -> FakeBucket:
        return FakeBucket(self.buckets.setdefault(naam, {}))


@pytest.fixture(params=["lokaal", "gcs"])
def opslag(request: pytest.FixtureRequest, tmp_path: Path) -> DocumentOpslag:
    if request.param == "lokaal":
        return LokaleBestandsopslag(tmp_path / "documenten")
    return GcsDocumentOpslag("test-bucket", client=FakeGcsClient())


def test_opslaan_en_lezen_roundtrip(opslag: DocumentOpslag) -> None:
    opslag.opslaan(pad="admin-1/doc-1.pdf", inhoud=b"%PDF-inhoud")
    assert opslag.bestaat(pad="admin-1/doc-1.pdf")
    assert opslag.lezen(pad="admin-1/doc-1.pdf") == b"%PDF-inhoud"


def test_overschrijven_geeft_nieuwste_inhoud(opslag: DocumentOpslag) -> None:
    opslag.opslaan(pad="admin-1/doc-1.pdf", inhoud=b"v1")
    opslag.opslaan(pad="admin-1/doc-1.pdf", inhoud=b"v2")
    assert opslag.lezen(pad="admin-1/doc-1.pdf") == b"v2"


def test_niet_bestaand_pad(opslag: DocumentOpslag) -> None:
    assert not opslag.bestaat(pad="onbekend.pdf")


def test_lezen_onbekend_pad_geeft_filenotfound(opslag: DocumentOpslag) -> None:
    # Pariteit: ook de GCS-variant vertaalt google's NotFound naar FileNotFoundError,
    # zodat aanroepende code geen google-exceptions hoeft te kennen.
    with pytest.raises(FileNotFoundError):
        opslag.lezen(pad="onbekend.pdf")


@pytest.mark.parametrize("pad", ["../buiten.pdf", "/absoluut.pdf", "a/../../b.pdf"])
def test_pad_buiten_basismap_wordt_geweigerd(opslag: DocumentOpslag, pad: str) -> None:
    with pytest.raises(ValueError, match="buiten de opslagmap"):
        opslag.opslaan(pad=pad, inhoud=b"x")


def test_gcs_isolatie_per_bucket() -> None:
    client = FakeGcsClient()
    a = GcsDocumentOpslag("bucket-a", client=client)
    b = GcsDocumentOpslag("bucket-b", client=client)
    a.opslaan(pad="doc.pdf", inhoud=b"a")
    assert not b.bestaat(pad="doc.pdf")


def test_standaard_opslag_kiest_lokaal_zonder_bucket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "document_gcs_bucket", None)
    monkeypatch.setattr(settings, "document_opslag_basismap", str(tmp_path / "docs"))
    assert isinstance(storage_module.standaard_opslag(), LokaleBestandsopslag)


def test_standaard_opslag_kiest_gcs_met_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "document_gcs_bucket", "rlz-documenten-test")
    gezien: list[str] = []

    class StubGcs:
        def __init__(self, bucket_naam: str, **_: object) -> None:
            gezien.append(bucket_naam)

    monkeypatch.setattr(storage_module, "GcsDocumentOpslag", StubGcs)
    opslag = storage_module.standaard_opslag()
    assert isinstance(opslag, StubGcs)
    assert gezien == ["rlz-documenten-test"]
