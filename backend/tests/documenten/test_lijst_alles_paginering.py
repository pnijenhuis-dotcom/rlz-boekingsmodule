"""Feedbackrun A blok 8 (FV-20, Peter 25-09): "Alle" toonde niet alles. Sinds 25-09 heet de kantoorwerk-lijst "Open (N)"
en bestaat er een échte groep `alles` = kantoor ∪ wachten ∪ afgehandeld — server-side gepagineerd (limit default 200,
max 500, offset, `totaal`) — waarop het zoekveld server-side zoekt (`q`: leverancier, referentie/factuurnummer,
bestandsnaam, bedrag). Casus uit de feedback: de Exact-factuur op "wachten op anderen" (ter accordering) was onder
"alle" niet vindbaar; óók een geboekt document moet via zoeken terugkomen. Zonder `groep=alles` blijft het bestaande
gedrag byte-gelijk."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.models import Document, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from app.sync.models import VendorCache

client = TestClient(app)

VENDOR_EXACT = uuid.UUID("11111111-2222-4333-8444-555555555501")
VENDOR_FLOOR = uuid.UUID("11111111-2222-4333-8444-555555555502")
NAAR_KLAAR = (DocumentStatus.EXTRACTIE_BEZIG, DocumentStatus.TE_CONTROLEREN, DocumentStatus.KLAAR_OM_TE_BOEKEN)


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _upload(actor: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, naam: str) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id, bestandsnaam=naam, inhoud=uuid.uuid4().bytes, actor_id=actor, opslag=opslag
    ).document_id


def _zet_status(administratie_id: uuid.UUID, actor: uuid.UUID, document_id: uuid.UUID, *pad: DocumentStatus) -> None:
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        for naar in pad:
            service._schrijf_overgang(session, document=document, naar=naar, actor_id=actor)
        session.commit()


def _voorstel(
    administratie_id: uuid.UUID, actor: uuid.UUID, document_id: uuid.UUID, *, vendor: uuid.UUID, ref: str, bedrag: str
) -> None:
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor,
        vendor_id=vendor,
        referentie=ref,
        factuurdatum=date(2026, 9, 1),
        totaalbedrag=Decimal(bedrag),
        regels=[],
    )


@pytest.fixture
def casus(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, admin_engine: Engine
) -> dict[str, uuid.UUID]:
    """Zeven documenten over de drie groepen: 3 kantoor (te controleren), 1 wachten (Exact ter accordering — de casus),
    2 afgehandeld (geboekt Floor + verwijderd), 1 kantoor mét een gelezen veldvoorstel (zonder opgeslagen
    boekvoorstel)."""
    actor = gescoopte_gebruiker
    with scoped_session(administratie_id) as session:
        session.add(
            VendorCache(id=VENDOR_EXACT, administratie_id=administratie_id, naam="Exact Online B.V.", brondata={})
        )
        session.add(
            VendorCache(id=VENDOR_FLOOR, administratie_id=administratie_id, naam="Floor Bouwliftenservice", brondata={})
        )
        session.commit()
    ids = {
        "werk_1": _upload(actor, administratie_id, opslag, "werk-1.pdf"),
        "werk_2": _upload(actor, administratie_id, opslag, "werk-2.pdf"),
        "werk_3": _upload(actor, administratie_id, opslag, "werk-3.pdf"),
        "exact": _upload(actor, administratie_id, opslag, "exact-abonnement.pdf"),
        "floor_geboekt": _upload(actor, administratie_id, opslag, "floor-26219.pdf"),
        "verwijderd": _upload(actor, administratie_id, opslag, "dubbel.pdf"),
        "gelezen": _upload(actor, administratie_id, opslag, "scan-zonder-voorstel.pdf"),
    }
    for sleutel in ("werk_1", "werk_2", "werk_3"):
        _zet_status(
            administratie_id, actor, ids[sleutel], DocumentStatus.EXTRACTIE_BEZIG, DocumentStatus.TE_CONTROLEREN
        )
    # De Exact-factuur: opgeslagen voorstel (crediteur + referentie + bedrag), daarna bij de klant (laag 2 in de
    # accordering — voor de lijst telt de status: ter_accordering = "wachten op anderen").
    _zet_status(administratie_id, actor, ids["exact"], *NAAR_KLAAR)
    _voorstel(administratie_id, actor, ids["exact"], vendor=VENDOR_EXACT, ref="2026-09-EXACT-0417", bedrag="121.00")
    _zet_status(administratie_id, actor, ids["exact"], DocumentStatus.TER_ACCORDERING)
    _zet_status(administratie_id, actor, ids["floor_geboekt"], *NAAR_KLAAR)
    _voorstel(administratie_id, actor, ids["floor_geboekt"], vendor=VENDOR_FLOOR, ref="26219", bedrag="802.23")
    _zet_status(administratie_id, actor, ids["floor_geboekt"], DocumentStatus.GEBOEKT)
    service.verwijder_document(
        administratie_id=administratie_id, document_id=ids["verwijderd"], actor_id=actor, reden="dubbel"
    )
    # Gelezen veldvoorstel zonder opgeslagen boekvoorstel (de extractie-uitkomst in de tijdlijn).
    with scoped_session(administratie_id) as session:
        document = session.get(Document, ids["gelezen"])
        assert document is not None
        service._schrijf_overgang(session, document=document, naar=DocumentStatus.EXTRACTIE_BEZIG, actor_id=actor)
        service._schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.TE_CONTROLEREN,
            actor_id=actor,
            detail={
                "veldvoorstel": {
                    "leverancier_naam": "Hoogwerkservice Hardinxveld",
                    "factuurnummer": "HW-2026-88",
                    "totaal_incl": "690.00",
                }
            },
        )
        session.commit()
    return ids


class TestGroepAlles:
    def test_alles_is_de_unie_van_de_drie_groepen_en_zonder_groep_blijft_oud_gedrag(
        self, casus: dict[str, uuid.UUID], administratie_id: uuid.UUID
    ) -> None:
        alles = {i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, groep="alles")}
        assert alles == set(casus.values()), "alles = kantoor ∪ wachten ∪ afgehandeld, ongeacht toggles"
        kantoor = {i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, groep="kantoor")}
        wachten = {i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, groep="wachten")}
        afgehandeld = {
            i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, groep="afgehandeld")
        }
        assert alles == kantoor | wachten | afgehandeld
        assert casus["exact"] in wachten and casus["exact"] not in kantoor
        # Zonder groep (bestaande aanroepen): kantoor + wachten, afgehandeld verborgen — byte-gelijk oud gedrag.
        standaard = {i.document.id for i in service.lijst_documenten(administratie_id=administratie_id)}
        assert standaard == kantoor | wachten
        assert service.tel_documenten(administratie_id=administratie_id) == len(casus)
        assert service.tel_documenten(administratie_id=administratie_id, groep="wachten") == 1
        with pytest.raises(ValueError):
            service.tel_documenten(administratie_id=administratie_id, groep="onzin")

    def test_paginering_limit_offset_en_totaal(self, casus: dict[str, uuid.UUID], administratie_id: uuid.UUID) -> None:
        pagina_1 = service.lijst_documenten(administratie_id=administratie_id, groep="alles", limit=3, offset=0)
        pagina_2 = service.lijst_documenten(administratie_id=administratie_id, groep="alles", limit=3, offset=3)
        pagina_3 = service.lijst_documenten(administratie_id=administratie_id, groep="alles", limit=3, offset=6)
        assert (len(pagina_1), len(pagina_2), len(pagina_3)) == (3, 3, 1)
        ids = [i.document.id for i in pagina_1 + pagina_2 + pagina_3]
        assert len(set(ids)) == len(casus) and set(ids) == set(casus.values()), (
            "pagina's overlappen niet en dekken alles"
        )
        # Deterministische volgorde: nieuwste eerst, ties op id — twee keer dezelfde pagina = dezelfde rijen.
        assert [i.document.id for i in pagina_1] == [
            i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, groep="alles", limit=3)
        ]
        assert service.tel_documenten(administratie_id=administratie_id, groep="alles") == len(casus)

    def test_zoekterm_vindt_wachten_op_anderen_en_geboekt_server_side(
        self, casus: dict[str, uuid.UUID], administratie_id: uuid.UUID
    ) -> None:
        def zoek(q: str) -> set[uuid.UUID]:
            return {
                i.document.id for i in service.lijst_documenten(administratie_id=administratie_id, groep="alles", q=q)
            }

        # De casus uit de feedback: "Exact" op wachten_op_anderen — via leverancier, referentie én bedrag vindbaar.
        assert zoek("exact") == {casus["exact"]}
        assert zoek("EXACT-0417") == {casus["exact"]}
        assert zoek("121,00") == {casus["exact"]}
        assert service.tel_documenten(administratie_id=administratie_id, q="exact") == 1
        # Geboekt (afgehandeld) is óók vindbaar — op naam, referentie en bestandsnaam.
        assert zoek("floor") == {casus["floor_geboekt"]}
        assert zoek("26219") == {casus["floor_geboekt"]}
        # Zonder opgeslagen boekvoorstel telt het gelezen veldvoorstel (leverancier/factuurnummer/totaal).
        assert zoek("hoogwerkservice") == {casus["gelezen"]}
        assert zoek("HW-2026-88") == {casus["gelezen"]}
        assert zoek("690.00") == {casus["gelezen"]}
        # Bestandsnaam blijft doorzoekbaar; een niet-bestaande term = leeg (nooit alles).
        assert zoek("werk-2") == {casus["werk_2"]}
        assert zoek("bestaat-niet-xyz") == set()
        assert zoek("   ") == set(casus.values())
        # Zoekterm mét paginering: totaal en pagina zijn consistent.
        assert service.tel_documenten(administratie_id=administratie_id, q="werk-") == 3
        assert len(service.lijst_documenten(administratie_id=administratie_id, groep="alles", q="werk-", limit=2)) == 2

    def test_router_groep_alles_draagt_totaal_pagina_en_tellers(
        self, casus: dict[str, uuid.UUID], gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker)
        basis = f"/administraties/{administratie_id}/documenten"

        alles = client.get(basis, params={"groep": "alles"}, headers=headers)
        assert alles.status_code == 200, alles.text
        body = alles.json()
        assert {d["id"] for d in body["documenten"]} == {str(i) for i in casus.values()}
        assert body["totaal"] == len(casus) and body["limit"] == 200 and body["offset"] == 0
        assert body["groepen"] == {"kantoor": 4, "wachten": 1, "afgehandeld": 2, "alles": 7}
        # Élke rij draagt zijn status (de statuschip in de lijst) — geboekt en verwijderd zitten er gewoon in.
        statussen = {d["id"]: d["status"] for d in body["documenten"]}
        assert statussen[str(casus["exact"])] == "ter_accordering"
        assert statussen[str(casus["floor_geboekt"])] == "geboekt"
        assert statussen[str(casus["verwijderd"])] == "verwijderd"

        pagina = client.get(basis, params={"groep": "alles", "limit": 3, "offset": 3}, headers=headers).json()
        assert len(pagina["documenten"]) == 3 and pagina["totaal"] == 7 and pagina["offset"] == 3
        assert client.get(basis, params={"groep": "alles", "limit": 501}, headers=headers).status_code == 422
        assert client.get(basis, params={"groep": "alles", "limit": 0}, headers=headers).status_code == 422

        gezocht = client.get(basis, params={"groep": "alles", "q": "exact"}, headers=headers).json()
        assert [d["id"] for d in gezocht["documenten"]] == [str(casus["exact"])]
        assert gezocht["totaal"] == 1 and gezocht["groepen"]["alles"] == 7  # de groep-tellers blijven de volle stand

        # Zonder groep: `q`/`limit`/`totaal` doen niets — het bestaande antwoord is byte-gelijk (geen totaal/pagina).
        oud = client.get(basis, headers=headers).json()
        oud_met_q = client.get(basis, params={"q": "exact", "limit": 2}, headers=headers).json()
        assert oud == oud_met_q
        assert oud["totaal"] is None and oud["limit"] is None and oud["offset"] is None
        assert {d["id"] for d in oud["documenten"]} == {
            str(casus[k]) for k in ("werk_1", "werk_2", "werk_3", "exact", "gelezen")
        }

    def test_rolpoort_ongewijzigd_buiten_scope_403(
        self, casus: dict[str, uuid.UUID], gescoopte_gebruiker: uuid.UUID
    ) -> None:
        """De lijst-route blijft achter `vereis_administratie_scope`: een administratie buiten de scope van de
        boekhouder = 403/404, ook mét groep=alles (geen nieuwe leesweg om de RLS heen)."""
        vreemd = uuid.uuid4()
        resp = client.get(
            f"/administraties/{vreemd}/documenten",
            params={"groep": "alles", "q": "exact"},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code in (403, 404), resp.text
