"""Blok B 02-09 — bulk-toewijzen / bulk "hoort niet bij ons" in de verzamelbak (casus: 97 IC-facturen in
één handeling naar Universal Steigerbouw). Server-side een orkestratie over de bestaande per-rij-routes
(geen tweede schrijver): per rij een uitkomst (verwerkt / al_verwerkt / fout mét reden), één kapotte
rij stopt de stapel niet, leren + audit + extractie-start lopen per rij exact als bij de losse klik."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.intake import verzamelbak
from app.intake.models import ToewijzingRegel
from app.main import app
from app.security.tokens import create_access_token
from tests.intake.conftest import bouw_pdf

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _bak_rij(actor_id: uuid.UUID, naam: str, *, tenaamstelling: str | None = "Universal Steigerbouw B.V.") -> uuid.UUID:
    return documenten_service.registreer_niet_toegewezen_document(
        bestandsnaam=naam,
        inhoud=bouw_pdf(1) + naam.encode(),  # unieke sha256 per rij
        actor_id=actor_id,
        reden="tenaamstelling_niet_eenduidig",
        afzender_hint="administratie@universal-steigerbouw.nl",
        tenaamstelling=tenaamstelling,
    )


def _status(admin_engine: Engine, document_id: uuid.UUID) -> tuple[uuid.UUID | None, str]:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text("SELECT administratie_id, status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).one()
    return rij.administratie_id, rij.status


class TestBulkToewijzen:
    def test_stapel_in_een_handeling_met_uitkomst_per_rij(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        ids = [_bak_rij(gescoopte_gebruiker, f"IC-{i}.pdf") for i in range(3)]
        al_afgehandeld = _bak_rij(gescoopte_gebruiker, "niet-van-ons.pdf")
        verzamelbak.hoort_niet_bij_ons(document_id=al_afgehandeld, actor_id=gescoopte_gebruiker, reden="ander kantoor")
        onbekend = uuid.uuid4()

        r = verzamelbak.bulk_wijs_toe(
            document_ids=[*ids, ids[0], al_afgehandeld, onbekend],  # dubbel id = één keer
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
        )
        per_id = {u.document_id: u for u in r.uitkomsten}
        assert len(r.uitkomsten) == 5 and r.verwerkt == 3 and r.fout == 2 and r.al_verwerkt == 0
        for document_id in ids:
            assert per_id[document_id].uitkomst == "verwerkt" and per_id[document_id].bestandsnaam.startswith("IC-")
            adm, status = _status(admin_engine, document_id)
            assert adm == administratie_id and status != "niet_toegewezen"
        # Al "hoort niet bij ons": leesbare reden, geen enum-jargon, rest gewoon verwerkt.
        assert per_id[al_afgehandeld].uitkomst == "fout"
        assert "hoort niet bij ons" in (per_id[al_afgehandeld].reden or "")
        assert per_id[onbekend].uitkomst == "fout" and "niet (meer) in de verzamelbak" in (per_id[onbekend].reden or "")
        # Het geheugen leerde de tenaamstelling één keer (idempotent per rij, zelfde sleutel).
        with scoped_session(None) as session:
            regels = session.scalars(
                select(ToewijzingRegel).where(
                    ToewijzingRegel.sleutel == "universal steigerbouw", ToewijzingRegel.actief
                )
            ).all()
        assert len(regels) == 1 and regels[0].administratie_id == administratie_id

    def test_tweede_keer_is_al_verwerkt(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        ids = [_bak_rij(gescoopte_gebruiker, f"IC-x{i}.pdf") for i in range(2)]
        verzamelbak.bulk_wijs_toe(document_ids=ids, administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        r = verzamelbak.bulk_wijs_toe(document_ids=ids, administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        assert r.al_verwerkt == 2 and r.verwerkt == 0 and r.fout == 0
        assert all("Was al toegewezen" in (u.reden or "") for u in r.uitkomsten)

    def test_onbekende_administratie_is_een_fout_voor_de_hele_aanroep(self, gescoopte_gebruiker: uuid.UUID) -> None:
        document_id = _bak_rij(gescoopte_gebruiker, "IC-y.pdf")
        try:
            verzamelbak.bulk_wijs_toe(
                document_ids=[document_id], administratie_id=uuid.uuid4(), actor_id=gescoopte_gebruiker
            )
        except verzamelbak.OnbekendeAdministratie:
            pass
        else:
            raise AssertionError("onbekende administratie moet weigeren vóór er iets gebeurt")


class TestBulkHoortNietBijOns:
    def test_een_reden_voor_de_hele_selectie(self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine) -> None:
        ids = [_bak_rij(gescoopte_gebruiker, f"spam-{i}.pdf", tenaamstelling=None) for i in range(2)]
        r = verzamelbak.bulk_hoort_niet_bij_ons(document_ids=ids, actor_id=gescoopte_gebruiker, reden="reclame")
        assert r.verwerkt == 2
        for document_id in ids:
            assert _status(admin_engine, document_id) == (None, "afgewezen")
        # Reden verplicht — óók in bulk.
        try:
            verzamelbak.bulk_hoort_niet_bij_ons(document_ids=ids, actor_id=gescoopte_gebruiker, reden="  ")
        except verzamelbak.RedenVerplicht:
            pass
        else:
            raise AssertionError("lege reden moet weigeren")


class TestEndpoints:
    def test_bulk_toewijzen_endpoint(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        kantoor_headers = _bearer(gescoopte_gebruiker)
        ids = [_bak_rij(gescoopte_gebruiker, f"IC-e{i}.pdf") for i in range(2)]
        resp = client.post(
            "/verzamelbak/bulk-toewijzen",
            json={"document_ids": [str(i) for i in ids], "administratie_id": str(administratie_id)},
            headers=kantoor_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verwerkt"] == 2 and body["fout"] == 0
        assert {u["uitkomst"] for u in body["uitkomsten"]} == {"verwerkt"}
        onbekend = client.post(
            "/verzamelbak/bulk-toewijzen",
            json={"document_ids": [str(ids[0])], "administratie_id": str(uuid.uuid4())},
            headers=kantoor_headers,
        )
        assert onbekend.status_code == 409

    def test_bulk_hoort_niet_bij_ons_endpoint_vereist_reden(self, gescoopte_gebruiker: uuid.UUID) -> None:
        kantoor_headers = _bearer(gescoopte_gebruiker)
        document_id = _bak_rij(gescoopte_gebruiker, "spam-e.pdf", tenaamstelling=None)
        leeg = client.post(
            "/verzamelbak/bulk-hoort-niet-bij-ons",
            json={"document_ids": [str(document_id)], "reden": ""},
            headers=kantoor_headers,
        )
        assert leeg.status_code == 422
        ok = client.post(
            "/verzamelbak/bulk-hoort-niet-bij-ons",
            json={"document_ids": [str(document_id)], "reden": "geen klant"},
            headers=kantoor_headers,
        )
        assert ok.status_code == 200 and ok.json()["verwerkt"] == 1


class TestZusjeSignaal:
    def test_ubl_met_al_toegewezen_pdf_zusje_draagt_het_signaal(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        """Casus 02-09: vóór de bundeling werden PDF en UBL van dezelfde factuur los gerouteerd — de PDF via AI
        toegewezen, de UBL in de bak. De bak-rij toont dan het toegewezen zusje (uit het intake-bericht)."""
        from app.intake.models import IntakeBericht

        pdf_doc_id = uuid.uuid4()
        with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
            bericht = IntakeBericht(
                id=uuid.uuid4(),
                message_id=f"<{uuid.uuid4()}@test>",
                afzender="administratie@universal-steigerbouw.nl",
                onderwerp="IC-facturen",
                bron="eml_upload",
                verwerkt_door=gescoopte_gebruiker,
                detail={
                    "bijlagen": [
                        {
                            "bestandsnaam": "Universal Nederland B.V - RLZ-2080143277 - 2026-09-01.pdf",
                            "uitkomst": "toegewezen",
                            "document_id": str(pdf_doc_id),
                            "detail": f"tenaamstelling_register → {administratie_id}",
                        },
                        {
                            "bestandsnaam": "Universal Nederland B.V - RLZ-2080143277 - 2026-09-01.xml",
                            "uitkomst": "verzamelbak",
                            "document_id": None,
                            "detail": "tenaamstelling_niet_eenduidig",
                        },
                    ]
                },
            )
            session.add(bericht)
            session.flush()
            bericht_id = bericht.id
        xml_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam="Universal Nederland B.V - RLZ-2080143277 - 2026-09-01.xml",
            inhoud=b"<Invoice/>",
            actor_id=gescoopte_gebruiker,
            reden="tenaamstelling_niet_eenduidig",
            intake_bericht_id=bericht_id,
            afzender_hint="administratie@universal-steigerbouw.nl",
        )
        los_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam="los.xml",
            inhoud=b"<Invoice>los</Invoice>",
            actor_id=gescoopte_gebruiker,
            reden="tenaamstelling_niet_eenduidig",
            intake_bericht_id=bericht_id,
        )
        items = {i.document_id: i for i in verzamelbak.lijst_verzamelbak()}
        assert items[xml_id].zusje_document_id == pdf_doc_id
        assert items[xml_id].zusje_bestandsnaam == "Universal Nederland B.V - RLZ-2080143277 - 2026-09-01.pdf"
        assert items[xml_id].zusje_administratie_id == administratie_id
        assert items[los_id].zusje_document_id is None
