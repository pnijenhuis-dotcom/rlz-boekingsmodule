# ruff: noqa: F811 — pytest-fixtures als parameters
"""Run 2 VGG 12-09 blok 2: dubbel-snede 2 (zelfde crediteur + zelfde bedrag + boekdatum ±3 d, ongeacht referentie)
als LEES-ONLY meetlat in `rlz_dubbel` — bank leidend (CONTRACT_RUN2 besluit 4 + 6).

Puur: paren binnen ±3 dagen wel, 4 dagen niet; zelfde referentie al in cluster → niet; beide module → niet; bank 2/2
→ niet gemeld (teller); bank 1/2 → gemeld; bank niet gelezen → gemeld mét markering. Lezer: `$filter=BookDate ge`,
400 → zonder filter, 403 → None. Guard: de dagelijkse run (snede2=False) leest GEEN PaymentTransactions en meldt niets
van snede 2; de lees-only CLI wél, mét regel per paar, tellers per administratie en totaal.

Punt 8 blok 7b (opdracht Peter 13-09; meetlat 13-09: 4.380 paren, 3.003× € 4.886,32 = 12 chalets × maand): een
PERIODIEKE REEKS (crediteur + cent-exact bedrag, ≥ 3 documenten over ≥ 2 kalendermaanden) is geen dubbel — álle paren
van die groep vallen weg, per groep geteld en in de lees-only-uitvoer vermeld; ≥ 3 gelijke bedragen binnen één maand
blijven paren. De KF-paren (module×niet-module, 2 documenten per bedrag) blijven gemeld — testcasus voor de
doorbelasting-aansluiting-mini-run.

Punt 8 blok 7c (opdracht Peter 13-09; nameting 13-09 Molenhof Verhuur: 78 × € 4.886,32 ÁLLE op 2026-01-01 = C(78,2) =
3.003 paren die de periodiek-uitsluiting niet ving): een DAG-BATCH (≥ 3 documenten, zelfde crediteur, zelfde bedrag,
zelfde datum op de boekdatum- óf factuurdatum-as) is nooit dubbel — eerst periodiek, dan dag-batch, een paar telt één
keer; twee documenten op één dag (KF-vorm) blijven een paar."""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app import cli
from app.migratie.bankdekking import BankMutatie
from app.reconciliatie import rlz_dubbel
from app.reconciliatie.rlz_dubbel import (
    LABEL_MODULE_X_NIET,
    LABEL_NIET_X_NIET,
    RlzDocument,
    Snede2DagBatchGroep,
    Snede2Paar,
    lees_payment_transactions,
    naar_rlz_document,
    snede2_uitkomst,
    toets_met_client,
    vind_clusters,
    vind_snede2,
)
from app.rlz.client import RlzApiError
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

ZENVOICES = uuid.UUID("d51c26fe-0000-4000-8000-00000000ce5a")
V5_MODULE = uuid.uuid5(uuid.NAMESPACE_URL, "snede2-module")
V5_MODULE_B = uuid.uuid5(uuid.NAMESPACE_URL, "snede2-module-b")


def _v4(n: int) -> uuid.UUID:
    return uuid.UUID(f"bbbbbbbb-0000-4000-8000-{n:012d}")


def _rij(
    rlz_id: uuid.UUID,
    *,
    ref: str | None,
    boekdatum: str,
    datum: str | None = None,
    bedrag: float = 1234.56,
    boekstuk: str = "RLZ-04-00000001",
    entity: uuid.UUID | None = ZENVOICES,
    naam: str = "Bouwbedrijf Jansen en Zonen B.V.",
    status: int = 2,
) -> dict:
    return {
        "id": str(rlz_id),
        "Entity": {"id": str(entity), "Name": naam} if entity else None,
        "Reference": ref,
        "Date": f"{datum or boekdatum}T00:00:00Z",
        "BookDate": f"{boekdatum}T00:00:00Z",
        "BaseInvoiceAmount": bedrag,
        "ReceiptNumber": boekstuk,
        "Status": status,
    }


def _doc(rlz_id: uuid.UUID, *, module_ids: set[uuid.UUID] | None = None, **kw) -> RlzDocument:
    d = naar_rlz_document(_rij(rlz_id, **kw), module_ids=module_ids or set())
    assert d is not None
    return d


def _bank(*mutaties: tuple[str, str]) -> list[BankMutatie]:
    """(bedrag, datum) → afboekingen (teken −1), zoals bij een betaalde inkoopfactuur."""
    return [
        BankMutatie(rlz_id=f"tx{i}", bedrag=Decimal(b), boekdatum=date.fromisoformat(d), teken=-1)
        for i, (b, d) in enumerate(mutaties)
    ]


