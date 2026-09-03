"""Archief C1 (design-ronde 03-09, mockup inzicht-kantoorbreed.html ⑥ — directe bugfix): de
per-administratie-route gaf 7 jaar historie in één response zonder LIMIT. Sinds C1: verplichte
server-side paginering (default 25, max 200) mét aparte telling, default-datumvenster (laatste 12
maanden op boekmoment, terugval factuurdatum), optioneel `van`/`tot`, zoekterm en server-side
sortering per kolom (conventie punt 21: ontbrekende waarden achteraan)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.db.session import scoped_session
from app.documenten import boekvoorstel
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from app.sync.models import VendorCache
from app.zoeken import service as zoeken_service
from app.zoeken.service import ArchiefFout, ArchiefSortering
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "boekhouding") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def maak_geboekt_document(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,  # noqa: F811
    referentie: str,
    vendor_naam: str | None = "Bouwmaat Nederland B.V.",
    factuurdatum: date = date(2026, 7, 1),
    totaalbedrag: Decimal = Decimal("922.04"),
    boekstuknummer: str | None = "IF-2026-0219",
    boeken: bool = True,
) -> uuid.UUID:
    """Upload + boekvoorstel + (optioneel) de statusmachine-route naar GEBOEKT (tijdlijn incluis)."""
    vendor_id: uuid.UUID | None = None
    if vendor_naam is not None:
        vendor_id = uuid.uuid4()
        with scoped_session(administratie_id) as session:
            session.add(VendorCache(id=vendor_id, administratie_id=administratie_id, naam=vendor_naam, brondata={}))
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"factuur-{referentie}.pdf",
        inhoud=f"%PDF-1.4 {referentie}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=factuurdatum,
        totaalbedrag=totaalbedrag,
        regels=[],
    )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        from app.documenten.models import Boekvoorstel

        voorstel = session.get(Boekvoorstel, resultaat.document_id)
        voorstel.rlz_boekstuknummer = boekstuknummer
        if boeken:
            document = session.get(Document, resultaat.document_id)
            documenten_service._schrijf_overgang(
                session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=actor_id
            )
            documenten_service._schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.GEBOEKT,
                actor_id=actor_id,
                detail={"rlz_boekstuknummer": boekstuknummer},
            )
    return resultaat.document_id


class TestPureHelpers:
    def test_maanden_terug_schuift_naar_bestaande_kalenderdag(self) -> None:
        assert zoeken_service._maanden_terug(date(2026, 9, 3), 12) == date(2025, 9, 3)
        assert zoeken_service._maanden_terug(date(2026, 3, 31), 12) == date(2025, 3, 31)
        assert zoeken_service._maanden_terug(date(2024, 2, 29), 12) == date(2023, 2, 28)
        assert zoeken_service._maanden_terug(date(2026, 1, 15), 12) == date(2025, 1, 15)

    def test_standaard_venster_is_twaalf_maanden_tot_vandaag(self) -> None:
        van, tot = zoeken_service.standaard_datumvenster(date(2026, 9, 3))
        assert (van, tot) == (date(2025, 9, 3), date(2026, 9, 3))

    def test_filter_vult_ontbrekende_grenzen_en_weigert_omgekeerd_venster(self) -> None:
        f = zoeken_service.maak_archief_filter(van=None, tot=None, q="  x ", vandaag=date(2026, 9, 3))
        assert (f.van, f.tot, f.q) == (date(2025, 9, 3), date(2026, 9, 3), "x")
        f = zoeken_service.maak_archief_filter(van=date(2020, 1, 1), tot=None, vandaag=date(2026, 9, 3))
        assert (f.van, f.tot) == (date(2020, 1, 1), date(2026, 9, 3))
        with pytest.raises(ArchiefFout):
            zoeken_service.maak_archief_filter(van=date(2026, 2, 1), tot=date(2026, 1, 1))

    def test_sortering_parsen_volgt_de_documentenlijst_conventie(self) -> None:
        assert zoeken_service.parse_archief_sortering(None) == zoeken_service.STANDAARD_ARCHIEF_SORTERING
        assert zoeken_service.parse_archief_sortering("") == zoeken_service.STANDAARD_ARCHIEF_SORTERING
        assert zoeken_service.parse_archief_sortering("bedrag:desc") == ArchiefSortering("bedrag", "desc")
        assert zoeken_service.parse_archief_sortering("leverancier") == ArchiefSortering("leverancier", "asc")
        with pytest.raises(ArchiefFout):
            zoeken_service.parse_archief_sortering("status:asc")
        with pytest.raises(ArchiefFout):
            zoeken_service.parse_archief_sortering("bedrag:omhoog")


class TestPaginering:
    def test_paginering_grenzen_en_totaal(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,  # noqa: F811
        opslag: LokaleBestandsopslag,  # noqa: F811
    ) -> None:
        ids = [
            maak_geboekt_document(
                administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, referentie=f"F-{n}"
            )
            for n in range(3)
        ]
        # Een niet-geboekt document telt nooit mee.
        maak_geboekt_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            referentie="F-OPEN",
            boekstuknummer=None,
            boeken=False,
        )
        p1 = zoeken_service.archief(administratie_id=administratie_id, pagina=1, per_pagina=2)
        p2 = zoeken_service.archief(administratie_id=administratie_id, pagina=2, per_pagina=2)
        p3 = zoeken_service.archief(administratie_id=administratie_id, pagina=3, per_pagina=2)
        assert (p1.totaal, p2.totaal, p3.totaal) == (3, 3, 3)
        assert len(p1.documenten) == 2 and len(p2.documenten) == 1 and p3.documenten == []
        assert (p1.pagina, p1.per_pagina) == (1, 2)
        # Geen overlap en compleet: samen precies de drie geboekte documenten.
        assert {d.document_id for d in p1.documenten} | {d.document_id for d in p2.documenten} == set(ids)
        # Default-venster staat expliciet in het antwoord (frontend toont de velden ingevuld).
        van, tot = zoeken_service.standaard_datumvenster()
        assert (p1.van, p1.tot) == (van, tot)
        assert all(d.geboekt_op is not None for d in p1.documenten)

    def test_ongeldige_paginering_wordt_geweigerd(self, administratie_id: uuid.UUID) -> None:  # noqa: F811
        with pytest.raises(ArchiefFout):
            zoeken_service.archief(administratie_id=administratie_id, pagina=0)
        with pytest.raises(ArchiefFout):
            zoeken_service.archief(administratie_id=administratie_id, per_pagina=0)
        with pytest.raises(ArchiefFout):
            zoeken_service.archief(
                administratie_id=administratie_id, per_pagina=zoeken_service.ARCHIEF_PER_PAGINA_MAX + 1
            )


class TestDatumvenster:
    def test_venster_op_boekmoment(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,  # noqa: F811
        opslag: LokaleBestandsopslag,  # noqa: F811
    ) -> None:
        maak_geboekt_document(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, referentie="F-NU"
        )
        vandaag = date.today()
        # Vandaag geboekt: binnen [vandaag, vandaag] — ook al ligt de factuurdatum (2026-07-01) erbuiten.
        assert zoeken_service.archief(administratie_id=administratie_id, van=vandaag, tot=vandaag).totaal == 1
        # Venster vóór resp. ná het boekmoment: niets.
        assert (
            zoeken_service.archief(
                administratie_id=administratie_id, van=vandaag - timedelta(days=30), tot=vandaag - timedelta(days=1)
            ).totaal
            == 0
        )
        assert (
            zoeken_service.archief(
                administratie_id=administratie_id, van=vandaag + timedelta(days=1), tot=vandaag + timedelta(days=30)
            ).totaal
            == 0
        )

    def test_zonder_boekmoment_valt_het_venster_terug_op_de_factuurdatum(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,  # noqa: F811
        opslag: LokaleBestandsopslag,  # noqa: F811
    ) -> None:
        """Een geboekt document zónder GEBOEKT-overgang in de tijdlijn (oude/geïmporteerde rij) telt
        op factuurdatum: buiten het default-venster onzichtbaar, met een expliciet venster vindbaar."""
        doc_id = maak_geboekt_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            referentie="F-OUD",
            factuurdatum=date(2024, 1, 15),
            boeken=False,
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            session.get(Document, doc_id).status = DocumentStatus.GEBOEKT
        assert zoeken_service.archief(administratie_id=administratie_id).totaal == 0
        oud = zoeken_service.archief(administratie_id=administratie_id, van=date(2024, 1, 1), tot=date(2024, 1, 31))
        assert [d.document_id for d in oud.documenten] == [doc_id]
        assert oud.documenten[0].geboekt_op is None
        assert oud.documenten[0].factuurdatum == date(2024, 1, 15)


class TestSorteringEnZoeken:
    @pytest.fixture
    def drie_documenten(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,  # noqa: F811
        opslag: LokaleBestandsopslag,  # noqa: F811
    ) -> dict[str, uuid.UUID]:
        return {
            "zeta": maak_geboekt_document(
                administratie_id=administratie_id,
                actor_id=gescoopte_gebruiker,
                opslag=opslag,
                referentie="F-Z",
                vendor_naam="Zeta Steigers",
                factuurdatum=date(2026, 3, 1),
                totaalbedrag=Decimal("300.00"),
                boekstuknummer="IF-0003",
            ),
            "alfa": maak_geboekt_document(
                administratie_id=administratie_id,
                actor_id=gescoopte_gebruiker,
                opslag=opslag,
                referentie="F-A",
                vendor_naam="alfa bouw",
                factuurdatum=date(2026, 1, 1),
                totaalbedrag=Decimal("100.00"),
                boekstuknummer="IF-0001",
            ),
            "zonder": maak_geboekt_document(
                administratie_id=administratie_id,
                actor_id=gescoopte_gebruiker,
                opslag=opslag,
                referentie="F-M",
                vendor_naam=None,
                factuurdatum=date(2026, 2, 1),
                totaalbedrag=Decimal("200.00"),
                boekstuknummer="IF-0002",
            ),
        }

    def _volgorde(self, administratie_id: uuid.UUID, sort: str, docs: dict[str, uuid.UUID]) -> list[str]:  # noqa: F811
        terug = {v: k for k, v in docs.items()}
        pagina = zoeken_service.archief(
            administratie_id=administratie_id, sortering=zoeken_service.parse_archief_sortering(sort)
        )
        return [terug[d.document_id] for d in pagina.documenten]

    def test_leverancier_hoofdletterongevoelig_en_leeg_achteraan(self, administratie_id, drie_documenten) -> None:  # noqa: F811
        assert self._volgorde(administratie_id, "leverancier:asc", drie_documenten) == ["alfa", "zeta", "zonder"]
        assert self._volgorde(administratie_id, "leverancier:desc", drie_documenten) == ["zeta", "alfa", "zonder"]

    def test_bedrag_factuurdatum_en_boekstuk(self, administratie_id, drie_documenten) -> None:  # noqa: F811
        assert self._volgorde(administratie_id, "bedrag:asc", drie_documenten) == ["alfa", "zonder", "zeta"]
        assert self._volgorde(administratie_id, "bedrag:desc", drie_documenten) == ["zeta", "zonder", "alfa"]
        assert self._volgorde(administratie_id, "factuurdatum:asc", drie_documenten) == ["alfa", "zonder", "zeta"]
        assert self._volgorde(administratie_id, "boekstuk:desc", drie_documenten) == ["zeta", "zonder", "alfa"]

    def test_standaard_is_boekmoment_nieuwste_eerst(self, administratie_id, drie_documenten) -> None:  # noqa: F811
        # Aangemaakt in de volgorde zeta → alfa → zonder; nieuwste boekmoment eerst.
        assert self._volgorde(administratie_id, "", drie_documenten) == ["zonder", "alfa", "zeta"]

    def test_zoekterm_op_leverancier_referentie_boekstuk_en_bedrag(self, administratie_id, drie_documenten) -> None:  # noqa: F811
        def zoek(q: str) -> set[uuid.UUID]:
            return {d.document_id for d in zoeken_service.archief(administratie_id=administratie_id, q=q).documenten}

        assert zoek("ALFA") == {drie_documenten["alfa"]}
        assert zoek("F-Z") == {drie_documenten["zeta"]}
        assert zoek("IF-0002") == {drie_documenten["zonder"]}
        assert zoek("200,00") == {drie_documenten["zonder"]}
        assert zoek("bestaat-niet") == set()
        assert zoeken_service.archief(administratie_id=administratie_id, q="ALFA").totaal == 1


class TestRoute:
    def test_route_pagineert_en_vertaalt_ongeldige_invoer_naar_422(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,  # noqa: F811
        opslag: LokaleBestandsopslag,  # noqa: F811
    ) -> None:
        maak_geboekt_document(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, referentie="F-R"
        )
        headers = _bearer(gescoopte_gebruiker)
        pad = f"/administraties/{administratie_id}/archief"
        resp = client.get(pad, headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["totaal"] == 1 and body["pagina"] == 1 and body["per_pagina"] == 25
        van, tot = zoeken_service.standaard_datumvenster()
        assert (body["van"], body["tot"]) == (van.isoformat(), tot.isoformat())
        assert body["documenten"][0]["rlz_boekstuknummer"] == "IF-2026-0219"

        assert client.get(pad, params={"per_pagina": 500}, headers=headers).status_code == 422
        assert client.get(pad, params={"pagina": 0}, headers=headers).status_code == 422
        assert client.get(pad, params={"van": "2026-02-01", "tot": "2026-01-01"}, headers=headers).status_code == 422
        assert client.get(pad, params={"sort": "status:asc"}, headers=headers).status_code == 422
        leeg = client.get(pad, params={"pagina": 2}, headers=headers).json()
        assert leeg["documenten"] == [] and leeg["totaal"] == 1
