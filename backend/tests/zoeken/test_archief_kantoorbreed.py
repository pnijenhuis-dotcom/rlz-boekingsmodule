"""Archief B4 (design-ronde 03-09, mockup inzicht-kantoorbreed.html ⑥/⑨): kantoorbreed bladeren
`GET /archief` — scope via mijn_administraties + RLS per administratie (een niet-Beheerder MÉT
scope ziet alleen de eigen administratie), administratie = facet (nooit poort), sortering per
kolom + richting over administraties heen exact gelijk aan de SQL-orde, paginering door
samenvoeging zonder gaten/overlap, diepte-grens leesbaar."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from app.zoeken import archief_kantoorbreed as kb
from app.zoeken import service as zoeken_service
from app.zoeken.service import ArchiefFout, ArchiefSortering
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.zoeken.test_archief_paginering import maak_geboekt_document

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def andere_administratie(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere klant', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


@pytest.fixture
def twee_administraties_gevuld(
    beheerder_id: uuid.UUID,  # noqa: F811
    gescoopte_gebruiker: uuid.UUID,  # noqa: F811
    administratie_id: uuid.UUID,  # noqa: F811
    andere_administratie: uuid.UUID,
    opslag: LokaleBestandsopslag,  # noqa: F811
) -> dict[str, uuid.UUID]:
    """Scope-test (naam 'Scope-test'): zeta 300 / alfa 100 / zonder-leverancier 200.
    Andere klant: mid 250 / beta 50 — alleen zichtbaar voor de Beheerder."""
    eigen = dict(administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag)
    ander = dict(administratie_id=andere_administratie, actor_id=beheerder_id, opslag=opslag)
    return {
        "zeta": maak_geboekt_document(
            **eigen,
            referentie="F-Z",
            vendor_naam="Zeta Steigers",
            factuurdatum=date(2026, 3, 1),
            totaalbedrag=Decimal("300.00"),
            boekstuknummer="IF-0003",
        ),
        "alfa": maak_geboekt_document(
            **eigen,
            referentie="F-A",
            vendor_naam="alfa bouw",
            factuurdatum=date(2026, 1, 1),
            totaalbedrag=Decimal("100.00"),
            boekstuknummer="IF-0001",
        ),
        "zonder": maak_geboekt_document(
            **eigen,
            referentie="F-M",
            vendor_naam=None,
            factuurdatum=date(2026, 2, 1),
            totaalbedrag=Decimal("200.00"),
            boekstuknummer="IF-0002",
        ),
        "mid": maak_geboekt_document(
            **ander,
            referentie="F-MID",
            vendor_naam="Mid Verhuur",
            factuurdatum=date(2026, 2, 15),
            totaalbedrag=Decimal("250.00"),
            boekstuknummer="VK-0002",
        ),
        "beta": maak_geboekt_document(
            **ander,
            referentie="F-B",
            vendor_naam="Beta Materiaal",
            factuurdatum=date(2025, 12, 1),
            totaalbedrag=Decimal("50.00"),
            boekstuknummer="VK-0001",
        ),
    }


def _namen(pagina: kb.KantoorbreedPagina, docs: dict[str, uuid.UUID]) -> list[str]:
    terug = {v: k for k, v in docs.items()}
    return [terug[r.document.document_id] for r in pagina.documenten]


class TestScope:
    def test_niet_beheerder_met_scope_ziet_alleen_eigen_administratie(
        self,
        gescoopte_gebruiker,  # noqa: F811
        administratie_id,  # noqa: F811
        andere_administratie,
        twee_administraties_gevuld,  # noqa: F811
    ) -> None:
        pagina = kb.blader(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING)
        assert pagina.totaal == 3
        assert {r.administratie_id for r in pagina.documenten} == {administratie_id}
        assert [f.administratie_id for f in pagina.facet] == [administratie_id]
        assert pagina.facet[0].aantal == 3 and pagina.facet[0].naam == "Scope-test"
        assert pagina.administraties_met_documenten == 1
        assert {r.administratie_naam for r in pagina.documenten} == {"Scope-test"}

    def test_beheerder_ziet_alles_met_facet_per_administratie(
        self,
        beheerder_id,  # noqa: F811
        administratie_id,  # noqa: F811
        andere_administratie,
        twee_administraties_gevuld,  # noqa: F811
    ) -> None:
        pagina = kb.blader(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER)
        assert pagina.totaal == 5 and pagina.administraties_met_documenten == 2
        assert [(f.naam, f.aantal) for f in pagina.facet] == [("Andere klant", 2), ("Scope-test", 3)]

    def test_facet_is_filter_en_nooit_poort(
        self,
        gescoopte_gebruiker,  # noqa: F811
        beheerder_id,  # noqa: F811
        administratie_id,  # noqa: F811
        andere_administratie,
        twee_administraties_gevuld,  # noqa: F811
    ) -> None:
        # Beheerder filtert op één administratie: alleen die rijen, maar de facetlijst blijft compleet.
        pagina = kb.blader(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, administratie_id=andere_administratie)
        assert pagina.totaal == 2 and {r.administratie_id for r in pagina.documenten} == {andere_administratie}
        assert len(pagina.facet) == 2
        # Niet-Beheerder vraagt een administratie buiten zijn scope: leeg resultaat, géén fout, geen lek.
        buiten = kb.blader(
            actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, administratie_id=andere_administratie
        )
        assert buiten.totaal == 0 and buiten.documenten == [] and buiten.administraties_met_documenten == 0
        assert [f.administratie_id for f in buiten.facet] == [administratie_id]


class TestSortering:
    @pytest.mark.parametrize(
        "sort,verwacht",
        [
            ("leverancier:asc", ["alfa", "beta", "mid", "zeta", "zonder"]),
            ("leverancier:desc", ["zeta", "mid", "beta", "alfa", "zonder"]),
            ("bedrag:asc", ["beta", "alfa", "zonder", "mid", "zeta"]),
            ("bedrag:desc", ["zeta", "mid", "zonder", "alfa", "beta"]),
            ("factuurdatum:asc", ["beta", "alfa", "zonder", "mid", "zeta"]),
            ("boekstuk:desc", ["mid", "beta", "zeta", "zonder", "alfa"]),
        ],
    )
    def test_sorteerbare_kolommen_over_administraties_heen(
        self,
        beheerder_id,  # noqa: F811
        twee_administraties_gevuld,
        sort,
        verwacht,  # noqa: F811
    ) -> None:
        pagina = kb.blader(
            actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, sortering=zoeken_service.parse_archief_sortering(sort)
        )
        assert _namen(pagina, twee_administraties_gevuld) == verwacht

    def test_administratie_kolom_met_secundair_boekmoment(self, beheerder_id, twee_administraties_gevuld) -> None:  # noqa: F811
        # 'andere klant' < 'scope-test'; binnen een administratie nieuwste boekmoment eerst.
        asc = kb.blader(
            actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, sortering=ArchiefSortering("administratie", "asc")
        )
        assert _namen(asc, twee_administraties_gevuld) == ["beta", "mid", "zonder", "alfa", "zeta"]
        desc = kb.blader(
            actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, sortering=ArchiefSortering("administratie", "desc")
        )
        assert _namen(desc, twee_administraties_gevuld) == ["zonder", "alfa", "zeta", "beta", "mid"]

    @pytest.mark.parametrize("kolom", zoeken_service.ARCHIEF_SORTEER_KOLOMMEN)
    @pytest.mark.parametrize("richting", ["asc", "desc"])
    def test_python_samenvoeging_spiegelt_de_sql_orde(
        self,
        gescoopte_gebruiker,  # noqa: F811
        administratie_id,  # noqa: F811
        twee_administraties_gevuld,
        kolom,
        richting,  # noqa: F811
    ) -> None:
        """De top-K-samenvoeging is alleen correct als Python exact dezelfde totale orde hanteert
        als de SQL-sortering binnen één administratie — toets per kolom × richting."""
        sortering = ArchiefSortering(kolom, richting)
        filt = zoeken_service.maak_archief_filter(van=None, tot=None)
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            sql = zoeken_service.archief_rijen(
                session, administratie_id=administratie_id, filt=filt, sortering=sortering, limit=100
            )
        rijen = [kb.KantoorbreedRij(administratie_id, "Scope-test", d) for d in sql]
        # Omgekeerd aanbieden: de Python-sortering moet de SQL-volgorde herstellen.
        python = kb.sorteer(list(reversed(rijen)), sortering)
        assert [r.document.document_id for r in python] == [d.document_id for d in sql]


class TestPaginering:
    def test_paginas_over_administraties_zonder_gaten_of_overlap(
        self, beheerder_id, twee_administraties_gevuld  # noqa: F811
    ) -> None:  # noqa: F811
        sortering = ArchiefSortering("bedrag", "asc")
        alles = kb.blader(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, sortering=sortering, per_pagina=50)
        samengesteld: list[uuid.UUID] = []
        for p in (1, 2, 3):
            pagina = kb.blader(
                actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, sortering=sortering, pagina=p, per_pagina=2
            )
            assert pagina.totaal == 5 and pagina.pagina == p and pagina.per_pagina == 2
            samengesteld.extend(r.document.document_id for r in pagina.documenten)
        assert samengesteld == [r.document.document_id for r in alles.documenten]
        assert len(samengesteld) == 5
        leeg = kb.blader(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, sortering=sortering, pagina=4, per_pagina=2)
        assert leeg.documenten == [] and leeg.totaal == 5

    def test_een_administratie_gebruikt_sql_offset(self, gescoopte_gebruiker, twee_administraties_gevuld) -> None:  # noqa: F811
        p2 = kb.blader(
            actor_id=gescoopte_gebruiker,
            rol=GebruikerRol.BOEKHOUDING,
            pagina=2,
            per_pagina=2,
            sortering=ArchiefSortering("bedrag", "asc"),
        )
        assert _namen(p2, twee_administraties_gevuld) == ["zeta"] and p2.totaal == 3

    def test_diepte_grens_bij_meerdere_administraties(self, beheerder_id, twee_administraties_gevuld) -> None:  # noqa: F811
        with pytest.raises(ArchiefFout, match="kies een administratie"):
            kb.blader(
                actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, pagina=kb.MAX_DIEPTE // 200 + 1, per_pagina=200
            )
        with pytest.raises(ArchiefFout):
            kb.blader(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, per_pagina=0)

    def test_datumvenster_en_zoekterm_werken_kantoorbreed(self, beheerder_id, twee_administraties_gevuld) -> None:  # noqa: F811
        assert kb.blader(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, q="mid").totaal == 1
        assert kb.blader(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, q="IF-000").totaal == 3
        vandaag = date.today()
        assert kb.blader(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, van=vandaag, tot=vandaag).totaal == 5
        assert (
            kb.blader(
                actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, van=date(2020, 1, 1), tot=date(2020, 12, 31)
            ).totaal
            == 0
        )


class TestRoute:
    def test_route_scope_en_422(self, gescoopte_gebruiker, administratie_id, twee_administraties_gevuld) -> None:  # noqa: F811
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        resp = client.get("/archief", params={"sort": "bedrag:desc", "per_pagina": 2}, headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["totaal"] == 3 and body["administraties_met_documenten"] == 1 and body["per_pagina"] == 2
        assert [d["totaalbedrag"] for d in body["documenten"]] == ["300.00", "200.00"]
        assert body["documenten"][0]["administratie_id"] == str(administratie_id)
        assert body["documenten"][0]["administratie_naam"] == "Scope-test"
        assert body["facet"] == [{"administratie_id": str(administratie_id), "naam": "Scope-test", "aantal": 3}]
        assert client.get("/archief", params={"sort": "status:asc"}, headers=headers).status_code == 422
        assert client.get("/archief", params={"per_pagina": 201}, headers=headers).status_code == 422
        assert (
            client.get("/archief", params={"van": "2026-02-01", "tot": "2026-01-01"}, headers=headers).status_code
            == 422
        )
        assert client.get("/archief", params={"administratie_id": "geen-uuid"}, headers=headers).status_code == 422
