"""Blok 11 (17-09): project-dekking als STAP-0-instrument in de replay — puur over RlzBron."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.migratie import project_dekking as pd
from app.migratie.rlz_bron import RlzBron


@dataclass(frozen=True)
class _Toewijzing:
    pand_code: str


def _regel(code: str, project: tuple[str, str] | None, netto: str = "100.00") -> dict:
    r = {"Account": {"Code": code, "Name": f"rek {code}"}, "NetAmount": netto}
    if project:
        r["Project"] = {"id": project[0], "Name": project[1]}
    return r


def _bron() -> tuple[RlzBron, dict[uuid.UUID, _Toewijzing]]:
    b = RlzBron()
    d1, d2, d3 = (str(uuid.uuid4()) for _ in range(3))
    p1, p2 = (str(uuid.uuid4()), "Koraalerf 45 te Rotterdam"), (str(uuid.uuid4()), "Heidebeemd 3 te Zwolle")
    b.documenten = {
        "PurchaseInvoices": [{"id": d1, "ReceiptNumber": "RLZ-04-00000001", "DocumentType": 1, "Status": 2}],
        "ManualJournals": [
            {"id": d2, "ReceiptNumber": "RLZ-06-00000002", "DocumentType": 11, "Status": 3},
            {"id": d3, "ReceiptNumber": "RLZ-06-00000003", "DocumentType": 11, "Status": 3},
        ],
    }
    b.regels = {
        d1: [_regel("7000", p1, "185000.00"), _regel("1800", None, "38850.00")],  # btw zonder project = overig, telt niet mee
        d2: [_regel("1001", None, "5000.00"), _regel("1405", p1, "5000.00")],
        d3: [_regel("1001", None, "2000.00"), _regel("4601", None, "2000.00")],  # kosten zonder project op pand-rekening
    }
    b.bank = [{"id": "m1", "Amount": -1.0}]
    panden = {uuid.UUID(d1): _Toewijzing("koraalerf-45"), uuid.UUID(d2): _Toewijzing("koraalerf-45"), uuid.UUID(d3): _Toewijzing("heidebeemd-3")}
    return b, panden


def test_tellers_per_type_en_groep_en_zonder_project_lijst() -> None:
    bron, panden = _bron()
    d = pd.bereken(bron, panden=panden)
    assert d.documenten_met_regels == 3 and d.regels_totaal == 6 and d.regels_met_project == 2
    assert d.per_documenttype["inkoop"].totaal == 2 and d.per_documenttype["inkoop"].met_project == 1
    assert d.per_grootboekgroep["7000 aankoop"].aandeel == Decimal("1.000")
    assert d.per_grootboekgroep["46xx/70xx vaste lasten & kosten"].met_project == 0
    # pand-relevant: 7000 (1/1), 1405 (1/1), 4601 (0/1) → 2/3
    assert d.aandeel_pand_relevant == Decimal("0.667") and d.dekking_voldoende is False
    assert d.zonder_project_pand_relevant == [
        {"boekstuk": "RLZ-06-00000003", "documenttype": "memoriaal", "rekening": "4601", "groep": "46xx/70xx vaste lasten & kosten", "bedrag": "2000.00"}
    ]
    assert d.bank_project_veld_aanwezig is False
    assert "beslispunt Peter" in d.oordeel


def test_kruistoets_project_cluster() -> None:
    bron, panden = _bron()
    d = pd.bereken(bron, panden=panden)
    assert d.documenten_met_project_en_cluster == 2
    assert d.clusters_een_project == 1 and d.clusters_meer_projecten == 0
    assert d.projecten_een_cluster == 1 and d.projecten_versnipperd == 0
    assert list(d.project_naar_clusters.values()) == [["koraalerf-45"]]


def test_dekking_voldoende_en_markdown_en_dict() -> None:
    bron, panden = _bron()
    bron.regels[list(bron.regels)[2]][1]["Project"] = {"id": "p9", "Name": "Heidebeemd 3 te Zwolle"}
    d = pd.bereken(bron, panden=panden)
    assert d.dekking_voldoende is True and "≥ 90 %" in d.oordeel
    md = "\n".join(pd.markdown(d))
    assert "#### Project-dekking" in md and "| 7000 aankoop * |" in md
    js = d.als_dict()
    assert js["dekking_voldoende"] is True and js["kruistoets"]["projecten_versnipperd"] == 0


def test_lege_bron_niet_meetbaar() -> None:
    d = pd.bereken(RlzBron())
    assert d.dekking_voldoende is None and "niet meetbaar" in d.oordeel and d.bank_project_veld_aanwezig is None


def test_documentvorm_expand_leest_project_mee() -> None:
    """Vijfde meting 17-09: dekking 0,000 op 1125 documenten omdat de document-vorm géén `Project` expandeerde —
    het instrument leest `regel["Project"]`; de expand die de regels levert MOET 'm dragen (REGEL_EXPAND doet dat al)."""
    from app.migratie import rlz_bron

    assert "Project" in rlz_bron.DOCUMENTVORM_EXPAND and "Project" in rlz_bron.REGEL_EXPAND
    assert rlz_bron.DOCUMENTVORM_EXPAND == "DocumentLineList($expand=Account,TaxRate,Project)"