def _paar_zenvoices_module() -> list[RlzDocument]:
    """Dezelfde factuur twee keer: via Zenvoices (handmatig, referentie F-2026-0042) en via de module (UUIDv5,
    referentie 2026-42 → zelfde genormaliseerde referentie zou snede 1 zijn; hier een ándere referentie)."""
    return [
        _doc(_v4(1), ref="F-2026-0042", boekdatum="2026-06-22", boekstuk="RLZ-04-00000100"),
        _doc(
            V5_MODULE,
            module_ids={V5_MODULE},
            ref="20260042-A",
            boekdatum="2026-06-24",
            boekstuk="RLZ-04-00000107",
        ),
    ]


class TestVindSnede2:
    def test_paar_binnen_drie_dagen_ongeacht_referentie_label_module_x_niet_module(self) -> None:
        (p,) = vind_snede2(_paar_zenvoices_module(), clusters=(), bank=[])
        assert isinstance(p, Snede2Paar)
        assert {p.a.boekstuk, p.b.boekstuk} == {"RLZ-04-00000100", "RLZ-04-00000107"}
        assert p.label == LABEL_MODULE_X_NIET and p.dagen_verschil == 2 and p.bedrag == Decimal("1234.56")
        assert p.bank_gelezen is True and p.bank_mutaties == 0 and p.bank_bevestigd is False

    def test_vier_dagen_is_geen_paar_drie_wel(self) -> None:
        a = _doc(_v4(1), ref="A", boekdatum="2026-06-22")
        assert vind_snede2([a, _doc(_v4(2), ref="B", boekdatum="2026-06-26")], clusters=(), bank=[]) == []
        assert len(vind_snede2([a, _doc(_v4(2), ref="B", boekdatum="2026-06-25")], clusters=(), bank=[])) == 1

    def test_boekdatum_gaat_voor_factuurdatum(self) -> None:
        a = _doc(_v4(1), ref="A", boekdatum="2026-06-22", datum="2026-01-01")
        b = _doc(_v4(2), ref="B", boekdatum="2026-06-23", datum="2026-03-03")
        (p,) = vind_snede2([a, b], clusters=(), bank=[])
        assert p.dagen_verschil == 1

    def test_ander_bedrag_of_andere_crediteur_of_geen_crediteur_is_geen_paar(self) -> None:
        a = _doc(_v4(1), ref="A", boekdatum="2026-06-22")
        assert (
            vind_snede2([a, _doc(_v4(2), ref="B", boekdatum="2026-06-22", bedrag=1234.57)], clusters=(), bank=[]) == []
        )
        andere = _doc(_v4(3), ref="B", boekdatum="2026-06-22", entity=uuid.UUID(int=7))
        assert vind_snede2([a, andere], clusters=(), bank=[]) == []
        assert vind_snede2([a, _doc(_v4(4), ref="B", boekdatum="2026-06-22", entity=None)], clusters=(), bank=[]) == []

    def test_zelfde_referentie_al_in_cluster_wordt_niet_nog_eens_gemeld(self) -> None:
        docs = [
            _doc(_v4(1), ref="2026-118", boekdatum="2026-08-14", boekstuk="RLZ-04-00000069"),
            _doc(_v4(2), ref="2026-118", boekdatum="2026-08-14", boekstuk="RLZ-04-00000072"),
        ]
        clusters = vind_clusters(docs, rlz_admin_id="r").clusters
        assert len(clusters) == 1
        assert vind_snede2(docs, clusters=clusters, bank=[]) == []
        # zonder de cluster-uitsluiting zou het wél een snede-2-paar zijn (guard op de uitsluiting zelf)
        assert len(vind_snede2(docs, clusters=(), bank=[])) == 1

    def test_beide_van_de_module_is_nooit_een_paar(self) -> None:
        ids = {V5_MODULE, V5_MODULE_B}
        docs = [
            _doc(V5_MODULE, module_ids=ids, ref="A", boekdatum="2026-06-22"),
            _doc(V5_MODULE_B, module_ids=ids, ref="B", boekdatum="2026-06-22"),
        ]
        assert vind_snede2(docs, clusters=(), bank=[]) == []
        # één module + één handmatig ís een paar; twee handmatige óók (niet-module×niet-module)
        docs2 = [_doc(_v4(1), ref="A", boekdatum="2026-06-22"), _doc(_v4(2), ref="B", boekdatum="2026-06-22")]
        (p,) = vind_snede2(docs2, clusters=(), bank=[])
        assert p.label == LABEL_NIET_X_NIET

    def test_bank_twee_van_twee_is_bevestigd_en_niet_gemeld_wel_geteld(self) -> None:
        bank = _bank(("1234.56", "2026-06-23"), ("1234.56", "2026-06-25"))
        assert vind_snede2(_paar_zenvoices_module(), clusters=(), bank=bank) == []
        u = snede2_uitkomst(_paar_zenvoices_module(), clusters=(), bank=bank)
        assert u.paren == () and u.bank_bevestigd == 1 and u.bank_gelezen is True
        assert u.tellers() == {
            "paren": 0,
            LABEL_MODULE_X_NIET: 0,
            LABEL_NIET_X_NIET: 0,
            "bank_bevestigd": 1,
            "periodiek_groepen": 0,
            "periodiek_paren": 0,
            "dagbatch_groepen": 0,
            "dagbatch_paren": 0,
        }

    def test_bank_een_van_twee_is_gemeld_met_k_van_n(self) -> None:
        bank = _bank(("1234.56", "2026-06-23"), ("1234.56", "2026-07-10"))  # tweede buiten het venster
        (p,) = vind_snede2(_paar_zenvoices_module(), clusters=(), bank=bank)
        assert p.bank_mutaties == 1 and p.bank_bevestigd is False
        assert p.regel("adm").endswith("| module×niet-module | bank 1/2")

    def test_bank_teken_moet_afboeking_zijn_voor_inkoop(self) -> None:
        bijboekingen = [BankMutatie("t", Decimal("1234.56"), date(2026, 6, 23), 1) for _ in range(2)]
        (p,) = vind_snede2(_paar_zenvoices_module(), clusters=(), bank=bijboekingen)
        assert p.bank_mutaties == 0

    def test_bank_niet_gelezen_gemeld_met_markering(self) -> None:
        bank = _bank(("1234.56", "2026-06-23"), ("1234.56", "2026-06-25"))
        assert vind_snede2(_paar_zenvoices_module(), clusters=(), bank=bank) == []
        (p,) = vind_snede2(_paar_zenvoices_module(), clusters=(), bank=None)
        assert p.bank_gelezen is False and p.bank_bevestigd is False
        assert p.regel("adm").endswith("| bank niet gelezen")
        u = snede2_uitkomst(_paar_zenvoices_module(), clusters=(), bank=None)
        assert u.bank_gelezen is False and u.bank_bevestigd == 0 and len(u.paren) == 1

    def test_regel_anonimiseert_crediteur_tot_initialen(self) -> None:
        (p,) = vind_snede2(_paar_zenvoices_module(), clusters=(), bank=[])
        regel = p.regel("adm-1")
        assert regel.startswith(
            "SNEDE2 adm-1 RLZ-04-00000100 + RLZ-04-00000107 | B.J.E.Z. | € 1234.56 | 2026-06-22/2026-06-24 | "
        )
        assert "Jansen" not in regel

    def test_drie_exemplaren_geven_drie_paren_elke_bankmutatie_een_keer(self) -> None:
        # drie opeenvolgende dagen (geen dag-batch, geen reeks): alle drie de paren binnen ±3 d
        docs = [
            _doc(_v4(i), ref=f"R{i}", boekdatum=f"2026-06-{21 + i}", boekstuk=f"RLZ-04-{i:08d}") for i in range(1, 4)
        ]
        bank = _bank(("1234.56", "2026-06-22"))
        paren = vind_snede2(docs, clusters=(), bank=bank)
        assert len(paren) == 3 and all(p.bank_mutaties == 1 for p in paren)
        assert paren == sorted(paren, key=lambda p: (str(p.a.rlz_id), str(p.b.rlz_id)))


