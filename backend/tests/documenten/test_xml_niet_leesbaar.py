"""FV-01 (feedbackrun A 25-09): een XML die geen (volledige) UBL is gaat naar `handmatig_afmaken` mét de reden als
`ubl_parse_fout` in de tijdlijn (was: te_controleren zonder voorstel, ruwe XML in het scherm); de route
`GET …/documenten/{id}/ubl-samenvatting` levert de leesbare kaart (200 leesbaar=false + dezelfde reden bij een
onleesbare XML; 422 voor een PDF); de lees-only CLI `xml-documenten-rapport` wordt in élke vorm uit het meetrecept
letterlijk aangeroepen (les 19-09 poging 2)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import cli
from app.documenten import service
from app.documenten.models import DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from tests.intake.conftest import bouw_ubl

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parents[1] / "keten" / "fixtures"
RLZ_EXPORT = (FIXTURES / "a_universal_nederland_rlz2080143037" / "factuur.xml").read_bytes()
KAPOT = b'<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"><cbc:ID>'


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _laatste_detail(admin_engine: Engine, document_id: uuid.UUID, *, sleutel: str = "ubl_parse_fout") -> dict:
    """Detail van de laatste extractie-EINDovergang (de rij mét `sleutel`; latere notitie-rijen — prefill-autosave,
    duplicaatsignaal — dragen 'm niet)."""
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                "AND naar_status IN ('te_controleren', 'handmatig_afmaken') AND detail ? :sleutel "
                "ORDER BY tijdstip DESC LIMIT 1"
            ),
            {"id": document_id, "sleutel": sleutel},
        ).all()
    if rijen:
        return rijen[0][0]
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                "AND naar_status IN ('te_controleren', 'handmatig_afmaken') ORDER BY tijdstip DESC LIMIT 1"
            ),
            {"id": document_id},
        ).scalar_one()


def _upload(administratie_id: uuid.UUID, actor: uuid.UUID, opslag: LokaleBestandsopslag, naam: str, inhoud: bytes):
    return service.upload_document(
        administratie_id=administratie_id, bestandsnaam=naam, inhoud=inhoud, actor_id=actor, opslag=opslag
    )


