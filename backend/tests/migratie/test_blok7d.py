"""Blok 7d run 2 VGG (14-09-2026) — tekenfout memorialen, volledigheidstoets op EventID, RLZ-resultaatposten buiten de
saldibalans-toets, betalingsverschil-afboeking, oordeel "GROEN ZONDER DOEL", partner-blokkade (besluit Peter 14-09).

Geldlogica-tests (opdracht punt 1): de vijf STAP-0-documenten van de nameting 13-09 als fixture — RLZ-06-00000001
(0500/1001), RLZ-06-00000106 (1100/1601), RLZ-06-00000038 (loonjournaal 1710/1605/4000/8199), RLZ-60-00000003
(1602/1001) en RLZ-06-00000122/123 (jaarafsluiting 8000 + terugdraai op 01-01). De regelvorm volgt de bewezen feiten
van 13-09 (DebitAmount/CreditAmount aanwezig; `CreditOrDebit` op lezen gespiegeld — CreditOrDebit 1 mét CreditAmount
op RLZ-06-00000001) én het patroon uit de saldibalans-nameting (alleen passiva-/opbrengstregels klapten om): een
`NetAmount` die de NORMALE ZIJDE van de rekening volgt. ⚠️ De letterlijke RLZ-waarden per regel komen uit STAP-0 14-09
(api-verkenning "Memoriaalregels — teken per regel, STAP-0 14-09"); tot die gelezen zijn is deze fixture het model dat
het patroon van 13-09 volledig verklaart — de fix (uitsluitend DebitAmount/CreditAmount, nooit NetAmount, nooit de
code) is onafhankelijk van welke van de twee kandidaat-velden RLZ precies zo vult.

Verwachte Odoo-kant per regel = de RLZ-journaalregel (JournalEntryLines) — cent-exact; élke memoriaal in balans.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.migratie import rlz_bron, vertaling
from app.migratie.cli_replay import statusregel
from app.migratie.rapport import GROEN_ZONDER_DOEL, NIET_MEETBAAR_TEKST
from app.migratie.vertaling import Doel
from tests.migratie import test_replay as tr
from tests.migratie.test_replay import (
    DOEL,
    L_CRED,
    L_KOSTEN,
    MJ2,
    ODOO_ACCOUNTS,
    REK,
    NepClient,
    _doc,
    _jr,
    _regel,
    _run,
    _tx,
    mini_vgg,
)

NUL = Decimal("0.00")


# ---- STAP-0-fixture: de vijf memorialen van 13-09 ----------

#: AccountNumber → (ledger-id, omschrijving, AccountType) — types uit de tabel "Ongemapte RLZ-rekeningen" 13-09
LEDGERS_STAP0: dict[str, tuple[str, str, int]] = {
    "0500": (str(uuid.uuid4()), "Geplaatst aandelenkapitaal", 4),
    "1001": (str(uuid.uuid4()), "ING NL95INGB0114119295", 3),
    "1100": (str(uuid.uuid4()), "Voorraad vastgoed / panden", 3),
    "1601": (str(uuid.uuid4()), "N.t.b. vastgoed / panden", 4),
    "1602": (str(uuid.uuid4()), "RC Tupker Beheer BV", 4),
    "1605": (str(uuid.uuid4()), "Nettolonen te betalen", 4),
    "1710": (str(uuid.uuid4()), "Loonbelasting te betalen", 4),
    "4000": (str(uuid.uuid4()), "Brutosalarissen", 2),
    "7000": (str(uuid.uuid4()), "Inkopen vastgoed", 2),
    "8000": (str(uuid.uuid4()), "Omzet verkopen", 1),
    "8199": (str(uuid.uuid4()), "Diverse opbrengsten", 1),
    "7999": (str(uuid.uuid4()), "Winst", 1),
    "8999": (str(uuid.uuid4()), "Verlies", 2),
    "0509": (str(uuid.uuid4()), "Resultaat lopend boekjaar", 4),
    "4900": (str(uuid.uuid4()), "Betalingsverschillen", 2),
}
CREDIT_NORMAAL = {1, 4}  # opbrengst / passiva: NetAmount volgt de creditzijde (patroon nameting 13-09)


def _ledgers() -> list[dict]:
    return [
        {"id": lid, "AccountNumber": code, "Description": naam, "AccountType": t, "IsTotalAccount": False}
        for code, (lid, naam, t) in LEDGERS_STAP0.items()
    ]


def _mj_regel(code: str, *, debet: float = 0.0, credit: float = 0.0, omschrijving: str = "regel") -> dict:
    """Eén memoriaalregel zoals de document-vorm 'm (model 13-09) geeft: DebitAmount/CreditAmount correct, `NetAmount`
    = bedrag naar de normale zijde van de rekening (credit-normaal → credit − debet), `CreditOrDebit` gespiegeld
    (1 als het bedrag op de normale zijde staat)."""
    lid, _naam, t = LEDGERS_STAP0[code]
    normaal_credit = t in CREDIT_NORMAAL
    net = (credit - debet) if normaal_credit else (debet - credit)
    cod = 1 if net >= 0 else 2
    return {
        "id": str(uuid.uuid4()),
        "Account": {"id": lid, "AccountNumber": code},
        "Description": omschrijving,
        "DebitAmount": debet,
        "CreditAmount": credit,
        "NetAmount": net,
        "CreditOrDebit": cod,
    }


def _jr_stap0(code: str, bron_id: str, datum: str, *, debet: float = 0.0, credit: float = 0.0) -> dict:
    return _jr(LEDGERS_STAP0[code][0], bron_id, datum, debet=debet, credit=credit)


MJ_0001, MJ_0106, MJ_0038, MJ_60_3, MJ_0122, MJ_0123 = (str(uuid.uuid4()) for _ in range(6))
BOEKSTUKKEN = {
    MJ_0001: "RLZ-06-00000001",
    MJ_0106: "RLZ-06-00000106",
    MJ_0038: "RLZ-06-00000038",
    MJ_60_3: "RLZ-60-00000003",
    MJ_0122: "RLZ-06-00000122",
    MJ_0123: "RLZ-06-00000123",
}
#: (document-id, datum, totaal, regels als (code, debet, credit)) — bedragen: nameting 13-09 (0001 € 70; 106 € 175.000;
#: 038 € 4.666,67; 60-3 € 1.000; 122/123 € 502.555 op 8000 — overige 122-regels hier tot één 7000-regel vereenvoudigd)
STAP0_DOCUMENTEN: list[tuple[str, str, float, list[tuple[str, float, float]]]] = [
    (MJ_0001, "2025-07-15", 70.0, [("1001", 70.0, 0.0), ("0500", 0.0, 70.0)]),
    (MJ_0106, "2025-12-31", 175000.0, [("1100", 175000.0, 0.0), ("1601", 0.0, 175000.0)]),
    (
        MJ_0038,
        "2025-06-30",
        4666.67,
        [("4000", 4666.67, 0.0), ("1710", 0.0, 1300.0), ("1605", 0.0, 3363.07), ("8199", 0.0, 3.60)],
    ),
    (MJ_60_3, "2025-08-09", 1000.0, [("1602", 1000.0, 0.0), ("1001", 0.0, 1000.0)]),
    (MJ_0122, "2025-12-31", 502555.0, [("8000", 0.0, 502555.0), ("7000", 502555.0, 0.0)]),
    (MJ_0123, "2026-01-01", 502555.0, [("8000", 502555.0, 0.0), ("7000", 0.0, 502555.0)]),
]


def stap0_administratie(*, resultaatposten: bool = True) -> tuple[dict, dict, dict]:
    """Collecties/regels/statements met alleen de vijf memorialen (+ RLZ's resultaatposten, DocumentType 0)."""
    tr._JOURNAALPOSTEN.clear()
    tr._JR_DOCTYPE.clear()
    tr._JR_DOCTYPE.update(dict.fromkeys(BOEKSTUKKEN, 11))
    mjs = []
    regels: dict[str, list[dict]] = {}
    journaal: list[dict] = []
    for rid, datum, totaal, lijnen in STAP0_DOCUMENTEN:
        mjs.append(
            _doc(rid, BOEKSTUKKEN[rid], datum, totaal, dt=11, Description=BOEKSTUKKEN[rid], JournalEntryDiary={})
        )
        regels[rid] = [_mj_regel(code, debet=d, credit=c) for code, d, c in lijnen]
        journaal += [_jr_stap0(code, rid, datum, debet=d, credit=c) for code, d, c in lijnen]
    if resultaatposten:
        # RLZ's eigen resultaatboekingen (DocumentType 0): 7999 Winst 661.529,12 / 8999 Verlies −265.262,40 →
        # 0509 Resultaat lopend boekjaar −396.266,72 (nameting 13-09, per 31-12-2025)
        res_id = str(uuid.uuid4())
        tr._JR_DOCTYPE[res_id] = 0
        journaal += [
            _jr_stap0("7999", res_id, "2025-12-31", debet=661529.12),
            _jr_stap0("8999", res_id, "2025-12-31", credit=265262.40),
            _jr_stap0("0509", res_id, "2025-12-31", credit=396266.72),
        ]
    # Blok 9 16-09 (1001-model): de twee memorialen die rechtstreeks op 1001 boeken staan in RLZ tegenover een
    # afgeletterde bankmutatie (PaymentReferenceList → het memoriaal); zonder die mutaties zou de 1001-regel terecht op
    # de tussenrekening landen en de bankgroep rood zijn (Odoo-bank = statement lines).
    mj_0001 = next(m for m in mjs if m["id"] == MJ_0001)
    mj_60_3 = next(m for m in mjs if m["id"] == MJ_60_3)
    collecties = {
        "PurchaseInvoices": [],
        "SalesInvoices": [],
        "ManualJournals": mjs,
        "Receipts": [],
        "PaymentTransactions": [
            _tx(str(uuid.uuid4()), "00001", "2025-07-15", 70.0, refs=[(mj_0001, 70.0)], naam="Tupker Beheer"),
            _tx(str(uuid.uuid4()), "00002", "2025-08-09", -1000.0, refs=[(mj_60_3, 1000.0)], naam="Tupker Beheer"),
        ],
        "PaymentAccounts": [{"id": REK, "Name": "ING", "IBAN": "NL95INGB0114119295", "Type": 1}],
        "JournalEntryLines": journaal,
        "Ledgers": _ledgers(),
        "TaxRates": [],
    }
    return collecties, regels, {}


ODOO_STAP0 = [
    {"id": 90000 + i, "code": code, "name": naam} for i, (code, (_l, naam, _t)) in enumerate(LEDGERS_STAP0.items())
]


def _run_stap0(client: NepClient, **kw):  # noqa: ANN003, ANN202
    basis = dict(odoo_accounts=ODOO_STAP0, panden={}, doel=DOEL)
    basis.update(kw)
    return _run(client, **basis)


def _per_code(rapport) -> dict[str, dict]:  # noqa: ANN001
    uit = {}
    for r in rapport.saldibalans:
        for code in LEDGERS_STAP0:
            if f"RLZ {code} " in r["omschrijving"]:
                uit[code] = r
    return uit


# ---- punt 1: tekenfout memorialen ----------


class TestPunt1TekenMemorialen:
    def test_memoriaal_debet_credit_uitsluitend_uit_debit_creditamount(self) -> None:
        """De regel 0500 van RLZ-06-00000001 (CreditOrDebit 1 mét CreditAmount 70, NetAmount +70): credit 70 — nooit
        debet via NetAmount of de code."""
        r0500 = _mj_regel("0500", credit=70.0)
        assert r0500["CreditOrDebit"] == 1 and r0500["NetAmount"] == 70.0 and r0500["CreditAmount"] == 70.0
        assert rlz_bron.memoriaal_debet_credit(r0500) == (NUL, Decimal("70.00"))
        r1602 = _mj_regel("1602", debet=1000.0)  # passiva debet: NetAmount −1000, code 2 — debet blijft debet
        assert r1602["NetAmount"] == -1000.0 and rlz_bron.memoriaal_debet_credit(r1602) == (Decimal("1000.00"), NUL)
        assert rlz_bron.memoriaal_debet_credit({"CreditOrDebit": 1, "Amount": 5.0}) is None
        assert rlz_bron.memoriaal_debet_credit({"NetAmount": 5.0}) is None

    def test_vijf_stap0_documenten_saldibalans_cent_exact_en_in_balans(self) -> None:
        collecties, regels, statements = stap0_administratie()
        rapport = _run_stap0(NepClient(collecties, regels, statements))
        per = _per_code(rapport)
        # meetlat productie (opdracht punt 1), hier op de fixture-bedragen: geen enkel omgeklapt teken
        verwacht_je = {
            "0500": "-70.00",
            "1001": "-930.00",  # +70 (0001) − 1000 (60-3)
            "1100": "175000.00",
            "1601": "-175000.00",
            "1602": "1000.00",
            "1605": "-3363.07",
            "1710": "-1300.00",
            "4000": "4666.67",
            "8199": "-3.60",
            "8000": "-502555.00",  # 122 credit op 31-12; 123 draait 'm op 01-01 terug
            "7000": "502555.00",
        }
        for code, w in verwacht_je.items():
            rij = per[code]
            assert rij["rlz_jaareinde"] == Decimal(w), (code, rij)
            if code == "1001":
                # blok 9 16-09: de bank telt op GROEPSniveau — RLZ 1001 (memoriaal) staat tegenover de Odoo-statement
                # line; de memoriaalregel zelf gaat via het 1001-model naar outstanding (nettoot binnen de bankgroep)
                assert rij["groep"] == "bank" and rij["odoo_jaareinde"] == 0
                continue
            assert rij["odoo_jaareinde"] == Decimal(w), (code, rij)
            assert rij["verschil_jaareinde_geschoond"] == 0 and rij["verschil_tot_geschoond"] == 0, (code, rij)
        bank = next(g for g in rapport.afletter_groepen if g["groep"] == "bank")
        assert bank["verschil_jaareinde"] == 0 and bank["verschil_tot"] == 0 and bank["rest"] == []
        assert rapport.model_1001["tellers"]["gekoppeld"] == 2 == rapport.model_1001["tellers"]["via_koppeling"]
        assert per["8000"]["rlz_tot"] == 0 == per["8000"]["odoo_tot"]  # ná de terugdraai op 01-01
        assert rapport.tellers["memoriaal_uit_balans"] == 0 and rapport.uit_balans == []
        for m in rapport.moves:
            if m.move_type != "entry":
                continue  # blok 9: de fixture draagt nu ook statement lines (geen line_ids)
            regels_m = m.vals["line_ids"]
            som = sum((rv["debit"] - rv["credit"] for _, _, rv in regels_m), NUL)
            assert som == 0, (m.boekstuk, regels_m)
        assert rapport.oordeel == "GROEN", rapport.als_markdown()
        # de Odoo-move van 0001: 0500 credit 70 / 1001 debet 70 — exact de RLZ-journaalregels
        m0001 = next(m for m in rapport.moves if m.boekstuk == "RLZ-06-00000001")
        kant = {rv["account_id"]: (rv["debit"], rv["credit"]) for _, _, rv in m0001.vals["line_ids"]}
        id_0500 = next(a["id"] for a in ODOO_STAP0 if a["code"] == "0500")
        assert kant[id_0500] == (NUL, Decimal("70.00"))
        # de 1001-regel: debet 70 blijft debet 70, bestemming = outstanding BNK1 (blok 9; rekening in Odoo nog niet
        # ingesteld → account_id None + KLIKPUNT, nooit de bankrekening zelf)
        assert kant[None] == (Decimal("70.00"), NUL)
        rij_1001 = next(r for r in rapport.model_1001["regels"] if r["boekstuk"] == "RLZ-06-00000001")
        assert rij_1001["uitkomst"] == "gekoppeld" and rij_1001["mutatie"] == "00001"

    def test_oude_vertaling_op_netamount_zou_passiva_en_opbrengst_omklappen(self) -> None:
        """Regressiebewijs van de oorzaak: NetAmount 'positief = debet' klapt precies 0500/1601/1602/1710/8199/8000 om
        en laat 1100/4000/7000 heel — het patroon van de nameting 13-09."""
        for code, debet, credit in [("0500", 0.0, 70.0), ("1601", 0.0, 175000.0), ("1602", 1000.0, 0.0)]:
            r = _mj_regel(code, debet=debet, credit=credit)
            oud = vertaling._orienteer_bedrag(Decimal(str(r["NetAmount"])), "entry")
            assert oud != rlz_bron.memoriaal_debet_credit(r), code  # de oude route klapt om
        for code, debet, credit in [("1100", 175000.0, 0.0), ("4000", 4666.67, 0.0), ("7000", 502555.0, 0.0)]:
            r = _mj_regel(code, debet=debet, credit=credit)
            oud = vertaling._orienteer_bedrag(Decimal(str(r["NetAmount"])), "entry")
            assert oud == rlz_bron.memoriaal_debet_credit(r), code  # activa/kosten bleven correct

    def test_memoriaal_uit_balans_is_teller_en_rood_nooit_stil(self) -> None:
        collecties, regels, statements = stap0_administratie()
        regels[MJ_0106][1]["CreditAmount"] = 174000.0  # RLZ zou dit nooit geven — de harde controle moet 'm vangen
        rapport = _run_stap0(NepClient(collecties, regels, statements))
        assert rapport.tellers["memoriaal_uit_balans"] == 1 and rapport.oordeel == "ROOD"
        [rij] = rapport.uit_balans
        assert rij["boekstuk"] == "RLZ-06-00000106" and rij["uit_balans"] == Decimal("1000.00")
        m = next(x for x in rapport.moves if x.boekstuk == "RLZ-06-00000106")
        assert m.status == vertaling.STATUS_NIET and "memoriaal uit balans: Σ debet − Σ credit" in m.reden
        md = rapport.als_markdown()
        assert "memoriaal uit balans 1" in md and "#### Memoriaal uit balans — 1" in md
        assert "1 memoriaal uit balans" in statusregel(rapport)

    def test_memoriaalregel_zonder_debit_creditamount_nooit_via_de_code(self) -> None:
        collecties, regels, statements = stap0_administratie()
        regels[MJ_0001] = [
            {"id": "a", "Account": {"id": LEDGERS_STAP0["1001"][0]}, "CreditOrDebit": 1, "Amount": 70.0},
            {"id": "b", "Account": {"id": LEDGERS_STAP0["0500"][0]}, "CreditOrDebit": 2, "Amount": 70.0},
        ]
        rapport = _run_stap0(NepClient(collecties, regels, statements))
        m = next(x for x in rapport.moves if x.boekstuk == "RLZ-06-00000001")
        assert m.status == vertaling.STATUS_NIET
        assert "2 memoriaalregel(s) zonder DebitAmount/CreditAmount" in m.reden and "CreditOrDebit-code" in m.reden
        assert all(rv["debit"] == 0 and rv["credit"] == 0 for _, _, rv in m.vals["line_ids"])  # geen gok
        assert rapport.oordeel == "ROOD"


# ---- punt 2: volledigheidstoets op EventID ----------


class TestPunt2VolledigheidEventID:
    def test_documentposten_per_eventid_en_betalingsposten_apart(self) -> None:
        collecties, regels, statements = mini_vgg()
        # inkoop (1): documentpost = EventID 71; RLZ typeert ook de betaling naar DocumentType 1 mét een andere code
        for jr in collecties["JournalEntryLines"]:
            if jr["JournalEntry"]["EventID"] == 91 and jr["Account"]["id"] in (L_CRED,):
                jr["JournalEntry"]["DocumentType"] = 1
                jr["JournalEntry"]["EventID"] = 72
        rapport = _run(NepClient(collecties, regels, statements))
        per_dt = {x["documenttype"]: x for x in rapport.journaal["per_documenttype"]}
        inkoop = per_dt[1]
        assert inkoop["documentposten"] == 1 and inkoop["documenten_geboekt"] == 1
        assert inkoop["overige_posten"] == 1 and inkoop["oordeel"].startswith("sluit (1 documentposten = 1 geboekt")
        assert {(e["eventid"], e["soort"]) for e in inkoop["per_eventid"]} == {
            (71, "documentpost"),
            (72, "betalings-/afletter-/correctiepost"),
        }
        # memoriaal (11): EventID 21 = documentpost (nazorg 14-09) → sluit
        assert per_dt[11]["documentposten"] == 3 and per_dt[11]["oordeel"].startswith("sluit (3 documentposten = 3")
        md = rapport.als_markdown()
        assert "Journaalposten per EventID (soortcode) per DocumentType" in md
        memo_rij = next(r for r in md.splitlines() if r.startswith("| memoriaal (11) |"))
        assert "sluit (3 documentposten" in memo_rij and "niet uitvoerbaar" not in memo_rij

    def test_memoriaal_eventid_22_is_overig_en_bank_direct_telt_hulzen_apart(self) -> None:
        """Productienameting 14-09: memoriaal 21 = 228 documentposten (= 228 geboekt) + 22 = 214 posten zónder
        document; bank-direct 240 = 54 posten = 9 documenten + 45 systeemhulzen. De toets telt documenten en benoemt
        hulzen apart."""
        collecties, regels, statements = mini_vgg()
        extra = dict(next(jr for jr in collecties["JournalEntryLines"] if jr["JournalEntry"]["DocumentType"] == 11))
        extra["JournalEntry"] = {
            **extra["JournalEntry"],
            "id": str(uuid.uuid4()),
            "EventID": rlz_bron.EVENTID_MEMORIAAL_OVERIG,
        }
        collecties["JournalEntryLines"].append(extra)
        rapport = _run(NepClient(collecties, regels, statements))
        per_dt = {x["documenttype"]: x for x in rapport.journaal["per_documenttype"]}
        memo = per_dt[11]
        assert memo["documentposten"] == 3 and memo["overige_posten"] == 1
        assert memo["oordeel"] == "sluit (3 documentposten = 3 geboekt; betalings-/afletterposten 1)"
        assert {(e["eventid"], e["soort"]) for e in memo["per_eventid"]} == {
            (21, "documentpost"),
            (22, "betalings-/afletter-/correctiepost"),
        }
        bank = per_dt[19]
        assert bank["documentposten"] == 4 and bank["documenten_geboekt"] == 3 and rapport.tellers["huls"] == 1
        assert bank["oordeel"] == "sluit (4 documentposten = 3 geboekt + 1 systeemhulzen; betalings-/afletterposten 0)"
        # zonder de huls-post: het verschil wordt tegen geboekt + hulzen benoemd, nooit tegen het ruwe aantal
        collecties["JournalEntryLines"] = [
            jr
            for jr in collecties["JournalEntryLines"]
            if jr["JournalEntry"]["DocumentType"] != 19 or jr["DebitAmount"] or jr["CreditAmount"]
        ]
        rapport = _run(NepClient(collecties, regels, statements))
        bank = next(x for x in rapport.journaal["per_documenttype"] if x["documenttype"] == 19)
        assert bank["oordeel"].startswith("VERSCHIL -1: 3 documentposten (EventID 240) ≠ 3 geboekt + 1 systeemhulzen")

    def test_onbekend_documenttype_blijft_niet_uitvoerbaar_met_codes(self) -> None:
        collecties, regels, statements = mini_vgg()
        jr = next(x for x in collecties["JournalEntryLines"] if x["JournalEntry"]["DocumentType"] == 11)
        jr["JournalEntry"]["DocumentType"] = 12
        jr["JournalEntry"]["EventID"] = 61
        rapport = _run(NepClient(collecties, regels, statements))
        per_dt = {x["documenttype"]: x for x in rapport.journaal["per_documenttype"]}
        assert per_dt[12]["documentposten"] is None and "gevonden codes: 61" in per_dt[12]["oordeel"]
        assert per_dt[12]["oordeel"].startswith("toets niet uitvoerbaar met deze API")
        assert "toets niet uitvoerbaar" in rapport.als_markdown()

    def test_verschil_wordt_benoemd_niet_het_ruwe_aantal(self) -> None:
        collecties, regels, statements = mini_vgg()
        extra = dict(collecties["JournalEntryLines"][12])  # een tweede inkoop-documentpost zonder document
        extra["JournalEntry"] = {**extra["JournalEntry"], "id": str(uuid.uuid4())}
        collecties["JournalEntryLines"].append(extra)
        rapport = _run(NepClient(collecties, regels, statements))
        inkoop = next(x for x in rapport.journaal["per_documenttype"] if x["documenttype"] == 1)
        assert inkoop["documentposten"] == 2 and inkoop["oordeel"].startswith(
            "VERSCHIL +1: 2 documentposten (EventID 71)"
        )


# ---- punt 3: RLZ-resultaatposten ----------


class TestPunt3Resultaatposten:
    def test_documenttype_0_buiten_de_toets_met_sluitcontrole(self) -> None:
        collecties, regels, statements = stap0_administratie()
        rapport = _run_stap0(NepClient(collecties, regels, statements))
        per = _per_code(rapport)
        assert "7999" not in per and "8999" not in per and "0509" not in per  # nooit als verschil
        rp = rapport.resultaatposten
        assert rp["posten"] == 1 and rp["regels"] == 3 and rp["sluit"] is True
        assert rp["som_jaareinde"] == 0 and rp["som_tot"] == 0
        d3 = rp["sluitcontrole_7999_8999_0509"]
        assert d3["7999_plus_8999_jaareinde"] == Decimal("396266.72") == d3["min_0509_jaareinde"] and d3["sluit"]
        assert rapport.resultaat_sluit and rapport.oordeel == "GROEN"
        md = rapport.als_markdown()
        assert "#### RLZ-resultaatposten (niet gemigreerd, Odoo berekent zelf)" in md and "sluitcontrole GROEN" in md
        assert "resultaatposten sluiten" in md
        per_dt = {x["documenttype"]: x for x in rapport.journaal["per_documenttype"]}
        assert per_dt[0]["oordeel"].startswith("RLZ-resultaatposten — niet gemigreerd")

    def test_onvolledig_gelezen_resultaatposten_is_rood(self) -> None:
        collecties, regels, statements = stap0_administratie()
        collecties["JournalEntryLines"] = [
            jr for jr in collecties["JournalEntryLines"] if jr["Account"]["id"] != LEDGERS_STAP0["8999"][0]
        ]
        rapport = _run_stap0(NepClient(collecties, regels, statements))
        assert rapport.resultaatposten["sluit"] is False and rapport.resultaat_sluit is False
        assert rapport.oordeel == "ROOD" and "resultaatposten SLUITEN NIET" in rapport.als_markdown()
        assert "resultaatposten sluiten NIET" in statusregel(rapport)


# ---- punt 4: betalingsverschil ----------


class TestPunt4Betalingsverschil:
    def test_write_off_op_4900_maakt_open_post_en_saldibalans_0(self) -> None:
        collecties, regels, statements = mini_vgg()
        # casus RLZ-04-00000073: factuur 230,99 (fixture) betaald met 231,01; RLZ boekt 0,02 op 4900 en toont open 0
        lid_4900 = LEDGERS_STAP0["4900"][0]
        collecties["Ledgers"].append(
            {"id": lid_4900, "AccountNumber": "4900", "Description": "Betalingsverschillen", "AccountType": 2}
        )
        collecties["PaymentTransactions"][3]["PaymentReferenceList"][0]["Amount"] = 231.01
        collecties["PaymentTransactions"][3]["Amount"] = -231.01
        pt3 = collecties["PaymentTransactions"][3]["id"]
        for jr in collecties["JournalEntryLines"]:
            if jr["JournalEntry"]["id"] == tr._JOURNAALPOSTEN[pt3]:
                if jr["DebitAmount"]:
                    jr["DebitAmount"] = 231.01
                else:
                    jr["CreditAmount"] = 231.01
        collecties["JournalEntryLines"] += [
            _jr(lid_4900, "wo", "2025-07-21", debet=0.02),
            _jr(L_CRED, "wo", "2025-07-21", credit=0.02),
        ]
        rapport = _run(
            NepClient(collecties, regels, statements),
            odoo_accounts=[*ODOO_ACCOUNTS, {"id": 4900, "code": "4900", "name": "Betalingsverschillen"}],
        )
        [wo] = rapport.betalingsverschillen
        assert wo["write_off"] == Decimal("0.02") and wo["rekening"] == "4900" and wo["rlz_ledger_id"] == lid_4900
        assert not [r for r in rapport.open_posten if r["boekstuk"] == "RLZ-04-00000100"]  # open berekend 0,00
        per = {r["rekening"]: r for r in rapport.saldibalans}
        assert per["4900"]["rlz_tot"] == Decimal("0.02") == per["4900"]["odoo_tot"] and per["4900"]["verschil_tot"] == 0
        assert per["1600"]["verschil_tot"] == 0 and rapport.oordeel == "GROEN", rapport.als_markdown()
        assert "Betalingsverschillen (blok 7d punt 4" in rapport.als_markdown() and "Σ € 0,02" in rapport.als_markdown()

    def test_zonder_koppeling_geen_write_off(self) -> None:
        """RLZ open 0 zónder enige betaling is geen betalingsverschil maar een onverklaarde afboeking — zichtbaar."""
        collecties, regels, statements = mini_vgg()
        collecties["PaymentTransactions"][3]["PaymentReferenceList"] = []
        rapport = _run(NepClient(collecties, regels, statements))
        rij = next(r for r in rapport.open_posten if r["boekstuk"] == "RLZ-04-00000100")
        assert rapport.betalingsverschillen == [] and "zonder gekoppelde bankmutatie" in rij["oorzaak"]


# ---- punt 5: GROEN ZONDER DOEL ----------


class TestPunt5GroenZonderDoel:
    def test_zonder_doelkoppeling_derde_stand(self) -> None:
        collecties, regels, statements = mini_vgg()
        rapport = _run(NepClient(collecties, regels, statements), doel=Doel(), odoo_accounts=[])
        assert rapport.doel_afwezig is True and rapport.groen is False and rapport.groen_zonder_doel is True
        assert rapport.oordeel.startswith(GROEN_ZONDER_DOEL) and NIET_MEETBAAR_TEKST in rapport.oordeel
        assert rapport.tellers["niet_vertaalbaar_doel"] == len(rapport.niet_vertaalbaar) > 0
        assert rapport.tellers["niet_vertaalbaar_overig"] == 0
        assert all(g["stand"] == NIET_MEETBAAR_TEKST and g["verschil_tot"] is None for g in rapport.afletter_groepen)
        assert all(p["controle"] == NIET_MEETBAAR_TEKST and p["marge"] is None for p in rapport.per_pand)
        assert statusregel(rapport).startswith(f"UITKOMST: {GROEN_ZONDER_DOEL}")
        md = rapport.als_markdown()
        assert "telt nu NIET" in md and "GO-eis bij SCHRIJF c" in md

    def test_doelonafhankelijke_fout_blijft_rood_ook_zonder_doel(self) -> None:
        collecties, regels, statements = mini_vgg()
        regels[MJ2][1]["CreditAmount"] = 149000.0  # memoriaal uit balans
        rapport = _run(NepClient(collecties, regels, statements), doel=Doel(), odoo_accounts=[])
        assert rapport.doel_afwezig and rapport.groen_zonder_doel is False and rapport.oordeel == "ROOD"
        assert rapport.tellers["niet_vertaalbaar_overig"] == 1

    def test_met_doel_vervalt_de_stand_automatisch(self) -> None:
        collecties, regels, statements = mini_vgg()
        rapport = _run(NepClient(collecties, regels, statements))
        assert rapport.doel_afwezig is False and rapport.oordeel == "GROEN"
        assert all(g["stand"] is None for g in rapport.afletter_groepen)


# ---- punt 6: partner-blokkade ----------


class TestPunt6PartnerGeblokkeerd:
    def test_geblokkeerd_concept_telt_niet_als_rood_in_groen_zonder_doel(self) -> None:
        collecties, regels, statements = mini_vgg()
        los_id = str(uuid.uuid4())
        # open in RLZ (geen betaling): BaseRemainingAmount = totaal, zodat de open-postentoets sluit
        collecties["PurchaseInvoices"].append(
            _doc(los_id, "RLZ-25-00000111", "2025-09-02", 795.0, dt=1, BaseRemainingAmount=795.0)
        )
        regels[los_id] = [_regel(L_KOSTEN, net=795.0)]
        collecties["JournalEntryLines"] += [
            _jr(L_KOSTEN, los_id, "2025-09-02", debet=795.0),
            _jr(L_CRED, los_id, "2025-09-02", credit=795.0),
        ]
        rapport = _run(NepClient(collecties, regels, statements), doel=Doel(), odoo_accounts=[])
        m = next(x for x in rapport.moves if x.rlz_id == los_id)
        assert m.status == vertaling.STATUS_NIET  # ongemapt (geen doel) + partner
        assert vertaling.BLOKKADE_PARTNER in m.reden or vertaling.PARTNER_ONBEKEND_REDEN in m.reden
        assert rapport.tellers["geblokkeerd_partner"] == 1 and [g["boekstuk"] for g in rapport.geblokkeerd] == [
            "RLZ-25-00000111"
        ]
        assert rapport.groen_zonder_doel is True, rapport.als_markdown()
        assert "1 geblokkeerd (partner)" in statusregel(rapport)
        assert "BESLISPUNT PETER" not in rapport.als_markdown()


@pytest.mark.parametrize("code", ["0500", "1601", "1602", "1710", "8199", "8000"])
def test_credit_normaal_fixture_klapt_netamount_om(code: str) -> None:
    """Fixture-zelftoets: op de omgeklapte rekeningen van 13-09 wijst NetAmount de verkeerde kant op."""
    r = _mj_regel(code, debet=10.0)
    assert r["NetAmount"] == -10.0 and rlz_bron.memoriaal_debet_credit(r) == (Decimal("10.00"), NUL)