# ---- periodieke reeksen (punt 8 blok 7b, 13-09) ------------------------------------------------------------


CHALETS = uuid.UUID("c4a1e750-0000-4000-8000-00000000c4a1")


def _chalets(maand_datums: list[str], *, per_maand: int = 12, bedrag: float = 4886.32) -> list[RlzDocument]:
    """`per_maand` gelijke facturen op élke gegeven datum (12 chalets × maand), zelfde verhuurder + bedrag."""
    docs: list[RlzDocument] = []
    n = 0
    for datum in maand_datums:
        for _ in range(per_maand):
            n += 1
            docs.append(
                _doc(
                    _v4(500 + n),
                    ref=f"CH-{n:04d}",
                    boekdatum=datum,
                    bedrag=bedrag,
                    boekstuk=f"RLZ-14-{n:08d}",
                    entity=CHALETS,
                    naam="Vakantiepark Recreatie Beheer B.V.",
                )
            )
    return docs


class TestPeriodiekeReeksUitgesloten:
    def test_twaalf_per_maand_over_twee_maanden_is_een_periodieke_groep_zonder_paren(self) -> None:
        docs = _chalets(["2026-01-01", "2026-02-01"])
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        assert u.paren == () and vind_snede2(docs, clusters=(), bank=[]) == []
        (g,) = u.periodiek_groepen
        assert g.entity_id == CHALETS and g.bedrag == Decimal("4886.32")
        assert g.aantal_documenten == 24 and g.aantal_maanden == 2
        assert g.aantal_paren == 2 * 66  # 2 × C(12, 2): alle paren binnen de dag, over de maandgrens geen (> 3 d)
        assert g.patroon  # gevuld — twee unieke datums is nog geen bewezen maandpatroon, wél de kale telling
        assert g.patroon == "≥ 3 gelijke bedragen over 2 maanden"
        assert u.tellers()["periodiek_groepen"] == 1 and u.tellers()["periodiek_paren"] == 132
        assert u.bank_bevestigd == 0
        assert g.regel() == (
            "· uitgesloten (periodiek): V.R.B.B. € 4886.32 — 24 documenten over 2 maanden, "
            "≥ 3 gelijke bedragen over 2 maanden, 132 paren"
        )
        assert "Vakantiepark" not in g.regel()

    def test_maandpatroon_wordt_via_classificeer_reeks_gelabeld(self) -> None:
        docs = _chalets(["2026-01-01", "2026-02-01", "2026-03-01"], per_maand=2)
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        (g,) = u.periodiek_groepen
        assert u.paren == () and g.aantal_paren == 3 and g.aantal_documenten == 6 and g.aantal_maanden == 3
        assert g.patroon == "maand-patroon over 3 facturen"

    def test_drie_gelijke_bedragen_op_een_dag_zijn_dag_batch(self) -> None:
        # blok 7c: géén periodieke reeks (één maand), wél een dag-batch — 0 paren gemeld, 3 weggenomen
        docs = _chalets(["2026-01-05"], per_maand=3)
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        assert u.periodiek_groepen == () and u.paren == ()
        assert u.tellers()["periodiek_groepen"] == 0 and u.tellers()["periodiek_paren"] == 0
        (b,) = u.dagbatch_groepen
        assert b.aantal_documenten == 3 and b.aantal_paren == 3 and b.as_ == "boekdatum"
        assert u.tellers()["dagbatch_groepen"] == 1 and u.tellers()["dagbatch_paren"] == 3

    def test_drie_gelijke_bedragen_op_drie_dagen_binnen_een_maand_blijven_paren(self) -> None:
        # geen periodiek (één maand), geen dag-batch (drie verschillende dagen), wél binnen ±3 d: drie paren
        docs = [
            _doc(_v4(700 + i), ref=f"D{i}", boekdatum=f"2026-01-0{5 + i}", bedrag=4886.32, entity=CHALETS)
            for i in range(3)
        ]
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        assert u.periodiek_groepen == () and u.dagbatch_groepen == () and len(u.paren) == 3
        assert u.tellers()["dagbatch_groepen"] == 0 and u.tellers()["dagbatch_paren"] == 0

    def test_maanden_tellen_ook_op_factuurdatum_bij_een_gedeelde_boekdatum(self) -> None:
        """Meetlat 13-09: de 78 chaletfacturen droegen álle boekdatum 2026-01-01 (jaarlijkse boekdag); de factuurdatum
        (Date) spreidt over de maanden. Op boekdatum alleen zou de reeks nooit periodiek zijn."""
        docs = [
            _doc(_v4(600 + i), ref=f"J{i}", boekdatum="2026-01-01", datum=f"2026-{m:02d}-01", entity=CHALETS)
            for i, m in enumerate((1, 1, 2, 2, 3, 3))
        ]
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        (g,) = u.periodiek_groepen
        assert u.paren == () and g.aantal_paren == 15 and g.aantal_maanden == 3

    def test_periodieke_groep_neemt_ook_bank_bevestigde_paren_weg_en_telt_ze_niet_dubbel(self) -> None:
        docs = _chalets(["2026-01-01", "2026-02-01"], per_maand=2)
        bank = _bank(("4886.32", "2026-01-01"), ("4886.32", "2026-01-02"))
        u = snede2_uitkomst(docs, clusters=(), bank=bank)
        assert u.paren == () and u.bank_bevestigd == 0
        assert u.periodiek_groepen[0].aantal_paren == 2

    def test_periodieke_groep_zonder_paren_wordt_niet_vermeld(self) -> None:
        # drie maanden, één factuur per maand: een reeks, maar geen snede-2-paar (> 3 dagen) — niets weggenomen
        docs = _chalets(["2026-01-01", "2026-02-01", "2026-03-01"], per_maand=1)
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        assert u.paren == () and u.periodiek_groepen == ()

    def test_ander_bedrag_bij_dezelfde_crediteur_valt_niet_mee_weg(self) -> None:
        docs = _chalets(["2026-01-01", "2026-02-01"]) + [
            _doc(_v4(901), ref="X1", boekdatum="2026-01-01", bedrag=99.0, entity=CHALETS),
            _doc(_v4(902), ref="X2", boekdatum="2026-01-01", bedrag=99.0, entity=CHALETS),
        ]
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        assert [p.bedrag for p in u.paren] == [Decimal("99.00")] and len(u.periodiek_groepen) == 1


