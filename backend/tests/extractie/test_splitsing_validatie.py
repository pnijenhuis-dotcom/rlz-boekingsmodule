"""Intake-splitsingsbug (spoedopdracht 02-09, diagnose punt 1): het pagina-aantal gaat als feit
mee in de opdracht en de paginabereik-validatie is proportioneel — een ongeldig bereik verwerpt
nooit meer het hele voorstel (en dus nooit meer de correct gelezen tenaamstelling)."""

from __future__ import annotations

import pytest

from app.extractie import splitsing
from app.extractie.client import AiExtractieFout, ClaudeAntwoord
from app.extractie.splitsing import (
    FactuurSegment,
    beoordeel_segmenten,
    detecteer_facturen,
    opdracht_met_paginatelling,
    valideer_segmenten,
)


class _NepClient:
    """Speelt Claude na: geeft het opgegeven `facturen`-antwoord terug en onthoudt de opdracht."""

    def __init__(self, facturen: list[dict], *, afgekapt: bool = False) -> None:
        self.facturen = facturen
        self.afgekapt = afgekapt
        self.opdrachten: list[str] = []

    def extraheer_json_uit_pdf(self, *, pdf_bytes, system, opdracht, json_schema, cache_document=False):
        self.opdrachten.append(opdracht)
        assert json_schema is splitsing.SPLITSING_SCHEMA  # prompt-wijziging, géén schema-wijziging
        return ClaudeAntwoord(
            data=None if self.afgekapt else {"facturen": self.facturen},
            afgekapt=self.afgekapt,
            input_tokens=10,
            output_tokens=5,
        )


def _kempen(sp: int, ep: int) -> dict:
    return {
        "sp": sp,
        "ep": ep,
        "ten": "Kempen Facilities B.V.",
        "lev": "Van Happen Containers",
        "nr": "226176996",
        "z": 0.9,
    }


class TestOpdrachtMetPaginatelling:
    def test_een_pagina_benoemt_het_feit_en_sp_ep_1(self) -> None:
        opdracht = opdracht_met_paginatelling(1)
        assert opdracht.startswith(splitsing.OPDRACHT)
        assert "precies 1 pagina" in opdracht
        assert "sp=1 en ep=1" in opdracht

    def test_meerdere_paginas_benoemen_het_bereik(self) -> None:
        opdracht = opdracht_met_paginatelling(3)
        assert "precies 3 pagina's" in opdracht
        assert "1–3" in opdracht

    def test_nul_of_onbekend_wordt_een(self) -> None:
        assert "precies 1 pagina" in opdracht_met_paginatelling(0)


class TestReproductie1PaginaEp2:
    """De productie-casus (diagnose §1.4): 1-pagina-PDF, AI antwoordt sp=1, ep=2 mét correcte
    tenaamstelling. Vóór de fix: AiExtractieFout → verzamelbak zonder tenaamstelling."""

    def test_een_pagina_ep_2_geeft_geldig_voorstel_met_tenaamstelling(self) -> None:
        client = _NepClient([_kempen(1, 2)])
        segmenten = detecteer_facturen(b"%PDF", paginas=1, client=client)
        assert len(segmenten) == 1
        assert segmenten[0].geldig
        assert (segmenten[0].start_pagina, segmenten[0].eind_pagina) == (1, 1)
        assert segmenten[0].tenaamstelling == "Kempen Facilities B.V."
        assert segmenten[0].leverancier == "Van Happen Containers"
        assert segmenten[0].factuurnummer == "226176996"
        # Het pagina-aantal ging als feit mee in de opdracht (bewezen effectief, 3/3).
        assert "precies 1 pagina" in client.opdrachten[0]

    def test_paginabereik_2_2_op_1_pagina_idem(self) -> None:
        segmenten = detecteer_facturen(b"%PDF", paginas=1, client=_NepClient([_kempen(2, 2)]))
        assert [(s.start_pagina, s.eind_pagina, s.geldig) for s in segmenten] == [(1, 1, True)]

    def test_geen_facturen_herkend_blijft_een_fout(self) -> None:
        # Algemene voorwaarden e.d.: terecht geen voorstel — de aanroeper routeert naar de bak.
        with pytest.raises(AiExtractieFout, match="geen facturen herkend"):
            detecteer_facturen(b"%PDF", paginas=8, client=_NepClient([]))

    def test_afgekapt_blijft_een_fout(self) -> None:
        with pytest.raises(AiExtractieFout, match="afgekapt"):
            detecteer_facturen(b"%PDF", paginas=1, client=_NepClient([], afgekapt=True))

    def test_onleesbaar_bereik_blijft_een_fout(self) -> None:
        kapot = {**_kempen(1, 1), "sp": "een"}
        with pytest.raises(AiExtractieFout, match="onleesbaar paginabereik"):
            detecteer_facturen(b"%PDF", paginas=1, client=_NepClient([kapot]))


