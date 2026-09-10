# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok 6 (bundel 08-09) + blok 1 vervolgrun 10-09 avond: reconciliatie-blok `rlz_dubbel` — periodieke toets "mogelijk
dubbel geboekt in RLZ".

Getest zonder RLZ (gemockte client): paginering, de OUDE paar-meetlat (`vind_paren`, blok 7: alleen referentie,
placeholders nooit), module-herkenning, en sinds 10-09: referentie-classificatie in de clustering (IBAN / klantkenmerk /
placeholder mét tellers), ÉÉN bevinding per cluster (3 documenten = 1 bevinding, niet 3), stabiele cluster-vingerafdruk,
rangorde "Waarschijnlijk dubbel" (6-Steps-casus) vs "Zelfde referentie, controleer", overgang oud → cluster (open
paar-bevindingen vervangen onder eigen vingerafdruk; paar-acceptaties overgedragen, geaccepteerd blijft geaccepteerd,
intrekken wint), de kantoorbrede urgentie en de lees-only CLI-vergelijking paren OUD → clusters NIEUW."""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import cli
from app.db.models import AuditEvent, GebruikerRol
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.reconciliatie import kantoorbreed, rlz_dubbel, teksten
from app.reconciliatie import referentie_classificatie as rc
from app.reconciliatie import run as run_service
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie.models import ReconciliatieAcceptatie
from app.reconciliatie.rlz_dubbel import (
    REGEL_REFERENTIE,
    RlzDocument,
    is_van_module,
    lees_purchase_invoices,
    naar_rlz_document,
    toets_met_client,
    vind_clusters,
    vind_paren,
)
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

ARGS = argparse.Namespace()
BOOT = uuid.UUID("d51c26fe-0000-4000-8000-00000000b007")
STEPS = uuid.UUID("d51c26fe-0000-4000-8000-0000000006e5")
V4_A = uuid.UUID("11111111-1111-4111-8111-111111111111")  # versie 4 → nooit van de module
V4_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
V4_C = uuid.UUID("33333333-3333-4333-8333-333333333333")
V4_D = uuid.UUID("44444444-4444-4444-8444-444444444444")
V5_MODULE_A = uuid.uuid5(uuid.NAMESPACE_URL, "module-a")
V5_MODULE_B = uuid.uuid5(uuid.NAMESPACE_URL, "module-b")
RLZ_ADMIN = "rlz-admin-test"


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


def _vier(n: int) -> uuid.UUID:
    """Versie-4-GUID met een leesbaar volgnummer (nooit van de module)."""
    return uuid.UUID(f"aaaaaaaa-0000-4000-8000-{n:012d}")


def _six_steps() -> list[RlzDocument]:
    """6-Steps Projectbeheersing RLZ-04-00000069/00000072 (productie 10-09): beide concept, zelfde dag, zelfde
    bedrag."""
    return [
        _doc(
            V4_A,
            entity=STEPS,
            naam="6-Steps Projectbeheersing",
            ref="2026-118",
            datum="2026-08-14T00:00:00Z",
            bedrag=1815.0,
            boekstuk="RLZ-04-00000069",
            status=1,
        ),
        _doc(
            V4_B,
            entity=STEPS,
            naam="6-Steps Projectbeheersing",
            ref="2026-118",
            datum="2026-08-14T00:00:00Z",
            bedrag=1815.0,
            boekstuk="RLZ-04-00000072",
            status=1,
        ),
    ]


def _bp_express() -> list[RlzDocument]:
    """BP Express: klantnummer 0817725528 op 7 bank-directe boekingen, verschillende data en bedragen (21 oude
    paren)."""
    bedragen = (81.20, 94.15, 81.20, 120.00, 77.35, 94.15, 60.10)
    return [
        _doc(
            _vier(i),
            entity=uuid.UUID(int=0xB9),
            naam="BP Express",
            ref="0817725528",
            datum=f"2026-0{1 + i % 7}-0{1 + i}T00:00:00Z",
            bedrag=b,
            boekstuk=f"RLZ-02-{i:08d}",
        )
        for i, b in enumerate(bedragen, start=1)
    ]


def _food_service() -> list[RlzDocument]:
    """Food service: eigen IBAN als referentie op 4 boekingen (6 oude paren)."""
    return [
        _doc(
            _vier(10 + i),
            entity=uuid.UUID(int=0xF0),
            naam="Food service",
            ref="NL86INGB0662462785",
            datum=f"2026-0{i}-15T00:00:00Z",
            bedrag=100.0 + i,
            boekstuk=f"RLZ-02-{10 + i:08d}",
        )
        for i in range(1, 5)
    ]


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


def _cluster_vaf(cluster: rlz_dubbel.DubbelCluster) -> str:
    return acceptatie_service.vingerafdruk(
        bron=rlz_dubbel.ACCEPTATIE_BRON, soort=rlz_dubbel.SOORT, detail=cluster.detail
    )


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


# ---- paren (OUDE meetlat) -------------------------------------------------------------------------------


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

    def test_andere_crediteur_of_geen_crediteur_is_nooit_een_paar(self) -> None:
        assert vind_paren([_doc(V4_A, ref="42"), _doc(V4_B, ref="42", entity=uuid.uuid4(), naam="Ander")]) == []
        assert vind_paren([_doc(V4_A, ref="42", entity=None), _doc(V4_B, ref="42", entity=None)]) == []

    def test_beide_van_de_module_is_geen_treffer(self) -> None:
        module = {V5_MODULE_A, V5_MODULE_B}
        assert (
            vind_paren([_doc(V5_MODULE_A, ref="42", module_ids=module), _doc(V5_MODULE_B, ref="42", module_ids=module)])
            == []
        )

    def test_drie_exemplaren_geven_drie_paren_oude_meetlat(self) -> None:
        """De OUDE meetlat telt paren (3 documenten = 3 paren); de bevinding-eenheid is sinds 10-09 het cluster."""
        docs = [_doc(V4_A, ref="42"), _doc(V4_B, ref="42"), _doc(V4_C, ref="42")]
        assert len(vind_paren(docs)) == 3
        assert len(vind_clusters(docs).clusters) == 1


class TestKempenCasus:
    """BOOT 202632703 / 202632704 (RLZ-04-00004037/38): twee VERSCHILLENDE referenties én bedragen — aanvaarde grens."""

    def _boot(self, bedrag_a: float, bedrag_b: float) -> list[RlzDocument]:
        return [
            _doc(V4_A, ref="202632703", bedrag=bedrag_a, boekstuk="RLZ-04-00004037"),
            _doc(V4_B, ref="202632704", bedrag=bedrag_b, boekstuk="RLZ-04-00004038"),
        ]

    def test_echte_casus_is_geen_treffer_ook_niet_als_cluster(self) -> None:
        assert vind_paren(self._boot(2976.30, 1775.98)) == []
        assert vind_clusters(self._boot(1234.56, 1234.56)).clusters == ()

    def test_zelfde_boot_referentie_twee_keer_blijft_wel_een_treffer(self) -> None:
        uitkomst = vind_clusters(
            [
                _doc(V4_A, ref="202632703", bedrag=2976.30, boekstuk="RLZ-04-00004037"),
                _doc(V4_B, ref="2026-32703", bedrag=2976.30, boekstuk="RLZ-04-00004099"),
            ]
        )
        (cluster,) = uitkomst.clusters
        assert cluster.aantal_module == 0 and cluster.waarschijnlijk_dubbel is False  # geboekt, geen concept


# ---- clusters + classificatie (puur) ----------------------------------------------------------------------


class TestVindClusters:
    def test_drie_documenten_is_een_cluster_gesorteerd_op_datum(self) -> None:
        docs = [
            _doc(V4_B, ref="42", datum="2026-07-01T00:00:00Z", boekstuk="RLZ-04-2"),
            _doc(V4_C, ref="0042", datum="2026-08-01T00:00:00Z", boekstuk="RLZ-04-3"),
            _doc(V4_A, ref="Factuur 42", datum="2026-06-01T00:00:00Z", boekstuk="RLZ-04-1"),
        ]
        uitkomst = vind_clusters(docs, rlz_admin_id=RLZ_ADMIN)
        assert len(uitkomst.clusters) == 1 and uitkomst.uitgesloten == ()
        (c,) = uitkomst.clusters
        assert [d.boekstuk for d in c.documenten] == ["RLZ-04-1", "RLZ-04-2", "RLZ-04-3"]
        assert c.referentie_norm == "42" and c.entity_id == BOOT and c.rlz_ids == {V4_A, V4_B, V4_C}
        assert c.sleutel == f"cluster={RLZ_ADMIN}|{BOOT}|42" and c.detail == c.sleutel
        ctx = c.context(administratie_naam="Kempen Facilities B.V.")
        assert ctx["boekstukken"] == ["RLZ-04-1", "RLZ-04-2", "RLZ-04-3"] and ctx["aantal_exemplaren"] == 3
        assert ctx["boekstuk_a"] == "RLZ-04-1" and ctx["boekstuk_b"] == "RLZ-04-2"  # terugval-velden
        assert len(ctx["exemplaren"]) == 3 and ctx["exemplaren"][2]["rlz_id"] == str(V4_C)

    def test_vingerafdruk_en_record_id_stabiel_ongeacht_volgorde_boekstuk_en_extra_exemplaar(self) -> None:
        a = _doc(V4_A, ref="42", boekstuk="RLZ-04-1")
        b = _doc(V4_B, ref="42", boekstuk="RLZ-04-2")
        (c1,) = vind_clusters([a, b], rlz_admin_id=RLZ_ADMIN).clusters
        (c2,) = vind_clusters(
            [_doc(V4_B, ref="0042", boekstuk="RLZ-04-9", status=1), a], rlz_admin_id=RLZ_ADMIN
        ).clusters
        (c3,) = vind_clusters([a, b, _doc(V4_C, ref="42")], rlz_admin_id=RLZ_ADMIN).clusters
        assert c1.detail == c2.detail == c3.detail and c1.record_id == c2.record_id == c3.record_id
        assert _cluster_vaf(c1) == _cluster_vaf(c2) == _cluster_vaf(c3)
        assert c1.record_id.version == 5
        # Andere administratie of andere crediteur = andere sleutel.
        (c4,) = vind_clusters([a, b], rlz_admin_id="andere-admin").clusters
        assert c4.detail != c1.detail

    def test_alle_van_de_module_is_geen_cluster_een_handmatig_exemplaar_wel(self) -> None:
        module = {V5_MODULE_A, V5_MODULE_B}
        beide = [_doc(V5_MODULE_A, ref="42", module_ids=module), _doc(V5_MODULE_B, ref="42", module_ids=module)]
        assert vind_clusters(beide).clusters == () and vind_clusters(beide).uitgesloten == ()
        (c,) = vind_clusters([*beide, _doc(V4_C, ref="42")]).clusters
        assert len(c.documenten) == 3 and c.aantal_module == 2

    def test_six_steps_casus_is_waarschijnlijk_dubbel(self) -> None:
        (c,) = vind_clusters(_six_steps(), rlz_admin_id=RLZ_ADMIN).clusters
        assert c.waarschijnlijk_dubbel is True and c.concept is True
        assert [d.boekstuk for d in c.documenten] == ["RLZ-04-00000069", "RLZ-04-00000072"]
        assert c.context()["waarschijnlijk_dubbel"] is True

    def test_concepten_met_ander_bedrag_of_andere_datum_zijn_alleen_controleer(self) -> None:
        a, b = _six_steps()
        ander_bedrag = RlzDocument(**{**b.__dict__, "bedrag": Decimal("1816.00")})
        (c,) = vind_clusters([a, ander_bedrag]).clusters
        assert c.waarschijnlijk_dubbel is False
        geboekt = RlzDocument(**{**b.__dict__, "status": 2})
        (c2,) = vind_clusters([a, geboekt]).clusters
        assert c2.waarschijnlijk_dubbel is False and c2.concept is True

    def test_bp_express_klantnummer_is_uitgesloten_als_klantkenmerk(self) -> None:
        uitkomst = vind_clusters(_bp_express(), rlz_admin_id=RLZ_ADMIN)
        assert uitkomst.clusters == ()
        (g,) = uitkomst.uitgesloten
        assert g.reden == rc.REDEN_KLANTKENMERK and g.aantal_documenten == 7 and g.aantal_bedragen == 5
        assert g.referentie == "0817725528" and g.entity_naam == "BP Express"
        assert uitkomst.tellers()[rc.REDEN_KLANTKENMERK] == {"groepen": 1, "documenten": 7}
        assert len(vind_paren(_bp_express())) == 21  # de oude meetlat: 21 paren

    def test_food_service_iban_referentie_is_uitgesloten(self) -> None:
        uitkomst = vind_clusters(_food_service())
        assert uitkomst.clusters == ()
        (g,) = uitkomst.uitgesloten
        assert g.reden == rc.REDEN_IBAN and g.aantal_documenten == 4
        assert len(vind_paren(_food_service())) == 6

    def test_iban_met_spaties_ook_uitgesloten_ook_bij_twee_exemplaren(self) -> None:
        docs = [
            _doc(V4_A, ref="NL86 INGB 0662 4627 85", bedrag=10.0),
            _doc(V4_B, ref="nl86 ingb 0662 4627 85", bedrag=10.0),
        ]
        assert docs[0].referentie_norm == docs[1].referentie_norm == "nl86ingb662462785"  # voorloopnul per groep weg
        uitkomst = vind_clusters(docs)
        assert uitkomst.clusters == () and uitkomst.uitgesloten[0].reden == rc.REDEN_IBAN

    def test_iban_met_en_zonder_spaties_normaliseert_verschillend_en_geeft_nooit_een_cluster(self) -> None:
        """`normaliseer_referentie` haalt voorloopnullen alleen per cijfergroep weg: 'NL86INGB0662462785' (één token)
        ≠ 'NL86 INGB 0662 4627 85' → twee groepen van één → geen cluster, geen uitsluiting (niets te melden)."""
        docs = [
            _doc(V4_A, ref="NL86 INGB 0662 4627 85", bedrag=10.0),
            _doc(V4_B, ref="NL86INGB0662462785", bedrag=10.0),
        ]
        assert docs[0].referentie_norm != docs[1].referentie_norm
        uitkomst = vind_clusters(docs)
        assert uitkomst.clusters == () and uitkomst.uitgesloten == ()

    def test_precies_drie_met_een_bedrag_blijft_cluster(self) -> None:
        docs = [_doc(_vier(i), ref="777", bedrag=50.0, boekstuk=f"RLZ-{i}") for i in range(1, 4)]
        uitkomst = vind_clusters(docs)
        assert len(uitkomst.clusters) == 1 and uitkomst.uitgesloten == ()

    def test_twee_met_twee_bedragen_blijft_cluster(self) -> None:
        docs = [_doc(V4_A, ref="777", bedrag=50.0), _doc(V4_B, ref="777", bedrag=60.0)]
        assert len(vind_clusters(docs).clusters) == 1

    def test_placeholder_groep_telt_als_uitgesloten_placeholder(self) -> None:
        docs = [_doc(V4_A, ref="Ingescand document", bedrag=1.0), _doc(V4_B, ref="ingescand  document", bedrag=2.0)]
        uitkomst = vind_clusters(docs)
        assert uitkomst.clusters == ()
        (g,) = uitkomst.uitgesloten
        assert g.reden == rc.REDEN_PLACEHOLDER and g.aantal_documenten == 2 and g.referentie_norm is None
        assert uitkomst.tellers()[rc.REDEN_PLACEHOLDER] == {"groepen": 1, "documenten": 2}

    def test_tellers_dragen_alle_redenen_ook_bij_nul(self) -> None:
        t = vind_clusters([]).tellers()
        assert set(t) == set(rc.UITSLUITINGSREDENEN) and all(v == {"groepen": 0, "documenten": 0} for v in t.values())

    def test_productie_beeld_10_09_van_28_paren_naar_1_cluster(self) -> None:
        """BP Express (21 paren) + Food service (6 paren) + 6-Steps (1 paar) → 1 cluster, waarschijnlijk dubbel."""
        docs = [*_bp_express(), *_food_service(), *_six_steps()]
        assert len(vind_paren(docs)) == 28
        uitkomst = vind_clusters(docs, rlz_admin_id=RLZ_ADMIN)
        assert len(uitkomst.clusters) == 1 and uitkomst.clusters[0].waarschijnlijk_dubbel
        assert {g.reden for g in uitkomst.uitgesloten} == {rc.REDEN_IBAN, rc.REDEN_KLANTKENMERK}


# ---- toets_met_client + rapport -----------------------------------------------------------------------------


class TestToetsMetClient:
    def test_rapport_tellers_clusters_paren_en_uitsluitingen(self) -> None:
        client = _NepClient(
            [
                _rij(V4_A, ref="42"),
                _rij(V4_B, ref="42"),
                _rij(V5_MODULE_A, ref="99", bedrag=10.0),
                _rij(V4_C, ref="7", entity=None),
                *[
                    _rij(d.rlz_id, entity=d.entity_id, naam="Food service", ref=d.referentie, bedrag=float(d.bedrag))
                    for d in _food_service()
                ],
            ]
        )
        r = toets_met_client(client, module_ids={V5_MODULE_A}, vandaag=date(2026, 9, 8), rlz_admin_id=RLZ_ADMIN)  # type: ignore[arg-type]
        assert r.aantal_getoetst == 8 and r.aantal_module == 1 and r.aantal_zonder_crediteur == 1
        assert len(r.paren) == 7 and len(r.clusters) == 1 and r.venster_vanaf == date(2025, 8, 4)
        assert r.clusters[0].rlz_admin_id == RLZ_ADMIN
        assert r.uitsluiting_tellers()[rc.REDEN_IBAN] == {"groepen": 1, "documenten": 4}
        regels = rlz_dubbel.paren_als_tekst(r)
        assert regels[0].startswith(
            "8 inkoopfacturen sinds 2025-08-04 (1 van de module, 1 zonder crediteur) — 1 cluster(s) (paren OUD: 7)"
        )
        assert any("uitgesloten (iban): Food service" in x for x in regels)


# ---- CLI-blok binnen reconciliatie-alles ----------------------------------------------------------------------


def _rapport(aid: uuid.UUID, documenten, *, rlz_admin_id: str = RLZ_ADMIN) -> rlz_dubbel.RlzDubbelRapport:  # noqa: ANN001
    uitkomst = vind_clusters(documenten, rlz_admin_id=rlz_admin_id)
    return rlz_dubbel.RlzDubbelRapport(
        administratie_id=aid,
        aantal_getoetst=12,
        aantal_module=3,
        aantal_zonder_crediteur=0,
        paren=tuple(vind_paren(documenten)),
        venster_vanaf=date(2025, 8, 4),
        clusters=uitkomst.clusters,
        uitgesloten=uitkomst.uitgesloten,
        rlz_admin_id=rlz_admin_id,
    )


def _stub_toets(monkeypatch: pytest.MonkeyPatch, aid: uuid.UUID, documenten, **extra) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        rlz_dubbel,
        "toets_alle",
        lambda **kw: rlz_dubbel.RlzDubbelResultaat(rapporten={aid: _rapport(aid, documenten)}, **extra),
    )


def _voer_uit(extra_blokken=()) -> tuple[int, str]:  # noqa: ANN001
    uit: list[str] = []
    code = run_service.voer_uit(
        blokken=[*extra_blokken, (rlz_dubbel.BLOK, rlz_dubbel.cli_blok)],
        args=ARGS,
        bron="cli",
        stdout=uit.append,
        stderr=uit.append,
    )
    return code, "\n".join(uit)


def _oud_paar_blok(paar: rlz_dubbel.DubbelPaar, aid: uuid.UUID):  # noqa: ANN001, ANN202
    """Speelt een run van vóór 10-09 na: één paar-bevinding in de oude vorm (detail rlz_id_a/rlz_id_b, eigen vaf)."""

    def blok(args, verzamelaar=None, **kw) -> int:  # noqa: ANN001
        vaf = acceptatie_service.vingerafdruk(
            bron=rlz_dubbel.ACCEPTATIE_BRON, soort=rlz_dubbel.SOORT, detail=paar.detail
        )
        verzamelaar.bevinding(
            soort="afwijking",
            administratie_id=aid,
            tekst=f"AFWIJKING  {aid} {paar.detail} soort=dubbel_in_rlz [vaf:{vaf}]: "
            f"{paar.a.boekstuk} + {paar.b.boekstuk} (referentie)",
            vingerafdruk=vaf,
            detail={
                "bron": rlz_dubbel.ACCEPTATIE_BRON,
                "record_id": str(paar.record_id),
                "afwijking_soort": rlz_dubbel.SOORT,
                "detail": paar.detail,
                **paar.context(administratie_naam="Scope-test", rlz_admin_id=RLZ_ADMIN),
            },
            blok=rlz_dubbel.BLOK,
        )
        return 1

    return blok


class TestCliBlok:
    def test_run_legt_cluster_vast_als_een_afwijking_met_tellers_en_odoo_overgeslagen(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], administratie_id: uuid.UUID
    ) -> None:
        odoo_id = uuid.uuid4()
        docs = [
            _doc(V4_A, ref="42"),
            _doc(V4_B, ref="42", status=1, boekstuk=None),
            _doc(V4_C, ref="42", boekstuk="RLZ-04-3"),
            *_bp_express(),
        ]
        _stub_toets(
            monkeypatch,
            administratie_id,
            docs,
            overgeslagen={odoo_id: "niet van toepassing — backend odoo (dit blok toetst alleen Reeleezee)"},
        )
        code, tekst = _voer_uit()
        gevangen = capsys.readouterr()
        tekst += gevangen.out + gevangen.err
        assert code == 1
        assert f"OVERGESLAGEN {odoo_id}" in tekst
        assert "1 cluster(s) met dezelfde referentie (0 waarschijnlijk dubbel; 1 open, 0 geaccepteerd)" in tekst
        assert "uitgesloten: klantkenmerk 1 groep(en)/7 doc" in tekst
        assert (
            "soort=dubbel_in_rlz" in tekst
            and "? + RLZ-04-00004037 + RLZ-04-3" in tekst
            and "3 exemplaren, concept" in tekst
        )

        run = run_service.laatste_afgeronde_run()
        assert run is not None
        stand = run.samenvatting[rlz_dubbel.BLOK]
        assert stand["gecontroleerd"] == 12 and stand["afwijkingen"] == 1 and stand["status"] == "actie"
        bevindingen = [b for b in run_service.lees_bevindingen(run.run_id) if b.blok == rlz_dubbel.BLOK]
        assert len(bevindingen) == 1  # 3 documenten (3 oude paren) = 1 bevinding
        b = bevindingen[0]
        (cluster,) = vind_clusters(docs, rlz_admin_id=RLZ_ADMIN).clusters
        assert b.soort == "afwijking" and b.administratie_id == administratie_id
        assert b.detail["bron"] == "documenten" and b.detail["afwijking_soort"] == "dubbel_in_rlz"
        assert b.detail["detail"] == cluster.detail and b.detail["record_id"] == str(cluster.record_id)
        assert b.detail["boekstukken"] == ["RLZ-04-00004037", "RLZ-04-3"] and b.detail["aantal_exemplaren"] == 3
        assert b.detail["concept"] is True and b.detail["waarschijnlijk_dubbel"] is False
        assert b.vingerafdruk == _cluster_vaf(cluster)

    def test_zonder_clusters_exit_0_en_ok_regel_met_uitsluitingstellers(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID
    ) -> None:
        _stub_toets(monkeypatch, administratie_id, _food_service())
        uit: list[str] = []
        assert rlz_dubbel.cli_blok(ARGS, verzamelaar=None, stdout=uit.append, stderr=uit.append) == 0
        ok = [r for r in uit if r.startswith(f"OK         {administratie_id}: 12 inkoopfacturen sinds 2025-08-04")]
        assert ok and "uitgesloten: iban 1 groep(en)/4 doc" in ok[0]

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

    def test_geaccepteerd_cluster_telt_niet_mee_via_bestaand_acceptatiepad(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        docs = [_doc(V4_A, ref="42"), _doc(V4_B, ref="42")]
        (cluster,) = vind_clusters(docs, rlz_admin_id=RLZ_ADMIN).clusters
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=rlz_dubbel.ACCEPTATIE_BRON,
            record_id=cluster.record_id,
            soort=rlz_dubbel.SOORT,
            detail=cluster.detail,
            reden="beoordeeld in RLZ: twee echte facturen, zelfde referentie door leverancier hergebruikt",
            beheerder_id=beheerder_id,
        )
        _stub_toets(monkeypatch, administratie_id, docs)
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(rlz_dubbel.BLOK)
        uit: list[str] = []
        assert rlz_dubbel.cli_blok(ARGS, verzamelaar=verzamelaar, stdout=uit.append, stderr=uit.append) == 0
        assert [b.soort for b in verzamelaar.bevindingen] == ["geaccepteerd"]
        assert "GEACCEPTEERD" in verzamelaar.bevindingen[0].tekst and "(0 open, 1 geaccepteerd)" in "\n".join(uit)


# ---- overgang oud → cluster --------------------------------------------------------------------------------------


class TestOvergangPaarNaarCluster:
    def test_open_paar_bevindingen_worden_vervangen_onder_eigen_vingerafdruk_geen_verdwenen(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], administratie_id: uuid.UUID
    ) -> None:
        """Run 1 (oude vorm): paar-bevinding A+B én paar-bevinding uit een BP-Express-groep. Run 2 (cluster): beide
        oude vingerafdrukken komen terug als `uitgesloten` met reden — de delta ziet geen 'verdwenen', de lijst geen
        open paar meer; het cluster is de enige afwijking."""
        docs = [_doc(V4_A, ref="42"), _doc(V4_B, ref="42"), *_bp_express()]
        (paar_ab,) = vind_paren(docs[:2])
        paar_bp = vind_paren(_bp_express())[0]
        _stub_toets(monkeypatch, administratie_id, [])  # run 1: het blok zelf meldt niets
        code1, _ = _voer_uit(
            extra_blokken=[
                ("oud_a", _oud_paar_blok(paar_ab, administratie_id)),
                ("oud_b", _oud_paar_blok(paar_bp, administratie_id)),
            ]
        )
        assert code1 == 1
        run1 = run_service.laatste_afgeronde_run()
        assert run1 is not None
        oude = run_service.lees_bevindingen(run1.run_id, administratie_ids=[administratie_id])
        assert len(oude) == 2

        _stub_toets(monkeypatch, administratie_id, docs)
        capsys.readouterr()
        code2, tekst = _voer_uit()
        tekst += capsys.readouterr().out  # de blokfunctie print zelf (voer_uit geeft stdout niet door)
        assert code2 == 1
        run2 = run_service.laatste_afgeronde_run()
        assert run2 is not None and run2.run_id != run1.run_id
        nieuwe = [
            b
            for b in run_service.lees_bevindingen(run2.run_id, administratie_ids=[administratie_id])
            if b.blok == rlz_dubbel.BLOK
        ]
        per_soort = {}
        for b in nieuwe:
            per_soort.setdefault(b.soort, []).append(b)
        assert len(per_soort["afwijking"]) == 1 and len(per_soort["uitgesloten"]) == 2
        (cluster,) = vind_clusters(docs, rlz_admin_id=RLZ_ADMIN).clusters
        vervangen = {b.vingerafdruk: b for b in per_soort["uitgesloten"]}
        vaf_ab = acceptatie_service.vingerafdruk(bron="documenten", soort=rlz_dubbel.SOORT, detail=paar_ab.detail)
        vaf_bp = acceptatie_service.vingerafdruk(bron="documenten", soort=rlz_dubbel.SOORT, detail=paar_bp.detail)
        assert set(vervangen) == {vaf_ab, vaf_bp}
        assert vervangen[vaf_ab].detail["uitsluiting"] == f"vervangen door cluster [vaf:{_cluster_vaf(cluster)}]"
        assert vervangen[vaf_ab].detail["vervangen_door_vingerafdruk"] == _cluster_vaf(cluster)
        assert vervangen[vaf_bp].detail["uitsluiting"].startswith("referentie uitgesloten (klant-/contractnummer")
        assert vervangen[vaf_bp].detail["vervangen_door_vingerafdruk"] is None
        assert "2 paar-bevinding(en) uit de vorige run vervangen" in tekst

        # Delta: de oude vingerafdrukken staan in de huidige run → geen 'verdwenen'; het cluster is nieuw.
        delta = run_service.bepaal_delta(huidig=nieuwe, vorig=[b for b in oude], gezien=set(), samenvatting={})
        assert delta.verdwenen_afwijkingen == [] and len(delta.nieuwe_afwijkingen) == 1
        # Lijst: alleen het cluster als afwijking; de vervangen paren onder 'uitgesloten' met leesbare tekst.
        lees = teksten.leesbaar(vervangen[vaf_ab], administratie_naam="Scope-test")
        assert lees.titel.startswith("Uitgesloten van controle") and "vervangen door cluster" in lees.wat
        assert not teksten.bevat_technische_sleutel(lees.titel)

        # Run 3: geen open paar-bevindingen meer in de vorige run → niets te vervangen, tussenstand weg.
        code3, tekst3 = _voer_uit()
        tekst3 += capsys.readouterr().out
        run3 = run_service.laatste_afgeronde_run()
        soorten3 = [
            b.soort
            for b in run_service.lees_bevindingen(run3.run_id, administratie_ids=[administratie_id])
            if b.blok == rlz_dubbel.BLOK
        ]
        assert soorten3 == ["afwijking"] and "vervangen" not in tekst3

    def test_paar_waarvan_een_document_verdween_wordt_niet_vervangen(self) -> None:
        docs = [_doc(V4_A, ref="42"), _doc(V4_B, ref="42")]
        (paar,) = vind_paren(docs)
        uitkomst = vind_clusters([docs[0], _doc(V4_C, ref="42")])  # B is weg, C kwam erbij
        vorige = [
            run_service.Bevinding(
                blok=rlz_dubbel.BLOK,
                soort="afwijking",
                administratie_id=uuid.uuid4(),
                vingerafdruk="oud",
                tekst="",
                detail={"rlz_id_a": str(paar.a.rlz_id), "rlz_id_b": str(paar.b.rlz_id)},
            )
        ]
        assert (
            rlz_dubbel.vervang_paar_bevindingen(
                vorige=vorige, clusters=uitkomst.clusters, uitgesloten=uitkomst.uitgesloten
            )
            == []
        )

    def test_paar_acceptatie_wordt_eenmalig_op_het_cluster_overgedragen_met_audit(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        docs = [_doc(V4_A, ref="42", boekstuk="RLZ-04-1"), _doc(V4_B, ref="42", boekstuk="RLZ-04-2")]
        (paar,) = vind_paren(docs)
        (cluster,) = vind_clusters(docs, rlz_admin_id=RLZ_ADMIN).clusters
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=rlz_dubbel.ACCEPTATIE_BRON,
            record_id=paar.record_id,
            soort=rlz_dubbel.SOORT,
            detail=paar.detail,
            reden="beoordeeld in RLZ: twee echte facturen",
            beheerder_id=beheerder_id,
        )
        _stub_toets(monkeypatch, administratie_id, docs)
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(rlz_dubbel.BLOK)
        uit: list[str] = []
        assert rlz_dubbel.cli_blok(ARGS, verzamelaar=verzamelaar, stdout=uit.append, stderr=uit.append) == 0
        assert [b.soort for b in verzamelaar.bevindingen] == ["geaccepteerd"]
        assert any("acceptatie overgedragen op cluster" in r for r in uit)
        with scoped_session(administratie_id) as session:
            rijen = session.scalars(
                select(ReconciliatieAcceptatie).where(ReconciliatieAcceptatie.administratie_id == administratie_id)
            ).all()
            per_detail = {r.detail: r for r in rijen}
            assert set(per_detail) == {paar.detail, cluster.detail}
            nieuw = per_detail[cluster.detail]
            assert nieuw.geaccepteerd_door == beheerder_id and nieuw.ingetrokken_op is None
            assert nieuw.reden.startswith(
                "beoordeeld in RLZ: twee echte facturen (overgenomen van paar-acceptatie RLZ-04-1 + RLZ-04-2"
            )
            assert nieuw.vingerafdruk == _cluster_vaf(cluster) and nieuw.record_id == cluster.record_id
            assert per_detail[paar.detail].ingetrokken_op is None  # historisch spoor blijft staan
            audit = session.scalars(
                select(AuditEvent).where(AuditEvent.actie == "reconciliatie_acceptatie_overgedragen")
            ).all()
            assert len(audit) == 1 and audit[0].actor_id == SYSTEEM_ACTOR_ID
            assert audit[0].nieuwe_waarde["vingerafdruk"] == _cluster_vaf(cluster)
        # Tweede run: idempotent (geen tweede rij, geen tweede audit).
        verzamelaar2 = run_service.Verzamelaar()
        verzamelaar2.start_blok(rlz_dubbel.BLOK)
        assert rlz_dubbel.cli_blok(ARGS, verzamelaar=verzamelaar2, stdout=lambda t: None, stderr=lambda t: None) == 0
        with scoped_session(administratie_id) as session:
            assert (
                len(
                    session.scalars(
                        select(ReconciliatieAcceptatie).where(
                            ReconciliatieAcceptatie.administratie_id == administratie_id
                        )
                    ).all()
                )
                == 2
            )
            assert (
                len(
                    session.scalars(
                        select(AuditEvent).where(AuditEvent.actie == "reconciliatie_acceptatie_overgedragen")
                    ).all()
                )
                == 1
            )

    def test_ingetrokken_cluster_acceptatie_wordt_niet_opnieuw_overgedragen(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        docs = [_doc(V4_A, ref="42"), _doc(V4_B, ref="42")]
        (paar,) = vind_paren(docs)
        (cluster,) = vind_clusters(docs, rlz_admin_id=RLZ_ADMIN).clusters
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron="documenten",
            record_id=paar.record_id,
            soort=rlz_dubbel.SOORT,
            detail=paar.detail,
            reden="twee echte facturen",
            beheerder_id=beheerder_id,
        )
        _stub_toets(monkeypatch, administratie_id, docs)
        assert rlz_dubbel.cli_blok(ARGS, verzamelaar=None, stdout=lambda t: None, stderr=lambda t: None) == 0
        acceptatie_service.trek_in(
            administratie_id=administratie_id,
            bron="documenten",
            vingerafdruk_waarde=_cluster_vaf(cluster),
            reden="toch dubbel — Beheerder wint",
            beheerder_id=beheerder_id,
        )
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(rlz_dubbel.BLOK)
        assert rlz_dubbel.cli_blok(ARGS, verzamelaar=verzamelaar, stdout=lambda t: None, stderr=lambda t: None) == 1
        assert [b.soort for b in verzamelaar.bevindingen] == ["afwijking"]

    def test_deels_gedekt_cluster_blijft_open_met_verwijzing(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        """Paar A+B geaccepteerd; nu is er ook C op dezelfde referentie → het cluster blijft OPEN (niets verdwijnt
        stil),
        de tekst noemt het eerder geaccepteerde paar én het nieuwe exemplaar."""
        docs = [_doc(V4_A, ref="42", boekstuk="RLZ-04-1"), _doc(V4_B, ref="42", boekstuk="RLZ-04-2")]
        (paar,) = vind_paren(docs)
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron="documenten",
            record_id=paar.record_id,
            soort=rlz_dubbel.SOORT,
            detail=paar.detail,
            reden="twee echte facturen",
            beheerder_id=beheerder_id,
        )
        drie = [*docs, _doc(V4_C, ref="42", boekstuk="RLZ-04-3", datum="2026-09-01T00:00:00Z")]
        _stub_toets(monkeypatch, administratie_id, drie)
        verzamelaar = run_service.Verzamelaar()
        verzamelaar.start_blok(rlz_dubbel.BLOK)
        assert rlz_dubbel.cli_blok(ARGS, verzamelaar=verzamelaar, stdout=lambda t: None, stderr=lambda t: None) == 1
        (b,) = verzamelaar.bevindingen
        assert b.soort == "afwijking" and b.detail["acceptatie_gedeeltelijk"] == ["RLZ-04-3"]
        lees = teksten.leesbaar(b)
        assert "eerder geaccepteerd paar" in lees.wat and "RLZ-04-3 is/zijn nieuw" in lees.wat
        with scoped_session(administratie_id) as session:
            assert (
                len(
                    session.scalars(
                        select(ReconciliatieAcceptatie).where(
                            ReconciliatieAcceptatie.administratie_id == administratie_id
                        )
                    ).all()
                )
                == 1
            )

    def test_paar_ids_uit_detail(self) -> None:
        assert rlz_dubbel.paar_ids_uit_detail(f"rlz_a={V4_A} rlz_b={V4_B}") == frozenset({V4_A, V4_B})
        assert rlz_dubbel.paar_ids_uit_detail("cluster=x|y|z") is None
        assert rlz_dubbel.paar_ids_uit_detail(None) is None


# ---- leesbare tekst + kantoorbrede lijst ------------------------------------------------------------------------


def _bevinding(cluster: rlz_dubbel.DubbelCluster, **extra) -> run_service.Bevinding:  # noqa: ANN003
    return run_service.Bevinding(
        blok=rlz_dubbel.BLOK,
        soort="afwijking",
        administratie_id=uuid.uuid4(),
        vingerafdruk="vaf6",
        tekst=f"AFWIJKING  … {cluster.sleutel} soort=dubbel_in_rlz [vaf:vaf6]: …",
        detail={
            "bron": "documenten",
            "record_id": str(cluster.record_id),
            "afwijking_soort": rlz_dubbel.SOORT,
            "detail": cluster.detail,
            **cluster.context(administratie_naam="Kempen Facilities B.V.", **extra),
        },
    )


class TestTekstEnLijst:
    def test_drie_exemplaren_zelfde_referentie_controleer(self) -> None:
        (cluster,) = vind_clusters(
            [
                _doc(V4_A, ref="202632703", boekstuk="RLZ-04-00004037", naam="BOOT B.V."),
                _doc(
                    V4_B,
                    ref="2026-32703",
                    boekstuk="RLZ-04-00004038",
                    naam="BOOT B.V.",
                    datum="2026-07-01T00:00:00Z",
                ),
                _doc(V4_C, ref="202632703", boekstuk="RLZ-04-00004099", naam="BOOT B.V.", datum="2026-08-01T00:00:00Z"),
            ],
            rlz_admin_id=RLZ_ADMIN,
        ).clusters
        lb = teksten.leesbaar(_bevinding(cluster))
        assert lb.titel == "Zelfde referentie, controleer — BOOT B.V. · 202632703"  # '3 boekstukken' viel weg (≤ 60)
        assert len(lb.titel) <= teksten.MAX_TITEL
        assert lb.wat.startswith(
            "In Reeleezee staan drie inkoopfacturen van BOOT B.V. met dezelfde referentie 202632703:"
        )
        assert (
            "RLZ-04-00004037 (22-06-2026, € 1.234,56), RLZ-04-00004038 (01-07-2026, € 1.234,56) en "
            "RLZ-04-00004099 (01-08-2026, € 1.234,56)" in lb.wat
        )
        assert "geen ervan via de module geboekt" in lb.wat and "waarschijnlijk" not in lb.wat
        assert lb.doe.startswith("Open alle 3 boekstuknummers in Reeleezee") and "verwijdert nooit" in lb.doe
        for zin in (lb.titel, lb.wat, lb.doe):
            assert not teksten.bevat_technische_sleutel(zin), zin
        labels = dict(lb.details)
        assert labels["RLZ-documenten (cluster)"] == f"{V4_A}, {V4_B}, {V4_C}"
        assert labels["cluster-sleutel"] == cluster.sleutel and labels["matchregel"] == "referentie"

    def test_six_steps_waarschijnlijk_dubbel(self) -> None:
        (cluster,) = vind_clusters(_six_steps(), rlz_admin_id=RLZ_ADMIN).clusters
        lb = teksten.leesbaar(_bevinding(cluster))
        assert lb.titel == "Waarschijnlijk dubbel — 6-Steps Projectbeheersing · 2026-118"
        assert "twee inkoopfacturen" in lb.wat and "RLZ-04-00000069 (14-08-2026, € 1.815,00, concept)" in lb.wat
        assert lb.wat.endswith(
            "Twee exemplaren zijn concept met dezelfde factuurdatum en hetzelfde bedrag — waarschijnlijk dubbel "
            "ingevoerd."
        )
        assert lb.doe.startswith("Open beide boekstuknummers in Reeleezee")
        assert teksten.rlz_dubbel_waarschijnlijk(_bevinding(cluster).detail) is True

    def test_geaccepteerd_en_module_variant(self) -> None:
        (cluster,) = vind_clusters(
            [_doc(V5_MODULE_A, ref="42", module_ids={V5_MODULE_A}), _doc(V4_B, ref="42", status=1, boekstuk=None)]
        ).clusters
        lb = teksten.leesbaar(_bevinding(cluster), soort="geaccepteerd")
        assert "dezelfde referentie 42" in lb.wat and "nog concept" in lb.wat and "zonder boekstuknummer" in lb.wat
        assert "één ervan via de module, de andere handmatig ingevoerd" in lb.wat
        assert lb.doe.startswith("Beoordeeld en blijvend")

    def test_oude_paar_bevinding_zonder_exemplaren_blijft_leesbaar_met_rangorde(self) -> None:
        """Bevindingen van vóór 10-09 dragen alleen A/B-velden: tekst werkt, rangorde wordt uit A/B afgeleid."""
        (paar,) = vind_paren(_six_steps())
        b = run_service.Bevinding(
            blok=rlz_dubbel.BLOK,
            soort="afwijking",
            administratie_id=uuid.uuid4(),
            vingerafdruk="v",
            tekst="",
            detail={"bron": "documenten", "afwijking_soort": rlz_dubbel.SOORT, **paar.context()},
        )
        lb = teksten.leesbaar(b)
        assert lb.titel.startswith("Waarschijnlijk dubbel — 6-Steps")
        assert "twee inkoopfacturen" in lb.wat and "geen van beide via de module" in lb.wat
        assert teksten.rlz_dubbel_waarschijnlijk(b.detail) is True
        b2 = run_service.Bevinding(
            blok=rlz_dubbel.BLOK,
            soort="afwijking",
            administratie_id=uuid.uuid4(),
            vingerafdruk="v",
            tekst="",
            detail={
                "bron": "documenten",
                "afwijking_soort": rlz_dubbel.SOORT,
                **vind_paren([_doc(V4_A, ref="42"), _doc(V4_B, ref="42")])[0].context(),
            },
        )
        assert teksten.leesbaar(b2).titel.startswith("Zelfde referentie, controleer")

    def test_kantoorbrede_lijst_waarschijnlijk_voor_controleer_na_verdwenen_document(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        docs = [*_six_steps(), _doc(V4_C, ref="42", boekstuk="RLZ-04-C1"), _doc(V4_D, ref="42", boekstuk="RLZ-04-C2")]
        _stub_toets(monkeypatch, administratie_id, docs)

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

        _voer_uit(extra_blokken=[("documenten", documenten_blok)])
        lijst = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, soort="afwijking")
        rijen = [r for r in lijst.rijen if r.administratie_id == administratie_id]
        assert [r.blok for r in rijen] == ["documenten", rlz_dubbel.BLOK, rlz_dubbel.BLOK]
        assert rijen[1].titel.startswith("Waarschijnlijk dubbel") and rijen[2].titel.startswith(
            "Zelfde referentie, controleer"
        )
        dubbel = rijen[1]
        assert dubbel.doel_pad is None and dubbel.detail["boekstukken"] == ["RLZ-04-00000069", "RLZ-04-00000072"]
        assert "Open beide boekstuknummers" in dubbel.doe

        kantoorbreed.accepteer(
            bevinding_id=rijen[2].id,
            administratie_id=administratie_id,
            reden="beoordeeld in Reeleezee — twee echte facturen",
            actor_id=beheerder_id,
            rol=GebruikerRol.BEHEERDER,
        )
        na = kantoorbreed.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, soort="geaccepteerd")
        assert any(r.blok == rlz_dubbel.BLOK and r.administratie_id == administratie_id for r in na.rijen)


# ---- CLI: lees-only + opties ----------------------------------------------------------------------------------------


class TestCliLeesOnly:
    def test_lees_only_toont_paren_oud_naar_clusters_nieuw_en_schrijft_niets(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
    ) -> None:
        docs = [*_bp_express(), *_food_service(), *_six_steps()]
        # Een paar-acceptatie die bij een echte run overgedragen zou worden — lees-only mag die NIET schrijven.
        (paar,) = vind_paren(_six_steps())
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron="documenten",
            record_id=paar.record_id,
            soort=rlz_dubbel.SOORT,
            detail=paar.detail,
            reden="beoordeeld: echt twee facturen",
            beheerder_id=beheerder_id,
        )
        gefilterd: list = []

        def toets_alle(**kw):  # noqa: ANN003, ANN202
            gefilterd.append(kw.get("administratie_ids"))
            return rlz_dubbel.RlzDubbelResultaat(rapporten={administratie_id: _rapport(administratie_id, docs)})

        monkeypatch.setattr(rlz_dubbel, "toets_alle", toets_alle)
        vorige = run_service.laatste_afgeronde_run()

        code = cli.main(
            ["reconciliatie-alles", "--alleen", "rlz_dubbel", "--lees-only", "--administratie", str(administratie_id)]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert gefilterd == [[administratie_id]]
        assert "LEES-ONLY: geen run-rij" in out and "=== rlz_dubbel-reconciliatie (lees-only) ===" in out
        assert "=== bank-reconciliatie" not in out
        assert (
            f"LEES-ONLY  {administratie_id} (Scope-test): 12 inkoopfacturen sinds 2025-08-04 — paren OUD 28 → "
            "clusters NIEUW 1 (1 waarschijnlijk dubbel, 0 open, 1 geaccepteerd, waarvan 1 via overdracht)" in out
        )
        assert "uitgesloten: iban 1 groep(en)/4 doc, klantkenmerk 1 groep(en)/7 doc" in out
        assert (
            "uitgesloten (klant-/contractnummer (≥ 3× met verschillende bedragen)): BP Express ref '0817725528' — "
            "7 documenten, 5 verschillende bedragen" in out
        )
        assert "uitgesloten (referentie is een IBAN): Food service ref 'NL86INGB0662462785' — 4 documenten" in out
        assert (
            "GEACCEPTEERD " in out
            and "RLZ-04-00000069 + RLZ-04-00000072 (referentie, ref 2026118, 2 exemplaren, waarschijnlijk dubbel, "
            "concept)"
            in out
        )
        assert "paren OUD 28 → clusters NIEUW 1; 0 open paar-bevinding(en) in de vorige run" in out
        assert "Niets geschreven, niets gemaild." in out and "LEES-ONLY afgerond — niets vastgelegd." in out
        # Niets vastgelegd: geen nieuwe run, geen cluster-acceptatie.
        assert run_service.laatste_afgeronde_run() == vorige
        with scoped_session(administratie_id) as session:
            rijen = session.scalars(
                select(ReconciliatieAcceptatie).where(ReconciliatieAcceptatie.administratie_id == administratie_id)
            ).all()
            assert [r.detail for r in rijen] == [paar.detail]

    def test_alleen_zonder_lees_only_is_geweigerd(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["reconciliatie-alles", "--alleen", "rlz_dubbel"]) == 2
        assert "--alleen werkt uitsluitend samen met --lees-only" in capsys.readouterr().err

    def test_administratie_alleen_voor_rlz_dubbel_en_onbekende_naam_is_fout(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["reconciliatie-alles", "--lees-only", "--administratie", "x"]) == 2
        assert "--administratie geldt alleen voor" in capsys.readouterr().err
        monkeypatch.setattr(rlz_dubbel, "toets_alle", lambda **kw: rlz_dubbel.RlzDubbelResultaat())
        assert (
            cli.main(
                [
                    "reconciliatie-alles",
                    "--alleen",
                    "rlz_dubbel",
                    "--lees-only",
                    "--administratie",
                    "bestaat-echt-niet-xyz",
                ]
            )
            == 2
        )
        assert "geen administratie gevonden" in capsys.readouterr().err

    def test_administratie_op_naamdeel(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], administratie_id: uuid.UUID
    ) -> None:
        gezien: list = []
        monkeypatch.setattr(
            rlz_dubbel,
            "toets_alle",
            lambda **kw: (gezien.append(kw.get("administratie_ids")), rlz_dubbel.RlzDubbelResultaat())[1],
        )
        code = cli.main(
            ["reconciliatie-alles", "--alleen", "rlz_dubbel", "--lees-only", "--administratie", "scope-tes"]
        )
        out = capsys.readouterr()
        if code == 2:  # meerdere 'Scope-test'-administraties in de testdatabase → eerlijk niet eenduidig
            assert "is niet eenduidig" in out.err
        else:
            assert (
                code == 0
                and gezien == [[administratie_id]]
                and f"Administratie: Scope-test ({administratie_id})" in out.out
            )

    def test_zonder_opties_ongewijzigd_alle_blokken_via_voer_uit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gezien: dict = {}

        def voer_uit(*, blokken, args, **kw):  # noqa: ANN001, ANN003, ANN202
            gezien["blokken"] = [naam for naam, _ in blokken]
            return 0

        monkeypatch.setattr(run_service, "voer_uit", voer_uit)
        assert cli.main(["reconciliatie-alles"]) == 0
        assert gezien["blokken"] == ["bank", "documenten", "omzet", "doorbelasting", "rlz_dubbel"]