# ---- dag-batches (punt 8 blok 7c, 13-09) -------------------------------------------------------------------


MOLENHOF = uuid.UUID("a0d4e750-0000-4000-8000-0000000a0d4e")


def _molenhof(n: int = 78, *, boekdatum: str = "2026-01-01", datum: str | None = None) -> list[RlzDocument]:
    return [
        _doc(
            _v4(2000 + i),
            ref=f"MH-{i:04d}",
            boekdatum=boekdatum,
            datum=datum,
            bedrag=4886.32,
            boekstuk=f"RLZ-21-{i:08d}",
            entity=MOLENHOF,
            naam="Molenhof Verhuur B.V.",
        )
        for i in range(1, n + 1)
    ]


class TestDagBatchUitgesloten:
    def test_molenhof_78_op_een_dag_is_een_dag_batch_zonder_paren(self) -> None:
        """Nameting 13-09 (administratie d2e7f9f6…): 78 × € 4.886,32 álle op 2026-01-01 = C(78,2) = 3.003 paren; de
        periodiek-uitsluiting ving ze niet (één dag, één maand)."""
        docs = _molenhof()
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        assert u.paren == () and vind_snede2(docs, clusters=(), bank=[]) == []
        assert u.periodiek_groepen == () and u.bank_bevestigd == 0
        (b,) = u.dagbatch_groepen
        assert isinstance(b, Snede2DagBatchGroep)
        assert b.entity_id == MOLENHOF and b.bedrag == Decimal("4886.32") and b.datum == date(2026, 1, 1)
        assert b.aantal_documenten == 78 and b.aantal_paren == 3003 == 78 * 77 // 2 and b.as_ == "boekdatum"
        assert u.tellers()["dagbatch_groepen"] == 1 and u.tellers()["dagbatch_paren"] == 3003
        assert (
            b.regel()
            == "· uitgesloten (dag-batch): M.V.B. € 4886.32 — 78 documenten op 2026-01-01 (boekdatum), 3003 paren"
        )
        assert "78 documenten op 2026-01-01" in b.regel() and "Molenhof" not in b.regel()

    def test_twee_op_een_dag_blijven_een_paar(self) -> None:
        # de KF-vorm: twee documenten per bedrag op dezelfde dag zijn geen batch
        u = snede2_uitkomst(_molenhof(2), clusters=(), bank=[])
        assert len(u.paren) == 1 and u.dagbatch_groepen == () and u.periodiek_groepen == ()

    def test_factuurdatum_as_bij_verschillende_boekdatums(self) -> None:
        # boekdatums 05/06/07 (paren binnen ±3 d), factuurdatum álle 2026-01-05 → dag-batch op de factuurdatum-as
        docs = [
            _doc(
                _v4(2100 + i),
                ref=f"F{i}",
                boekdatum=f"2026-01-0{5 + i}",
                datum="2026-01-05",
                bedrag=4886.32,
                entity=MOLENHOF,
            )
            for i in range(3)
        ]
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        assert u.paren == () and u.periodiek_groepen == ()
        (b,) = u.dagbatch_groepen
        assert (
            b.as_ == "factuurdatum" and b.datum == date(2026, 1, 5) and b.aantal_documenten == 3 and b.aantal_paren == 3
        )
        assert "(factuurdatum)" in b.regel()

    def test_periodiek_weggevallen_paar_telt_niet_nog_eens_als_dag_batch(self) -> None:
        # chalets 2 maanden × 12: periodiek wint (132 paren), de dag-batches (12 op één dag) nemen niets meer weg
        u = snede2_uitkomst(_chalets(["2026-01-01", "2026-02-01"]), clusters=(), bank=[])
        assert u.paren == () and u.tellers()["periodiek_paren"] == 132
        assert u.dagbatch_groepen == () and u.tellers()["dagbatch_groepen"] == 0 and u.tellers()["dagbatch_paren"] == 0

    def test_dag_batch_neemt_ook_bank_bevestigde_paren_weg(self) -> None:
        bank = _bank(("4886.32", "2026-01-01"), ("4886.32", "2026-01-01"), ("4886.32", "2026-01-01"))
        u = snede2_uitkomst(_molenhof(3), clusters=(), bank=bank)
        assert u.paren == () and u.bank_bevestigd == 0 and u.dagbatch_groepen[0].aantal_paren == 3

    def test_ander_bedrag_op_dezelfde_dag_blijft_een_paar(self) -> None:
        docs = _molenhof(3) + [
            _doc(_v4(2201), ref="X1", boekdatum="2026-01-01", bedrag=99.0, entity=MOLENHOF),
            _doc(_v4(2202), ref="X2", boekdatum="2026-01-01", bedrag=99.0, entity=MOLENHOF),
        ]
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        assert [p.bedrag for p in u.paren] == [Decimal("99.00")] and len(u.dagbatch_groepen) == 1


