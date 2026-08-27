"""Accordering-nazorg (werkstroom-run 27/28-08, punt 2 — casus 34 facturen): (a) een wijziging van de
accorderingsconfiguratie laat lopende rondes expliciet VERVALLEN mét reden in de tijdlijn + een
batch voor de werkvoorraad-melding; een opslag zonder effectieve wijziging raakt niets; (b) bulk
"Ter accordering aanbieden" met exact de losse poorten — geweigerd = overgeslagen mét reden."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.accordering import service
from app.accordering.models import AccorderingStatus
from app.documenten import service as documenten_service
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from tests.accordering.conftest import document_status, maak_klaar_document, zet_schema

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _laag(volgnummer: int, accordeur: uuid.UUID, drempel: str | None = None) -> service.LaagInput:
    from decimal import Decimal

    return service.LaagInput(
        volgnummer=volgnummer, accordeur_gebruiker_id=accordeur, bedrag_drempel=Decimal(drempel) if drempel else None
    )


def _accordering_status(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r.status
            for r in conn.execute(
                text(
                    "SELECT status FROM boekhouding.document_accordering WHERE document_id = :id ORDER BY aangeboden_op"
                ),
                {"id": document_id},
            )
        ]


def _bied_aan(administratie_id: uuid.UUID, document_id: uuid.UUID, actor: uuid.UUID) -> None:
    service.bied_ter_accordering_aan(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor, actor_rol="boekhouding"
    )


class TestVervallenBijConfiguratiewijziging:
    def test_gewijzigde_lagen_laten_lopende_rondes_vervallen_met_reden(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        assert service.wachtrij_voor_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])

        # Andere accordeur op laag 1 → de bevroren stap (accordeur_1) klopt niet meer.
        vervallen = zet_schema(
            administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_2)]
        )
        assert vervallen == 1
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"
        assert _accordering_status(admin_engine, klaar_document) == [AccorderingStatus.VERVALLEN.value]
        # Niemand ziet 'm meer in een wachtrij — ook de nieuwe accordeur niet (opnieuw aanbieden is de weg).
        assert service.wachtrij_voor_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id]) == []
        assert service.wachtrij_voor_accordeur(actor_id=accordeur_2, administratie_ids=[administratie_id]) == []

        # Tijdlijnregel draagt de REDEN + batch_id (punt 2a) — dit was eerder een raadsel.
        detail = documenten_service.haal_document_op(administratie_id=administratie_id, document_id=klaar_document)
        regels = [g for g in detail.gebeurtenissen if g.detail and g.detail.get("accordering_vervallen")]
        assert len(regels) == 1
        assert regels[0].van_status.value == "ter_accordering"
        assert regels[0].naar_status.value == "klaar_om_te_boeken"
        assert regels[0].detail["reden"] == service.VERVALLEN_REDEN
        assert regels[0].detail["reden"] == "accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist"
        uuid.UUID(regels[0].detail["batch_id"])
        assert regels[0].actor_id == beheerder_id  # de mens die de configuratie wijzigde, herleidbaar

        with admin_engine.connect() as conn:
            acties = {
                r.actie
                for r in conn.execute(
                    text("SELECT actie FROM platform.audit_event WHERE tabel = 'document_accordering'")
                )
            }
        assert "accordering_vervallen" in acties

        # Werkvoorraad-melding: één batch, 1 vervallen, 1 nog niet opnieuw aangeboden.
        meldingen = service.vervallen_meldingen(administratie_id=administratie_id)
        assert len(meldingen) == 1
        assert meldingen[0].aantal == 1
        assert meldingen[0].nog_niet_opnieuw_aangeboden == 1
        assert meldingen[0].door_gebruiker_id == beheerder_id

        # Opnieuw aanbieden werkt gewoon (verse ronde) — en de melding is dan 'klaar' (0 open).
        _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        assert _accordering_status(admin_engine, klaar_document) == [
            AccorderingStatus.VERVALLEN.value,
            AccorderingStatus.OPEN.value,
        ]
        assert service.vervallen_meldingen(administratie_id=administratie_id)[0].nog_niet_opnieuw_aangeboden == 0

    def test_opslaan_zonder_effectieve_wijziging_raakt_geen_ronde(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        lagen = [_laag(1, accordeur_1), _laag(2, accordeur_2, "1000.00")]
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=lagen)
        _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)

        # Zelfde schema opnieuw opslaan (andere volgorde, drempel als '1000' i.p.v. '1000.00').
        vervallen = zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(2, accordeur_2, "1000"), _laag(1, accordeur_1)],
        )
        assert vervallen == 0
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        assert _accordering_status(admin_engine, klaar_document) == [AccorderingStatus.OPEN.value]
        assert service.vervallen_meldingen(administratie_id=administratie_id) == []

    def test_toggle_uit_laat_rondes_vervallen(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)
        vervallen = zet_schema(
            administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[], ingeschakeld=False
        )
        assert vervallen == 1
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"

    def test_put_response_draagt_rondes_vervallen(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)
        resp = client.put(
            f"/administraties/{administratie_id}/accordering/instellingen",
            json={"ingeschakeld": True, "lagen": [{"volgnummer": 1, "accordeur_gebruiker_id": str(accordeur_2)}]},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["rondes_vervallen"] == 1
        # GET draagt 'm niet (alleen een uitkomst van de PUT).
        resp = client.get(
            f"/administraties/{administratie_id}/accordering/instellingen",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.json()["rondes_vervallen"] == 0
        # Vervallen-melding via HTTP (kantoor).
        resp = client.get(
            f"/administraties/{administratie_id}/accordering/vervallen-meldingen",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body) == 1
        assert body[0]["aantal"] == 1
        assert body[0]["nog_niet_opnieuw_aangeboden"] == 1
        assert body[0]["reden"] == service.VERVALLEN_REDEN
        assert body[0]["door_naam"]


class TestBulkAanbieden:
    def test_bulk_biedt_aan_en_slaat_over_met_reden(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        tweede = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="tweede.pdf")
        # Derde document staat al ter accordering → poort "loopt al een ronde".
        derde = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="derde.pdf")
        _bied_aan(administratie_id, derde, gescoopte_gebruiker)
        onbekend = uuid.uuid4()

        resultaten = service.bulk_aanbieden(
            administratie_id=administratie_id,
            document_ids=[klaar_document, tweede, derde, onbekend, klaar_document],  # dubbel = één keer
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        per_id = {r.document_id: r for r in resultaten}
        assert len(resultaten) == 4
        assert per_id[klaar_document].uitkomst == "aangeboden"
        assert per_id[klaar_document].bestandsnaam == "factuur.pdf"
        assert per_id[tweede].uitkomst == "aangeboden"
        assert per_id[derde].uitkomst == "overgeslagen"
        assert "ter_accordering" in (per_id[derde].reden or "")
        assert per_id[onbekend].uitkomst == "overgeslagen"
        assert per_id[onbekend].reden == "Document niet gevonden in deze administratie"
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        assert document_status(admin_engine, tweede) == "ter_accordering"
        assert len(service.wachtrij_voor_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])) == 3

    def test_bulk_http_tellers_en_accordeur_geweigerd(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        pad = f"/administraties/{administratie_id}/accordering/documenten/bulk-aanbieden"
        resp = client.post(
            pad,
            json={"document_ids": [str(klaar_document), str(uuid.uuid4())]},
            headers=_bearer(accordeur_1, rol="klant_accordeur"),
        )
        assert resp.status_code == 403
        resp = client.post(
            pad,
            json={"document_ids": [str(klaar_document), str(uuid.uuid4())]},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["aangeboden"] == 1
        assert body["geboekt"] == 0
        assert body["overgeslagen"] == 1
        assert {r["uitkomst"] for r in body["resultaten"]} == {"aangeboden", "overgeslagen"}
        # Lege selectie = 422 (min_length).
        resp = client.post(pad, json={"document_ids": []}, headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert resp.status_code == 422
