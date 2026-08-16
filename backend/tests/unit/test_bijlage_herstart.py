"""Unit-tests app/rlz/bijlage.py::zorg_voor_bijlage — de herstart-veilige bijlage-upload
(STAP-0 "Uploads bij een herstart-boekcyclus" 2026-08-16, aanleiding kliktest-2-bug
TEST-ONB-KLIKTEST-01): idempotentie via de Uploads-leesroute + deterministische
cyclus-GUID's bij een verbruikt basis-GUID; alles daarbuiten faalt gewoon zichtbaar."""

from __future__ import annotations

import uuid

import pytest

from app.rlz.bijlage import MAX_UPLOAD_CYCLI, cyclus_upload_id, zorg_voor_bijlage
from app.rlz.client import RlzApiError

BASIS = uuid.uuid5(uuid.NAMESPACE_URL, "test-basis-upload")
DOC = uuid.uuid5(uuid.NAMESPACE_URL, "test-document")


class NepUploadClient:
    """Minimaal duck-typed clientje: `lijst` = wat GET .../Uploads teruggeeft (of een
    RlzApiError), `weiger` = statuscode per upload-GUID dat de PUT moet weigeren."""

    def __init__(self, *, lijst: list[dict] | RlzApiError | None = None, weiger: dict[str, int] | None = None):
        self.lijst = lijst or []
        self.weiger = weiger or {}
        self.geupload: list[str] = []

    def get(self, path: str, *, params=None):
        if isinstance(self.lijst, RlzApiError):
            raise self.lijst
        return {"value": self.lijst}

    def upload_bijlage(self, entity_path, entity_id, *, upload_id, filename, content_base64):
        code = self.weiger.get(str(upload_id))
        if code is not None:
            raise RlzApiError(code, "PUT", f"{entity_path}/{entity_id}/Uploads/{upload_id}", "geweigerd")
        self.geupload.append(str(upload_id))


def _zorg(client: NepUploadClient) -> bool:
    return zorg_voor_bijlage(
        client, "SalesInvoices", DOC, upload_id=BASIS, filename="f.pdf", content_base64="YQ=="
    )


class TestCyclusUploadId:
    def test_cyclus_0_is_het_basis_guid_zelf(self) -> None:
        assert cyclus_upload_id(BASIS, 0) == BASIS

    def test_cycli_zijn_deterministisch_en_onderling_verschillend(self) -> None:
        reeks = [cyclus_upload_id(BASIS, n) for n in range(4)]
        assert reeks == [cyclus_upload_id(BASIS, n) for n in range(4)]
        assert len(set(reeks)) == 4


class TestZorgVoorBijlage:
    def test_verse_upload_gebruikt_het_basis_guid(self) -> None:
        client = NepUploadClient()
        assert _zorg(client) is True
        assert client.geupload == [str(BASIS)]

    def test_bijlage_al_aanwezig_slaat_de_upload_over(self) -> None:
        # het herstart-op-storno-concept-pad (spiegel-kant kliktest 2) én de crash-retry
        client = NepUploadClient(lijst=[{"id": str(BASIS), "FileName": "f.pdf"}])
        assert _zorg(client) is False
        assert client.geupload == []

    def test_verbruikt_basis_guid_404_schuift_door_naar_cyclus_1(self) -> None:
        # het productie-pad: document in de RLZ-UI verwijderd, GUID blijft onbruikbaar
        client = NepUploadClient(weiger={str(BASIS): 404})
        assert _zorg(client) is True
        assert client.geupload == [str(cyclus_upload_id(BASIS, 1))]

    def test_bestaand_guid_400_schuift_ook_door(self) -> None:
        client = NepUploadClient(weiger={str(BASIS): 400})
        assert _zorg(client) is True
        assert client.geupload == [str(cyclus_upload_id(BASIS, 1))]

    def test_andere_fout_dan_400_of_404_faalt_direct(self) -> None:
        client = NepUploadClient(weiger={str(BASIS): 500})
        with pytest.raises(RlzApiError) as excinfo:
            _zorg(client)
        assert excinfo.value.status_code == 500
        assert client.geupload == []

    def test_onleesbare_uploads_lijst_valt_open_naar_gewoon_uploaden(self) -> None:
        client = NepUploadClient(lijst=RlzApiError(500, "GET", "SalesInvoices/x/Uploads", "kapot"))
        assert _zorg(client) is True
        assert client.geupload == [str(BASIS)]

    def test_alle_cycli_verbruikt_faalt_zichtbaar_met_de_laatste_fout(self) -> None:
        weiger = {str(cyclus_upload_id(BASIS, n)): 404 for n in range(MAX_UPLOAD_CYCLI)}
        client = NepUploadClient(weiger=weiger)
        with pytest.raises(RlzApiError) as excinfo:
            _zorg(client)
        assert excinfo.value.status_code == 404
        assert client.geupload == []