HKD = uuid.UUID("aaaa0000-0000-4000-8000-00000000d0e1")
V5_KF_A = uuid.uuid5(uuid.NAMESPACE_URL, "kf-doorbelasting-12600")
V5_KF_B = uuid.uuid5(uuid.NAMESPACE_URL, "kf-doorbelasting-16250")


class TestKFParenDoorbelastingAansluiting:
    """Testcasus voor de DOORBELASTING-AANSLUITING-MINI-RUN (opdracht Peter 13-09, punt 8 blok 7b): de twee
    module×niet-module-paren uit de nameting 13-09 bij Kempen Facilities — crediteur "H.K.D. B.V.", boekdatum
    2026-08-10, RLZ-04-00004412 + RLZ-04-00004314 € 12.600,00 en RLZ-04-00004312 + RLZ-04-00004415 € 16.250,00,
    telkens één exemplaar van de module (doorbelasting-spiegel) en één handmatig, bank 0/2. Twee documenten per bedrag
    zijn géén reeks: ze blijven ná de periodiek-uitsluiting gemeld. De mini-run moet verklaren waarom de spiegel én
    een handmatige factuur naast elkaar staan."""

    @staticmethod
    def _docs() -> list[RlzDocument]:
        ids = {V5_KF_A, V5_KF_B}
        kw = dict(boekdatum="2026-08-10", entity=HKD, naam="Hekade Kempen Diensten B.V.")  # initialen H.K.D.B.
        return [
            _doc(V5_KF_A, module_ids=ids, ref="DB-2026-0812", bedrag=12600.0, boekstuk="RLZ-04-00004412", **kw),
            _doc(_v4(4314), ref="HKD-2026-091", bedrag=12600.0, boekstuk="RLZ-04-00004314", **kw),
            _doc(_v4(4312), ref="HKD-2026-090", bedrag=16250.0, boekstuk="RLZ-04-00004312", **kw),
            _doc(V5_KF_B, module_ids=ids, ref="DB-2026-0813", bedrag=16250.0, boekstuk="RLZ-04-00004415", **kw),
        ]

    def test_kf_paren_blijven_module_x_niet_module_na_periodiek_uitsluiting(self) -> None:
        u = snede2_uitkomst(self._docs(), clusters=(), bank=[])
        assert u.periodiek_groepen == () and u.dagbatch_groepen == ()  # twee per bedrag op één dag: geen batch
        gemeld = sorted(({p.a.boekstuk, p.b.boekstuk}, p.bedrag, p.label, p.bank_mutaties) for p in u.paren)
        assert gemeld == sorted(
            [
                ({"RLZ-04-00004412", "RLZ-04-00004314"}, Decimal("12600.00"), LABEL_MODULE_X_NIET, 0),
                ({"RLZ-04-00004312", "RLZ-04-00004415"}, Decimal("16250.00"), LABEL_MODULE_X_NIET, 0),
            ]
        )
        assert u.tellers()[LABEL_MODULE_X_NIET] == 2 and u.tellers()[LABEL_NIET_X_NIET] == 0

    def test_kf_paren_blijven_staan_naast_een_periodieke_reeks_in_dezelfde_administratie(self) -> None:
        docs = self._docs() + _chalets(["2026-01-01", "2026-02-01"])
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        assert len(u.periodiek_groepen) == 1 and len(u.paren) == 2
        assert all(p.label == LABEL_MODULE_X_NIET for p in u.paren)

    def test_kf_regels_anoniem_in_de_uitvoer(self) -> None:
        u = snede2_uitkomst(self._docs(), clusters=(), bank=[])
        regels = [p.regel("kf") for p in u.paren]
        assert all("| H.K.D.B. | " in r and r.endswith("| module×niet-module | bank 0/2") for r in regels)
        assert any("RLZ-04-00004412" in r and "RLZ-04-00004314" in r and "€ 12600.00" in r for r in regels)
        assert any("RLZ-04-00004312" in r and "RLZ-04-00004415" in r and "€ 16250.00" in r for r in regels)


