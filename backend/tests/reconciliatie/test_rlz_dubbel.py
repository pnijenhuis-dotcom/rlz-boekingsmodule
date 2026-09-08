# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok 6 (bundel 08-09): reconciliatie-blok `rlz_dubbel` — periodieke toets "mogelijk dubbel geboekt in RLZ".

Getest zonder RLZ (gemockte client): paginering, matchregel (UITSLUITEND genormaliseerde referentie binnen dezelfde
crediteur — blok 7 herstelrun 08-09: bedrag+datum vervallen, placeholder-referenties matchen nooit), module-herkenning
(beide van de module = geen treffer; GUID-versie-4 nooit van ons), stabiele vingerafdruk per paar, de Kempen-casus
(BOOT 202632703/202632704: twee VERSCHILLENDE referenties — bewust NIET gevangen, aanvaarde grens), het CLI-blok in
een reconciliatie-alles-run (bevindingen, tellers, Odoo overgeslagen, acceptatie via het bestaande pad met bron
`documenten`), de leesbare tekst (geen GUID's in titel/wat/doe) en de kantoorbrede lijst (geen doel_pad, wel
boekstukken in detail)."""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import GebruikerRol
from app.reconciliatie import kantoorbreed, rlz_dubbel, teksten
from app.reconciliatie import run as run_service
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie.rlz_dubbel import (
    REGEL_REFERENTIE,
    RlzDocument,
    is_van_module,
    lees_purchase_invoices,
    naar_rlz_document,
    toets_met_client,
    vind_paren,
)
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

ARGS = argparse.Namespace()
BOOT = uuid.UUID("d51c26fe-0000-4000-8000-00000000b007")
V4_A = uuid.UUID("11111111-1111-4111-8111-111111111111")  # versie 4 → nooit van de module
V4_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
V4_C = uuid.UUID("33333333-3333-4333-8333-333333333333")
V5_MODULE_A = uuid.uuid5(uuid.NAMESPACE_URL, "module-a")
V5_MODULE_B = uuid.uuid5(uuid.NAMESPACE_URL, "module-b")


def _rij(
    rlz_id: uuid.UUID,
    *,
    entity: uuid.UUID | None = BOOT,
    naam: str = "BOOT organiserend ingenieursburo B.V.",
    ref: str | None,
    datum: str = "2026-06-22T00:00:00Z",
    bedrag: float | None = 1234.56,
    boekstuk: str | None = "RLZ-04-00004037",
    status: int = 2,
) -> dict:
    return {
        "id": str(rlz_id),
        "Entity": {"id": str(entity), "Name": naam} if entity else None,
        "Reference": ref,
        "Date": datum,
        "BookDate": datum,
        "BaseInvoiceAmount": bedrag,
        "ReceiptNumber": boekstuk,
        "Status": status,
    }


def _doc(rlz_id: uuid.UUID, **kw) -> RlzDocument:
    module_ids = kw.pop("module_ids", set())
    d = naar_rlz_document(_rij(rlz_id, **kw), module_ids=module_ids)
    assert d is not None
    return d


class _NepClient:
    """Gepagineerde PurchaseInvoices-collectie; registreert élke GET (params) voor de asserts."""

    def __init__(self, rijen: list[dict], *, fout: Exception | None = None) -> None:
        self.rijen = rijen
        self.calls: list[dict] = []
        self.fout = fout

    def get(self, path: str, *, params: dict | None = None) -> dict:
        assert path == "PurchaseInvoices"
        if self.fout is not None:
            raise self.fout
        self.calls.append(dict(params or {}))
        skip = int(params["$skip"])
        top = int(params["$top"])
        return {"value": self.rijen[skip : skip + top]}

    def __enter__(self) -> _NepClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


# ---- lezen ------------------------------------------------------------------------------------------


class TestLezen:
    def test_pagineert_met_top_skip_en_leest_alles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rlz_dubbel, "PAGINA_GROOTTE", 2)
        client = _NepClient([_rij(uuid.uuid4(), ref=str(i)) for i in range(5)])
        uit = lees_purchase_invoices(client, vanaf=date(2025, 8, 4))  # type: ignore[arg-type]
        assert len(uit) == 5
        assert [c["$skip"] for c in client.calls] == ["0", "2", "4"]
        assert client.calls[0]["$filter"] == "Date ge 2025-08-04"
        assert client.calls[0]["$expand"] == "Entity"
        assert "$select" not in client.calls[0]  # niet STAP-0-geverifieerd → bewust weggelaten

    def test_venster_is_400_dagen(self) -> None:
        assert rlz_dubbel.venster_vanaf(date(2026, 9, 8)) == date(2025, 8, 4)

    def test_naar_rlz_document_normaliseert_referentie_en_bedrag_cent_exact(self) -> None:
        d = _doc(V4_A, ref="Factuur nr. 2026-0042", bedrag=7927.8)
        assert d.referentie == "Factuur nr. 2026-0042" and d.referentie_norm == "202642"
        assert d.bedrag == Decimal("7927.80") and isinstance(d.bedrag, Decimal)
        assert d.datum == date(2026, 6, 22) and d.boekstuk == "RLZ-04-00004037" and d.status == 2
        assert d.entity_id == BOOT and d.entity_naam.startswith("BOOT") and d.van_module is False

    def test_rij_zonder_id_wordt_overgeslagen(self) -> None:
        assert naar_rlz_document({"Reference": "x"}, module_ids=set()) is None


# ---- module-herkenning ---------------------------------------------------------------------------------


class TestVanModule:
    def test_versie_4_is_nooit_van_de_module_ook_niet_als_de_set_het_zegt(self) -> None:
        assert is_van_module(V4_A, {V4_A}) is False

    def test_versie_5_alleen_als_de_eigen_db_het_guid_kent(self) -> None:
        assert is_van_module(V5_MODULE_A, {V5_MODULE_A}) is True
        assert is_van_module(V5_MODULE_A, set()) is False


# ---- paren -----------------------------------------------------------------------------------------------


class TestVindParen:
    def test_zelfde_genormaliseerde_referentie_binnen_crediteur_is_paar(self) -> None:
        a = _doc(V4_A, ref="INV 2026-0042", bedrag=100.0, boekstuk="RLZ-04-1")
        b = _doc(V4_B, ref="Factuur 2026-42", bedrag=250.0, datum="2026-07-01T00:00:00Z", boekstuk="RLZ-04-2")
        paren = vind_paren([a, b])
        assert len(paren) == 1
        assert paren[0].regels == (REGEL_REFERENTIE,)
        assert {paren[0].a.rlz_id, paren[0].b.rlz_id} == {V4_A, V4_B}

    def test_gelijk_bedrag_en_datum_zonder_referentiematch_is_geen_paar_meer(self) -> None:
        """Blok 7 (08-09): variant (B) bedrag+datum vervallen — Lusso/Kempen Airco-reeksen (508 ruis-paren)."""
        a = _doc(V4_A, ref="A-1", bedrag=100.0)
        b = _doc(V4_B, ref="B-2", bedrag=100.0)
        assert vind_paren([a, b]) == []

    def test_zelfde_referentie_met_gelijk_bedrag_is_alleen_referentie_regel(self) -> None:
        a = _doc(V4_A, ref="42", bedrag=100.0)
        b = _doc(V4_B, ref="0042", bedrag=100.0)
        (paar,) = vind_paren([a, b])
        assert paar.regels == (REGEL_REFERENTIE,)

    @pytest.mark.parametrize(
        "ref",
        ["Ingescand document", "ingescand  document", "0", "000", "00-00", "Factuur", "invoice", "#", "Scan", "n.v.t."],
    )
    def test_placeholder_referentie_telt_als_leeg_en_matcht_nooit(self, ref: str) -> None:
        assert rlz_dubbel.toetsbare_referentie(ref) is None
        a = _doc(V4_A, ref=ref, bedrag=100.0)
        b = _doc(V4_B, ref=ref, bedrag=100.0)
        assert a.referentie == (ref or None) and a.referentie_norm is None  # de ruwe tekst blijft leesbaar
        assert vind_paren([a, b]) == []

    def test_echte_referentie_met_placeholder_woord_erin_blijft_toetsbaar(self) -> None:
        a = _doc(V4_A, ref="Ingescand document 3")
        b = _doc(V4_B, ref="ingescand document 03")
        (paar,) = vind_paren([a, b])
        assert paar.regels == (REGEL_REFERENTIE,)

    def test_andere_crediteur_is_nooit_een_paar(self) -> None:
        a = _doc(V4_A, ref="42", bedrag=100.0)
        b = _doc(V4_B, ref="42", bedrag=100.0, entity=uuid.uuid4(), naam="Ander")
        assert vind_paren([a, b]) == []

    def test_zonder_crediteur_niet_toetsbaar(self) -> None:
        a = _doc(V4_A, ref="42", entity=None)
        b = _doc(V4_B, ref="42", entity=None)
        assert vind_paren([a, b]) == []

    def test_bedrag_blijft_cent_exact_in_het_detail_maar_stuurt_de_match_niet(self) -> None:
        a = _doc(V4_A, ref="A", bedrag=7927.8)
        b = _doc(V4_B, ref="B", bedrag=7927.80)
        assert a.bedrag == b.bedrag == Decimal("7927.80")
        assert vind_paren([a, b]) == []

    def test_beide_van_de_module_is_geen_treffer(self) -> None:
        module = {V5_MODULE_A, V5_MODULE_B}
        a = _doc(V5_MODULE_A, ref="42", module_ids=module)
        b = _doc(V5_MODULE_B, ref="42", module_ids=module)
        assert a.van_module and b.van_module
        assert vind_paren([a, b]) == []

    def test_een_module_exemplaar_plus_een_handmatig_exemplaar_is_wel_een_treffer(self) -> None:
        a = _doc(V5_MODULE_A, ref="42", module_ids={V5_MODULE_A})
        b = _doc(V4_B, ref="42")
        (paar,) = vind_paren([a, b])
        assert {paar.a.van_module, paar.b.van_module} == {True, False}

    def test_concept_status_1_komt_mee_en_wordt_gemarkeerd(self) -> None:
        a = _doc(V4_A, ref="42")
        b = _doc(V4_B, ref="42", status=1, boekstuk=None)
        (paar,) = vind_paren([a, b])
        assert paar.concept is True and paar.context()["status_b"] == 1

    def test_drie_exemplaren_geven_drie_paren_elk_precies_een_keer(self) -> None:
        docs = [_doc(V4_A, ref="42"), _doc(V4_B, ref="42"), _doc(V4_C, ref="42")]
        paren = vind_paren(docs)
        assert len(paren) == 3
        assert len({(p.a.rlz_id, p.b.rlz_id) for p in paren}) == 3

    def test_vingerafdruk_stabiel_per_paar_ongeacht_volgorde_en_bijzaken(self) -> None:
        """De acceptatie-sleutel (bron|soort|detail) hangt alleen van de twee RLZ-id's af → de delta-motor ziet
        het paar in de volgende run als 'ongewijzigd' (geen tweede mail) en een acceptatie blijft plakken."""
        a = _doc(V4_A, ref="42", boekstuk="RLZ-04-1")
        b = _doc(V4_B, ref="42", boekstuk="RLZ-04-2")
        (p1,) = vind_paren([a, b])
        (p2,) = vind_paren([_doc(V4_B, ref="42", boekstuk="RLZ-04-9", status=1), _doc(V4_A, ref="42")])
        assert p1.detail == p2.detail
        vaf = acceptatie_service.vingerafdruk(bron=rlz_dubbel.ACCEPTATIE_BRON, soort=rlz_dubbel.SOORT, detail=p1.detail)
        assert vaf == acceptatie_service.vingerafdruk(
            bron=rlz_dubbel.ACCEPTATIE_BRON, soort=rlz_dubbel.SOORT, detail=p2.detail
        )
        assert p1.detail == f"rlz_a={min(V4_A, V4_B, key=str)} rlz_b={max(V4_A, V4_B, key=str)}"


class TestKempenCasus:
    """BOOT 202632703 / 202632704 in Kempen Facilities (RLZ-04-00004037/38, handmatig 22-06, GUID-versie 4,
    live 08-09: € 2.976,30 vs € 1.775,98): twee VERSCHILLENDE referenties én verschillende bedragen. Sinds blok 7
    (herstelrun 08-09) toetst het blok alleen op referentie — deze casus wordt BEWUST NIET gevangen (aanvaarde grens,
    Peter 08-09); ook gelijke bedragen maken er geen paar meer van."""

    def _boot(self, bedrag_a: float, bedrag_b: float) -> list[RlzDocument]:
        return [
            _doc(V4_A, ref="202632703", bedrag=bedrag_a, boekstuk="RLZ-04-00004037"),
            _doc(V4_B, ref="202632704", bedrag=bedrag_b, boekstuk="RLZ-04-00004038"),
        ]

    def test_echte_casus_verschillende_bedragen_is_geen_treffer_aanvaarde_grens(self) -> None:
        assert vind_paren(self._boot(2976.30, 1775.98)) == []

    def test_ook_gelijke_bedragen_op_dezelfde_datum_zijn_geen_treffer_meer(self) -> None:
        assert vind_paren(self._boot(1234.56, 1234.56)) == []

    def test_zelfde_boot_referentie_twee_keer_blijft_wel_een_treffer(self) -> None:
        (paar,) = vind_paren(
            [
                _doc(V4_A, ref="202632703", bedrag=2976.30, boekstuk="RLZ-04-00004037"),
                _doc(V4_B, ref="2026-32703", bedrag=2976.30, boekstuk="RLZ-04-00004099"),
            ]
        )
        assert paar.regels == (REGEL_REFERENTIE,)
        ctx = paar.context(administratie_naam="Kempen Facilities B.V.")
        assert ctx["van_module_a"] is False and ctx["van_module_b"] is False


# ---- toets_met_client + rapport -----------------------------------------------------------------------------


class TestToetsMetClient:
    def test_rapport_tellers(self) -> None:
        client = _NepClient(
            [
                _rij(V4_A, ref="42"),
                _rij(V4_B, ref="42"),
                _rij(V5_MODULE_A, ref="99", bedrag=10.0),
                _rij(V4_C, ref="7", entity=None),
            ]
        )
        r = toets_met_client(client, module_ids={V5_MODULE_A}, vandaag=date(2026, 9, 8))  # type: ignore[arg-type]
        assert r.aantal_getoetst == 4 and r.aantal_module == 1 and r.aantal_zonder_crediteur == 1
        assert len(r.paren) == 1 and r.venster_vanaf == date(2025, 8, 4)
        regels = rlz_dubbel.paren_als_tekst(r)
        assert regels[0].startswith("4 inkoopfacturen sinds 2025-08-04 (1 van de module, 1 zonder crediteur) — 1 ")


# ---- CLI-blok binnen reconciliatie-alles ----------------------------------------------------------------------


def _rapport(aid: uuid.UUID, paren) -> rlz_dubbel.RlzDubbelRapport:  # noqa: ANN001
    return rlz_dubbel.RlzDubbelRapport(
        administratie_id=aid,
        aantal_getoetst=12,
        aantal_module=3,
        aantal_zonder_crediteur=0,
        paren=tuple(paren),
        venster_vanaf=date(2025, 8, 4),
    )


class TestCliBlok:
    def test_run_legt_paar_vast_als_afwijking_met_tellers_en_odoo_overgeslagen(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], administratie_id: uuid.UUID
    ) -> None:
        odoo_id = uuid.uuid4()
        (paar,) = vind_paren([_doc(V4_A, ref="42"), _doc(V4_B, ref="42", status=1, boekstuk=None)])
        monkeypatch.setattr(
            rlz_dubbel,
            "toets_alle",
            lambda **kw: rlz_dubbel.RlzDubbelResultaat(
                rapporten={administratie_id: _rapport(administratie_id, [paar])},
                fouten={},
                overgeslagen={odoo_id: "niet van toepassing — backend odoo (dit blok toetst alleen Reeleezee)"},
            ),
        )
        uit: list[str] = []
        code = run_service.voer_uit(
            blokken=[(rlz_dubbel.BLOK, rlz_dubbel.cli_blok)],
            args=ARGS,
            bron="cli",
            stdout=uit.append,
            stderr=uit.append,
        )
        assert code == 1
        # De blokfunctie print zelf (zelfde contract als de bestaande CLI-blokken); de run-callback draagt de
        # run-regels.
        gevangen = capsys.readouterr()
        tekst = "\n".join(uit) + gevangen.out + gevangen.err
        assert f"OVERGESLAGEN {odoo_id}" in tekst
        assert "1 mogelijk dubbel paar/paren (1 open, 0 geaccepteerd)" in tekst
        assert "soort=dubbel_in_rlz" in tekst and "RLZ-04-00004037 + ?" in tekst and "concept" in tekst

        run = run_service.laatste_afgeronde_run()
        assert run is not None
        stand = run.samenvatting[rlz_dubbel.BLOK]
        assert stand["gecontroleerd"] == 12 and stand["afwijkingen"] == 1 and stand["status"] == "actie"
        bevindingen = [b for b in run_service.lees_bevindingen(run.run_id) if b.blok == rlz_dubbel.BLOK]
        assert len(bevindingen) == 1
        b = bevindingen[0]
        assert b.soort == "afwijking" and b.administratie_id == administratie_id
        assert b.detail["bron"] == "documenten" and b.detail["afwijking_soort"] == "dubbel_in_rlz"
        assert b.detail["detail"] == paar.detail and b.detail["record_id"] == str(paar.record_id)
        assert b.detail["boekstuk_a"] == "RLZ-04-00004037" and b.detail["concept"] is True
        assert b.vingerafdruk == acceptatie_service.vingerafdruk(
            bron="documenten", soort="dubbel_in_rlz", detail=paar.detail
        )

    def test_zonder_paren_exit_0_en_ok_regel(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID
    ) -> None:
        monkeypatch.setattr(
            rlz_dubbel,
            "toets_alle",
            lambda **kw: rlz_dubbel.RlzDubbelResultaat(rapporten={administratie_id: _rapport(administratie_id, [])}),
        )
        uit: list[str] = []
        assert rlz_dubbel.cli_blok(ARGS, verzamelaar=None, stdout=uit.append, stderr=uit.append) == 0
        assert any(r.startswith(f"OK         {administratie_id}: 12 inkoopfacturen sinds 2025-08-04") for r in uit)

    def test_administratie_fout_is_zichtbare_fout_bevinding_nooit_stil(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID
    ) -> None:
        monkeypatch.setattr(
            rlz_dubbel,
            "toets_alle",
            lambda **kw: rlz_dubbel.RlzDubbelResultaat(fouten={administratie_id: "RLZ 502 Bad Gateway"}),
        )
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(rlz_dubbel.BLOK)
        uit: list[str] = []
        assert rlz_dubbel.cli_blok(ARGS, verzamelaar=verzamelaar, stdout=uit.append, stderr=uit.append) == 1
        assert [b.soort for b in verzamelaar.bevindingen] == ["fout"]
        assert "RLZ 502 Bad Gateway" in verzamelaar.bevindingen[0].tekst

    def test_geaccepteerd_paar_telt_niet_mee_via_bestaand_acceptatiepad(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        """Acceptatie mét reden via `service.accepteer` (bron `documenten` — DB-CHECK, geen migratie) → de volgende
        run meldt het paar als GEACCEPTEERD en exit 0."""
        (paar,) = vind_paren([_doc(V4_A, ref="42"), _doc(V4_B, ref="42")])
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=rlz_dubbel.ACCEPTATIE_BRON,
            record_id=paar.record_id,
            soort=rlz_dubbel.SOORT,
            detail=paar.detail,
            reden="beoordeeld in RLZ: twee echte facturen, zelfde referentie door leverancier hergebruikt",
            beheerder_id=beheerder_id,
        )
        monkeypatch.setattr(
            rlz_dubbel,
            "toets_alle",
            lambda **kw: rlz_dubbel.RlzDubbelResultaat(
                rapporten={administratie_id: _rapport(administratie_id, [paar])}
            ),
        )
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(rlz_dubbel.BLOK)
        uit: list[str] = []
        assert rlz_dubbel.cli_blok(ARGS, verzamelaar=verzamelaar, stdout=uit.append, stderr=uit.append) == 0
        assert [b.soort for b in verzamelaar.bevindingen] == ["geaccepteerd"]
        assert "GEACCEPTEERD" in verzamelaar.bevindingen[0].tekst and "(0 open, 1 geaccepteerd)" in "\n".join(uit)


# ---- leesbare tekst + kantoorbrede lijst ------------------------------------------------------------------------


class TestTekstEnLijst:
    def _bevinding(self, paar) -> run_service.Bevinding:  # noqa: ANN001
        return run_service.Bevinding(
            blok=rlz_dubbel.BLOK,
            soort="afwijking",
            administratie_id=uuid.uuid4(),
            vingerafdruk="vaf6",
            tekst="AFWIJKING  … soort=dubbel_in_rlz [vaf:vaf6]: RLZ-04-00004037 + RLZ-04-00004038 (referentie)",
            detail={
                "bron": "documenten",
                "record_id": str(paar.record_id),
                "afwijking_soort": rlz_dubbel.SOORT,
                "detail": paar.detail,
                **paar.context(administratie_naam="Kempen Facilities B.V."),
            },
        )

    def test_titel_wat_doe_zonder_guids_met_boekstukken_en_bedragen(self) -> None:
        (paar,) = vind_paren(
            [
                _doc(V4_A, ref="202632703", boekstuk="RLZ-04-00004037", naam="BOOT B.V."),
                _doc(V4_B, ref="2026-32703", boekstuk="RLZ-04-00004038", naam="BOOT B.V."),
            ]
        )
        lb = teksten.leesbaar(self._bevinding(paar))
        assert lb.titel.startswith("Mogelijk dubbel in RLZ — BOOT B.V. · 202632703 / 2026-32703")
        assert len(lb.titel) <= teksten.MAX_TITEL
        assert "RLZ-04-00004037 (22-06-2026, € 1.234,56)" in lb.wat and "RLZ-04-00004038" in lb.wat
        assert "dezelfde referentie 202632703" in lb.wat and "handmatig ingevoerd" in lb.wat
        assert "Open beide boekstuknummers in Reeleezee" in lb.doe and "verwijdert nooit" in lb.doe
        for zin in (lb.titel, lb.wat, lb.doe):
            assert not teksten.bevat_technische_sleutel(zin), zin
        labels = dict(lb.details)
        assert labels["RLZ-document A"] == str(paar.a.rlz_id) and labels["RLZ-document B"] == str(paar.b.rlz_id)
        assert labels["matchregel"] == "referentie"

    def test_geaccepteerd_en_concept_variant(self) -> None:
        (paar,) = vind_paren([_doc(V4_A, ref="42"), _doc(V4_B, ref="42", status=1, boekstuk=None)])
        lb = teksten.leesbaar(self._bevinding(paar), soort="geaccepteerd")
        assert "dezelfde referentie 42" in lb.wat and "nog concept" in lb.wat and "zonder boekstuknummer" in lb.wat
        assert lb.doe.startswith("Beoordeeld en blijvend")

    def test_kantoorbrede_lijst_toont_rij_zonder_doel_pad_met_urgentie_na_verdwenen(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        (paar,) = vind_paren([_doc(V4_A, ref="42"), _doc(V4_B, ref="42")])
        monkeypatch.setattr(
            rlz_dubbel,
            "toets_alle",
            lambda **kw: rlz_dubbel.RlzDubbelResultaat(
                rapporten={administratie_id: _rapport(administratie_id, [paar])}
            ),
        )

        def documenten_blok(args, verzamelaar=None) -> int:  # noqa: ANN001
            verzamelaar.bevinding(
                soort="afwijking",
                administratie_id=administratie_id,
                tekst="AFWIJKING document=x soort=ontbreekt_in_rlz [vaf:z]: 404",
                vingerafdruk="z",
                detail={
                    "bron": "documenten",
                    "record_id": str(uuid.uuid4()),
                    "afwijking_soort": "ontbreekt_in_rlz",
                    "detail": "404",
                },
            )
            return 1

        run_service.voer_uit(
            blokken=[("documenten", documenten_blok), (rlz_dubbel.BLOK, rlz_dubbel.cli_blok)],
            args=ARGS,
            bron="cli",
            stdout=lambda t: None,
            stderr=lambda t: None,
        )
        lijst = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, soort="afwijking")
        rijen = [r for r in lijst.rijen if r.administratie_id == administratie_id]
        assert [r.blok for r in rijen] == ["documenten", rlz_dubbel.BLOK]  # verdwenen document urgenter dan dubbel
        dubbel = rijen[1]
        assert dubbel.doel_pad is None and dubbel.detail["boekstuk_a"] == "RLZ-04-00004037"
        assert dubbel.titel.startswith("Mogelijk dubbel in RLZ") and "Open beide boekstuknummers" in dubbel.doe

        # Accepteren via het bestaande UI-pad (kantoorbreed → service.accepteer, bron uit de bevinding).
        kantoorbreed.accepteer(
            bevinding_id=dubbel.id,
            administratie_id=administratie_id,
            reden="beoordeeld in Reeleezee — twee echte facturen",
            actor_id=beheerder_id,
            rol=GebruikerRol.BEHEERDER,
        )
        na = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, soort="geaccepteerd")
        assert any(r.blok == rlz_dubbel.BLOK and r.administratie_id == administratie_id for r in na.rijen)