class TestStatusEnReden:
    def test_kapotte_xml_wordt_handmatig_afmaken_met_reden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        r = _upload(administratie_id, gescoopte_gebruiker, opslag, "kapot.xml", KAPOT)
        assert r.status == DocumentStatus.HANDMATIG_AFMAKEN
        detail = _laatste_detail(admin_engine, r.document_id)
        assert detail["ubl_parse_fout"].startswith("Geen geldige XML")
        assert "veldvoorstel" not in detail

    def test_gzip_en_vreemd_root_dragen_leesbare_reden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        import gzip

        r1 = _upload(administratie_id, gescoopte_gebruiker, opslag, "export.xml", gzip.compress(RLZ_EXPORT))
        assert r1.status == DocumentStatus.HANDMATIG_AFMAKEN
        assert "gecomprimeerd" in _laatste_detail(admin_engine, r1.document_id)["ubl_parse_fout"]
        order = b'<?xml version="1.0"?><Order><cbc:ID xmlns:cbc="urn:x">1</cbc:ID></Order>'
        r2 = _upload(administratie_id, gescoopte_gebruiker, opslag, "order.xml", order)
        assert r2.status == DocumentStatus.HANDMATIG_AFMAKEN
        assert "root-element <Order>" in _laatste_detail(admin_engine, r2.document_id)["ubl_parse_fout"]

    def test_ubl_zonder_regels_handmatig_afmaken_met_bewaard_kopvoorstel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        r = _upload(administratie_id, gescoopte_gebruiker, opslag, "leeg.xml", bouw_ubl(regels=0))
        assert r.status == DocumentStatus.HANDMATIG_AFMAKEN
        detail = _laatste_detail(admin_engine, r.document_id)
        assert "factuurregels" in detail["ubl_parse_fout"]
        assert detail["veldvoorstel"]["factuurnummer"] == "F-2026-001", "het kop-voorstel verdwijnt niet stil"

    def test_geldige_rlz_export_blijft_te_controleren(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        r = _upload(administratie_id, gescoopte_gebruiker, opslag, "RLZ-2080143037.xml", RLZ_EXPORT)
        assert r.status == DocumentStatus.TE_CONTROLEREN
        detail = _laatste_detail(admin_engine, r.document_id, sleutel="veldvoorstel")
        assert "ubl_parse_fout" not in detail
        assert detail["veldvoorstel"]["project_tekst"] == "26084 - Opdrachtgever A (W03611)"


class TestSamenvattingRoute:
    def _url(self, administratie_id: uuid.UUID, document_id: uuid.UUID) -> str:
        return f"/administraties/{administratie_id}/documenten/{document_id}/ubl-samenvatting"

    def test_leesbare_kaart_voor_rlz_export(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        r = _upload(administratie_id, gescoopte_gebruiker, opslag, "RLZ-2080143037.xml", RLZ_EXPORT)
        resp = client.get(self._url(administratie_id, r.document_id), headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["leesbaar"] is True and body["reden"] is None
        assert body["leverancier"] == "Universal Nederland B.V." and body["afnemer"] == "Universal Steigerbouw B.V."
        assert body["factuurnummer"] == "RLZ-2080143037" and body["totaal_incl"] == "212.21"
        assert body["regels"][0]["netto_bedrag"] == "175.38" and body["regels"][0]["btw_bedrag"] == "36.83"
        assert body["project_tekst"] == "26084 - Opdrachtgever A (W03611)"

    def test_niet_leesbaar_is_200_met_dezelfde_reden_als_de_tijdlijn(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        r = _upload(administratie_id, gescoopte_gebruiker, opslag, "kapot.xml", KAPOT)
        resp = client.get(self._url(administratie_id, r.document_id), headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200
        body = resp.json()
        assert body["leesbaar"] is False
        assert body["reden"] == _laatste_detail(admin_engine, r.document_id)["ubl_parse_fout"]

    def test_pdf_is_422_en_buiten_scope_403(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        r = _upload(administratie_id, gescoopte_gebruiker, opslag, "factuur.pdf", b"%PDF-1.4 x")
        resp = client.get(self._url(administratie_id, r.document_id), headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 422
        resp = client.get(self._url(uuid.uuid4(), r.document_id), headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 403
        assert client.get(self._url(administratie_id, r.document_id)).status_code in (401, 403)


class TestXmlDocumentenRapportCli:
    @pytest.fixture
    def stand(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag):
        """Drie xml-documenten: één geldige RLZ-export zonder beeld, één kapotte, één PDF (telt niet)."""
        a = _upload(administratie_id, gescoopte_gebruiker, opslag, "RLZ-2080143037.xml", RLZ_EXPORT)
        b = _upload(administratie_id, gescoopte_gebruiker, opslag, "kapot.xml", KAPOT)
        _upload(administratie_id, gescoopte_gebruiker, opslag, "factuur.pdf", b"%PDF-1.4 x")
        return a, b, opslag

    def test_alle_vormen_uit_het_meetrecept(
        self, stand, administratie_id: uuid.UUID, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # De conftest zet `settings.document_opslag_basismap` op dezelfde tmp-map als de `opslag`-fixture, dus de
        # CLI (standaard_opslag) leest exact de geüploade bestanden — zoals in productie (GCS).
        a, b, _ = stand
        # Vorm 1 — kantoorbreed (nameting-workflow): --alles --detail.
        assert cli.main(["xml-documenten-rapport", "--alles", "--detail"]) == 0
        uit = capsys.readouterr().out
        assert "xml-documenten-rapport (lees-only)" in uit
        assert "2 xml-documenten · 2 zonder beeld · 1 niet leesbaar · 0 mét PDF-tweeling · fouten 0" in uit
        assert str(a.document_id)[:8] in uit and str(b.document_id)[:8] in uit
        assert "intake-herlezen --alleen-ubl" in uit
        # Vorm 2 — één administratie op uuid, JSON.
        assert cli.main(["xml-documenten-rapport", "--administratie", str(administratie_id), "--json-uit"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["administraties"] == 1 and data["fouten"] == []
        per = {r["bestandsnaam"]: r for r in data["rijen"]}
        assert per["kapot.xml"]["status"] == "handmatig_afmaken" and per["kapot.xml"]["niet_leesbaar_reden"]
        assert per["RLZ-2080143037.xml"]["beeld"] == "geen" and per["RLZ-2080143037.xml"]["niet_leesbaar_reden"] is None
        assert "factuur.pdf" not in per
        # Vorm 3 — zonder argumenten = alles.
        assert cli.main(["xml-documenten-rapport"]) == 0
        assert "TOTAAL 2 xml-documenten" in capsys.readouterr().out
        # Onbekende administratie = exit 2, zichtbaar.
        assert cli.main(["xml-documenten-rapport", "--administratie", "bestaat-niet-xyz"]) == 2

    def test_kapotte_administratie_stopt_de_rest_niet(
        self, stand, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.documenten import xml_rapport

        echte = xml_rapport.rijen_voor

        def kapot(aid, naam, **kw):  # noqa: ANN001
            if aid != administratie_id:
                raise RuntimeError("kapot")
            return echte(aid, naam, opslag=stand[2])

        monkeypatch.setattr(xml_rapport, "rijen_voor", kapot)
        monkeypatch.setattr(
            xml_rapport, "_administraties", lambda term: [(administratie_id, "Scope"), (uuid.uuid4(), "Kapot BV")]
        )
        meting = xml_rapport.meet(administratie=None)
        assert meting is not None and len(meting.rijen) == 2
        assert meting.fouten == ["Kapot BV: RuntimeError: kapot"]
        assert meting.totaal_regel().endswith("fouten 1")