# ---- lezer + toets_met_client ------------------------------------------------------------------------------


class _Client:
    """PurchaseInvoices + PaymentTransactions; `bank_filter` = 'ok' | 400 | 403 bepaalt het antwoord op een
    `$filter` op PaymentTransactions."""

    def __init__(self, facturen: list[dict], bank: list[dict], *, bank_filter: str | int = "ok") -> None:
        self.facturen, self.bank, self.bank_filter = facturen, bank, bank_filter
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, *, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((path, params))
        rijen = self.facturen if path == "PurchaseInvoices" else self.bank
        if path == "PaymentTransactions":
            if self.bank_filter == 403:
                raise RlzApiError(403, "GET", path, "Forbidden")
            if "$filter" in params and self.bank_filter == 400:
                raise RlzApiError(400, "GET", path, "filter niet ondersteund")
        skip, top = int(params["$skip"]), int(params["$top"])
        return {"value": rijen[skip : skip + top]}

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _tx(bedrag: float, datum: str, id_: str) -> dict:
    return {"id": id_, "Amount": bedrag, "BookDate": f"{datum}T00:00:00", "OpenAmount": 0.0}


class TestLezerEnToets:
    def test_filter_bookdate_eerst(self) -> None:
        client = _Client([], [_tx(-1234.56, "2026-06-23", "a")])
        rijen = lees_payment_transactions(client, vanaf=date(2025, 8, 4))  # type: ignore[arg-type]
        assert rijen == [_tx(-1234.56, "2026-06-23", "a")]
        assert client.calls == [
            ("PaymentTransactions", {"$top": "200", "$skip": "0", "$filter": "BookDate ge 2025-08-04"})
        ]

    def test_400_op_filter_valt_terug_zonder_filter_en_filtert_client_side(self) -> None:
        client = _Client([], [_tx(-1.0, "2024-01-01", "oud"), _tx(-1234.56, "2026-06-23", "a")], bank_filter=400)
        rijen = lees_payment_transactions(client, vanaf=date(2025, 8, 4))  # type: ignore[arg-type]
        assert [r["id"] for r in rijen] == ["a"]
        assert [("$filter" in p) for _, p in client.calls] == [True, False]

    def test_403_is_none_bank_niet_gelezen(self) -> None:
        client = _Client([], [_tx(-1.0, "2026-06-23", "a")], bank_filter=403)
        assert lees_payment_transactions(client, vanaf=date(2025, 8, 4)) is None  # type: ignore[arg-type]

    def test_dagelijkse_run_leest_geen_paymenttransactions_en_kent_geen_snede2(self) -> None:
        client = _Client(
            [_rij(d.rlz_id, ref=d.referentie, boekdatum="2026-06-22") for d in _paar_zenvoices_module()], []
        )
        r = toets_met_client(client, module_ids={V5_MODULE}, vandaag=date(2026, 9, 8))  # type: ignore[arg-type]
        assert r.snede2 is None
        assert all(pad == "PurchaseInvoices" for pad, _ in client.calls)

    def test_lees_only_leest_bank_en_vult_snede2(self) -> None:
        facturen = [
            _rij(_v4(1), ref="F-2026-0042", boekdatum="2026-06-22", boekstuk="RLZ-04-00000100"),
            _rij(V5_MODULE, ref="20260042-A", boekdatum="2026-06-24", boekstuk="RLZ-04-00000107"),
            _rij(_v4(5), ref="X1", boekdatum="2026-07-01", boekstuk="RLZ-04-00000200", bedrag=50.0),
            _rij(_v4(6), ref="X2", boekdatum="2026-07-02", boekstuk="RLZ-04-00000201", bedrag=50.0),
        ]
        bank = [_tx(-50.0, "2026-07-01", "a"), _tx(-50.0, "2026-07-02", "b")]  # het € 50-paar is bank-bevestigd
        client = _Client(facturen, bank)
        r = toets_met_client(client, module_ids={V5_MODULE}, vandaag=date(2026, 9, 8), snede2=True)  # type: ignore[arg-type]
        assert r.snede2 is not None and r.snede2.gedraaid and r.snede2.bank_gelezen
        assert [(p.a.boekstuk, p.b.boekstuk, p.label) for p in r.snede2.paren] == [
            ("RLZ-04-00000100", "RLZ-04-00000107", LABEL_MODULE_X_NIET)
        ] or [(p.b.boekstuk, p.a.boekstuk, p.label) for p in r.snede2.paren] == [
            ("RLZ-04-00000100", "RLZ-04-00000107", LABEL_MODULE_X_NIET)
        ]
        assert r.snede2.bank_bevestigd == 1
        assert any(pad == "PaymentTransactions" for pad, _ in client.calls)

    def test_lees_only_met_geweigerde_bank_markeert(self) -> None:
        facturen = [_rij(d.rlz_id, ref=d.referentie, boekdatum=str(d.boekdatum)) for d in _paar_zenvoices_module()]
        client = _Client(facturen, [], bank_filter=403)
        r = toets_met_client(client, module_ids={V5_MODULE}, vandaag=date(2026, 9, 8), snede2=True)  # type: ignore[arg-type]
        assert r.snede2 is not None and r.snede2.bank_gelezen is False and len(r.snede2.paren) == 1