def _seg(sp: int, ep: int, ten: str | None = "X") -> FactuurSegment:
    return FactuurSegment(sp, ep, ten, None, None, 0.9)


class TestBeoordeelSegmentenProportioneel:
    def test_een_factuur_is_het_hele_document_ongeacht_het_ai_bereik(self) -> None:
        uitkomst = beoordeel_segmenten([_seg(1, 3, "BLOW B.V.")], paginas=2)
        assert [(s.start_pagina, s.eind_pagina) for s in uitkomst.segmenten] == [(1, 2)]
        assert uitkomst.segmenten[0].tenaamstelling == "BLOW B.V."
        assert uitkomst.normalisaties and "genormaliseerd naar 1–2" in uitkomst.normalisaties[0]

    def test_een_factuur_met_correct_bereik_ongewijzigd(self) -> None:
        uitkomst = beoordeel_segmenten([_seg(1, 2)], paginas=2)
        assert uitkomst.normalisaties == []
        assert uitkomst.segmenten == [_seg(1, 2)]

    def test_meerdere_facturen_alleen_het_ongeldige_deel_afgewezen(self) -> None:
        uitkomst = beoordeel_segmenten([_seg(1, 2, "A"), _seg(3, 5, "B"), _seg(6, 6, "C")], paginas=6)
        # Alles geldig: niets gemarkeerd.
        assert uitkomst.ongeldig == []
        uitkomst = beoordeel_segmenten([_seg(1, 2, "A"), _seg(3, 9, "B"), _seg(4, 4, "C")], paginas=4)
        assert [s.geldig for s in uitkomst.segmenten] == [True, False, True]
        assert "3–9 valt buiten het document (4 pagina's)" in (uitkomst.segmenten[1].ongeldig_reden or "")
        # Tenaamstelling van het ongeldige deel blijft bewaard — de mens ziet 'm.
        assert uitkomst.segmenten[1].tenaamstelling == "B"
        assert [s.tenaamstelling for s in uitkomst.geldig] == ["A", "C"]

    def test_omgekeerd_bereik_alleen_dat_deel(self) -> None:
        uitkomst = beoordeel_segmenten([_seg(1, 1), _seg(3, 2)], paginas=3)
        assert [s.geldig for s in uitkomst.segmenten] == [True, False]
        assert "omgekeerd" in (uitkomst.segmenten[1].ongeldig_reden or "")

    def test_overlap_markeert_het_latere_deel(self) -> None:
        uitkomst = beoordeel_segmenten([_seg(1, 2), _seg(2, 3), _seg(4, 4)], paginas=4)
        assert [s.geldig for s in uitkomst.segmenten] == [True, False, True]
        assert "overlapt" in (uitkomst.segmenten[1].ongeldig_reden or "")

    def test_leeg_blijft_leeg(self) -> None:
        assert beoordeel_segmenten([], paginas=1).segmenten == []

    def test_als_dict_draagt_ongeldig_reden(self) -> None:
        deel = beoordeel_segmenten([_seg(1, 1), _seg(5, 5)], paginas=2).segmenten[1]
        assert deel.als_dict()["ongeldig_reden"] == "paginabereik 5–5 valt buiten het document (2 pagina's)"


class TestHardePoortOngewijzigd:
    """`valideer_segmenten` blijft alles-of-niets voor de door de MENS bevestigde bereiken."""

    def test_buiten_document(self) -> None:
        assert valideer_segmenten([_seg(1, 2)], paginas=1) == "paginabereik 1–2 valt buiten het document (1 pagina's)"

    def test_overlap(self) -> None:
        assert (
            valideer_segmenten([_seg(1, 2), _seg(2, 3)], paginas=3)
            == "paginabereiken overlappen of staan niet in volgorde"
        )

    def test_geldig(self) -> None:
        assert valideer_segmenten([_seg(1, 2), _seg(3, 3)], paginas=3) is None