# ---- CLI (lees-only) ---------------------------------------------------------------------------------------


def _rapport(aid: uuid.UUID, documenten: list[RlzDocument], *, snede2: rlz_dubbel.Snede2Uitkomst | None):
    uitkomst = vind_clusters(documenten, rlz_admin_id="rlz-a")
    return rlz_dubbel.RlzDubbelRapport(
        administratie_id=aid,
        aantal_getoetst=len(documenten),
        aantal_module=sum(1 for d in documenten if d.van_module),
        aantal_zonder_crediteur=0,
        paren=(),
        venster_vanaf=date(2025, 8, 4),
        clusters=uitkomst.clusters,
        uitgesloten=uitkomst.uitgesloten,
        rlz_admin_id="rlz-a",
        snede2=snede2,
    )


class TestCliLeesOnlySnede2:
    def test_lees_only_print_regel_per_paar_tellers_en_totaal(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], administratie_id: uuid.UUID
    ) -> None:
        docs = _paar_zenvoices_module()
        gezien: list[dict] = []

        def toets_alle(**kw):  # noqa: ANN003, ANN202
            gezien.append(kw)
            u = snede2_uitkomst(docs, clusters=(), bank=_bank(("1234.56", "2026-06-23")))
            return rlz_dubbel.RlzDubbelResultaat(
                rapporten={administratie_id: _rapport(administratie_id, docs, snede2=u)}
            )

        monkeypatch.setattr(rlz_dubbel, "toets_alle", toets_alle)
        code = cli.main(
            ["reconciliatie-alles", "--alleen", "rlz_dubbel", "--lees-only", "--administratie", str(administratie_id)]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert gezien == [{"administratie_ids": [administratie_id], "snede2": True}]
        assert (
            f"    - SNEDE2 {administratie_id} RLZ-04-00000100 + RLZ-04-00000107 | B.J.E.Z. | € 1234.56 | "
            "2026-06-22/2026-06-24 | module×niet-module | bank 1/2" in out
        )
        assert (
            f"    SNEDE2 tellers {administratie_id}: paren 1, module×niet-module 1, niet-module×niet-module 0, "
            "bank-bevestigd 0, periodiek uitgesloten 0 groepen/0 paren, dag-batch uitgesloten 0 groepen/0 paren" in out
        )
        assert (
            "SNEDE2 totaal over 1 administratie(s): paren 1, module×niet-module 1, niet-module×niet-module 0, "
            "bank-bevestigd 0, periodiek uitgesloten 0 groepen/0 paren, dag-batch uitgesloten 0 groepen/0 paren. "
            "Alleen meetlat — de dagelijkse run meldt snede 2 niet (beslispunt Peter)." in out
        )
        assert "Jansen" not in out

    def test_lees_only_print_periodieke_groep_voor_de_paren_en_telt_in_tellers_en_totaal(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], administratie_id: uuid.UUID
    ) -> None:
        docs = _paar_zenvoices_module() + _chalets(["2026-01-01", "2026-02-01"]) + _molenhof(3, boekdatum="2026-03-03")
        u = snede2_uitkomst(docs, clusters=(), bank=[])
        monkeypatch.setattr(
            rlz_dubbel,
            "toets_alle",
            lambda **kw: rlz_dubbel.RlzDubbelResultaat(
                rapporten={administratie_id: _rapport(administratie_id, docs, snede2=u)}
            ),
        )
        assert cli.main(["reconciliatie-alles", "--alleen", "rlz_dubbel", "--lees-only"]) == 0
        out = capsys.readouterr().out
        groep = (
            "    · uitgesloten (periodiek): V.R.B.B. € 4886.32 — 24 documenten over 2 maanden, "
            "≥ 3 gelijke bedragen over 2 maanden, 132 paren"
        )
        batch = "    · uitgesloten (dag-batch): M.V.B. € 4886.32 — 3 documenten op 2026-03-03 (boekdatum), 3 paren"
        paar = f"    - SNEDE2 {administratie_id} RLZ-04-00000100 + RLZ-04-00000107 |"
        assert groep in out and batch in out and paar in out
        assert out.index(groep) < out.index(batch) < out.index(paar)
        assert (
            f"    SNEDE2 tellers {administratie_id}: paren 1, module×niet-module 1, niet-module×niet-module 0, "
            "bank-bevestigd 0, periodiek uitgesloten 1 groepen/132 paren, dag-batch uitgesloten 1 groepen/3 paren"
            in out
        )
        assert "SNEDE2 totaal over 1 administratie(s): paren 1, " in out
        assert (
            "bank-bevestigd 0, periodiek uitgesloten 1 groepen/132 paren, dag-batch uitgesloten 1 groepen/3 paren. "
            "Alleen meetlat" in out
        )
        assert "Vakantiepark" not in out and "Jansen" not in out and "Molenhof" not in out

    def test_lees_only_bank_niet_gelezen_zichtbaar_in_tellers_en_totaal(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], administratie_id: uuid.UUID
    ) -> None:
        docs = _paar_zenvoices_module()
        u = snede2_uitkomst(docs, clusters=(), bank=None)
        monkeypatch.setattr(
            rlz_dubbel,
            "toets_alle",
            lambda **kw: rlz_dubbel.RlzDubbelResultaat(
                rapporten={administratie_id: _rapport(administratie_id, docs, snede2=u)}
            ),
        )
        assert cli.main(["reconciliatie-alles", "--alleen", "rlz_dubbel", "--lees-only"]) == 0
        out = capsys.readouterr().out
        assert "| module×niet-module | bank niet gelezen" in out
        assert (
            "bank-bevestigd 0, periodiek uitgesloten 0 groepen/0 paren, dag-batch uitgesloten 0 groepen/0 paren "
            "— BANK NIET GELEZEN (PaymentTransactions weigerde; niets gefilterd)" in out
        )
        assert "bank niet gelezen bij 1 administratie(s)" in out

    def test_dagelijkse_run_vraagt_snede2_false_en_print_niets_van_snede2(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID
    ) -> None:
        gezien: list[dict] = []

        def toets_alle(**kw):  # noqa: ANN003, ANN202
            gezien.append(kw)
            return rlz_dubbel.RlzDubbelResultaat(
                rapporten={administratie_id: _rapport(administratie_id, _paar_zenvoices_module(), snede2=None)}
            )

        monkeypatch.setattr(rlz_dubbel, "toets_alle", toets_alle)
        uit: list[str] = []
        assert rlz_dubbel.cli_blok(argparse.Namespace(), verzamelaar=None, stdout=uit.append, stderr=uit.append) == 0
        assert gezien == [{"administratie_ids": None, "snede2": False}]
        assert not any("SNEDE2" in r for r in uit)
