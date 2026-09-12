"""Blok 6 run 2 VGG (12-09): replay-motor dry-run getest zonder RLZ/Odoo/DB — dict-client (stijl test_schoonlijst).

Mini-VGG: 2 notaris-aankopen (memoriaal RLZ-06), 1 aanbetaling, 1 vaste-lasten-inkoop, 1 verkoopfactuur notaris, 3 bank-
directe boekingen (DocumentType 19, RLZ-09) + 7 bankregels mét PaymentReferenceList waarvan één deelkoppeling (2 × op de
verkoopfactuur), 1 concept, 1 systeemhuls + open bankregel, JournalEntryLines die sluiten → saldibalans verschil 0,00 =
GROEN. Varianten: ongemapte rekening → niet-vertaalbaar + exit 1; anker deterministisch; BookDate-terugval zichtbaar;
btw-regel → teller; $expand-terugval zichtbaar; 403 op een route = fout + ROOD; JSON-roundtrip."""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.migratie import replay, rlz_bron, vertaling
from app.migratie.vertaling import Doel, PandToewijzing, RolRekeningen, anker_voor, ref_voor
from app.rlz.client import RlzApiError

ADMIN = uuid.UUID("cc07e461-0000-4000-8000-000000000001")
RLZ_ADMIN = "f6d4770f-53fe-41fa-8b35-b675f406841c"
TOT = date(2026, 9, 1)

# ledgers (RLZ) — AccountNumber/Description/AccountType (1 opbrengst, 2 kosten, 3 activa, 4 passiva)
L_PANDEN = str(uuid.uuid4())
L_BANK = str(uuid.uuid4())
L_NOTARIS = str(uuid.uuid4())
L_KOSTEN = str(uuid.uuid4())
L_CRED = str(uuid.uuid4())
L_DEB = str(uuid.uuid4())
L_OMZET = str(uuid.uuid4())
LEDGERS = [
    {"id": L_PANDEN, "AccountNumber": "0300", "Description": "Panden", "AccountType": 3, "IsTotalAccount": False},
    {"id": L_BANK, "AccountNumber": "1100", "Description": "Bank", "AccountType": 3, "IsTotalAccount": False},
    {
        "id": L_NOTARIS,
        "AccountNumber": "1650",
        "Description": "Notaris derdengelden",
        "AccountType": 4,
        "IsTotalAccount": False,
    },
    {
        "id": L_KOSTEN,
        "AccountNumber": "4400",
        "Description": "Vaste lasten panden",
        "AccountType": 2,
        "IsTotalAccount": False,
    },
    {"id": L_CRED, "AccountNumber": "1600", "Description": "Crediteuren", "AccountType": 4, "IsTotalAccount": False},
    {"id": L_DEB, "AccountNumber": "1300", "Description": "Debiteuren", "AccountType": 3, "IsTotalAccount": False},
    {
        "id": L_OMZET,
        "AccountNumber": "8000",
        "Description": "Verkoop panden",
        "AccountType": 1,
        "IsTotalAccount": False,
    },
]
ODOO_ACCOUNTS = [
    {"id": 300, "code": "0300", "name": "Panden (oud)"},
    {"id": 1100, "code": "1100", "name": "Bank"},
    {"id": 1650, "code": "1650", "name": "Notaris"},
    {"id": 4400, "code": "4400", "name": "Vaste lasten"},
    {"id": 1600, "code": "1600", "name": "Crediteuren"},
    {"id": 1300, "code": "1300", "name": "Debiteuren"},
    {"id": 8000, "code": "8000", "name": "Verkoop (oud)"},
]
ROLLEN = RolRekeningen(voorraad_panden=3000, vooruitbetaald_voorraad=3010, opbrengst_panden=8010, kostprijs_panden=7000)
REK = str(uuid.uuid4())
DOEL = Doel(
    company_id=6,
    journal_sale_id=48,
    journal_purchase_id=49,
    journal_general_id=50,
    journal_bank_id=53,
    analytic_plan_id=1,
    rekening_crediteuren_id=1600,
    rekening_debiteuren_id=1300,
    rekening_bank_ids={REK: 1100},
)

MJ1, MJ2, MJ3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
PI1, PI_CONCEPT, SI1 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
BD1, BD2, BD3, HULS = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
PT = [str(uuid.uuid4()) for _ in range(7)]
NOTARIS = {"id": str(uuid.uuid4()), "Name": "Notaris O."}
VVE = {"id": str(uuid.uuid4()), "Name": "V. VvE Beheer B.V.", "ChamberOfCommerceNumber": "12345678"}


def _doc(rlz_id: str, boekstuk: str, datum: str, bedrag: float, *, status: int = 3, dt: int, **extra) -> dict:  # noqa: ANN003
    return {
        "id": rlz_id,
        "ReceiptNumber": boekstuk,
        "BaseInvoiceAmount": bedrag,
        "BaseRemainingAmount": 0.0,
        "Date": f"{datum}T00:00:00",
        "BookDate": f"{datum}T00:00:00",
        "Status": status,
        "DocumentType": dt,
        **extra,
    }


def _regel(
    ledger: str,
    *,
    debet: float | None = None,
    credit: float | None = None,
    net: float | None = None,
    omschrijving: str = "regel",
    **extra,
) -> dict:  # noqa: ANN003
    r: dict = {"id": str(uuid.uuid4()), "Account": {"id": ledger}, "Description": omschrijving, **extra}
    if net is not None:
        r["NetAmount"] = net
        r["TaxAmount"] = 0.0
    else:
        r["DebitAmount"] = debet or 0.0
        r["CreditAmount"] = credit or 0.0
    return r


def _tx(
    rlz_id: str,
    nr: str,
    datum: str,
    bedrag: float,
    *,
    refs: list[tuple[dict, float]] = (),
    open_bedrag: float = 0.0,
    naam: str = "K.V.",
) -> dict:
    return {
        "id": rlz_id,
        "TransactionId": nr,
        "BookDate": f"{datum}T00:00:00",
        "Amount": bedrag,
        "OpenAmount": open_bedrag,
        "IsComplete": open_bedrag == 0,
        "Name": naam,
        "CounterAccount": "NL91ABNA0417164300",
        "Reference": "Aanbetaling volgens afspraak All\nard Piersonlaan 20, Den Haag",
        "PaymentAccount": {"id": REK, "Name": "Betaalrekening"},
        "PaymentReferenceList": [
            {"id": str(uuid.uuid4()), "Sequence": i + 1, "Amount": a, "Document": d} for i, (d, a) in enumerate(refs)
        ],
    }


def _jr(ledger: str, bron_id: str, datum: str, *, debet: float = 0.0, credit: float = 0.0) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "Account": {"id": ledger},
        "DebitAmount": debet,
        "CreditAmount": credit,
        "JournalEntry": {"id": str(uuid.uuid4()), "BookDate": f"{datum}T00:00:00", "EventID": bron_id},
    }


def mini_vgg() -> tuple[dict[str, list[dict]], dict[str, list[dict]], dict[str, list[dict]]]:
    """(collecties, regels per document-id, statements per rekening-id)."""
    mj1 = _doc(
        MJ1,
        "RLZ-06-00000026",
        "2025-07-10",
        200000.0,
        dt=11,
        Description="Aankoop Gustaaf Gelderstraat 60\nte Almere, ons dossier: 2025.07",
        JournalEntryDiary={"Name": "Memoriaal"},
    )
    mj2 = _doc(
        MJ2,
        "RLZ-06-00000074",
        "2025-08-05",
        150000.0,
        dt=11,
        Description="Aankoop Rhijnauwensingel 93 Rotterdam",
        JournalEntryDiary={"Name": "Memoriaal"},
    )
    mj3 = _doc(
        MJ3,
        "RLZ-06-00000030",
        "2025-07-15",
        20000.0,
        dt=11,
        Description="Aanbetaling Gustaaf Gelderstraat 60",
        JournalEntryDiary={"Name": "Memoriaal"},
    )
    pi1 = _doc(
        PI1,
        "RLZ-04-00000100",
        "2025-07-20",
        230.99,
        status=3,
        dt=1,
        Entity=VVE,
        Description="Vaste lasten: Gelderstraat 60 maand juli",
        Reference="25010051",
        DueDate="2025-08-03T00:00:00",
    )
    pi_c = _doc(PI_CONCEPT, "RLZ-04-00000875", "2026-09-08", 750.0, status=1, dt=1, Description="Ingescand document")
    si1 = _doc(
        SI1,
        "RLZ-01-00000010",
        "2025-07-25",
        260000.0,
        status=3,
        dt=10,
        Entity=NOTARIS,
        Description="Overdracht Gustaaf Gelderstraat 60 te Almere, ons dossier: 2025.0787 58.01",
    )
    bd1 = _doc(BD1, "RLZ-09-00000500", "2025-07-10", -200000.0, dt=19, IsSystemGenerated=False)
    bd2 = _doc(BD2, "RLZ-09-00000600", "2025-08-05", -150000.0, dt=19, IsSystemGenerated=False)
    bd3 = _doc(BD3, "RLZ-09-00000510", "2025-07-15", -20000.0, dt=19, IsSystemGenerated=False)
    huls = _doc(HULS, "RLZ-09-00001177", "2026-09-09", -500.0, status=1, dt=19, IsSystemGenerated=True)
    huls_ref = {
        "id": HULS,
        "ReceiptNumber": "RLZ-09-00001177",
        "IsSystemGenerated": True,
        "Status": 1,
        "DocumentType": 19,
    }
    collecties = {
        "PurchaseInvoices": [pi1, pi_c],
        "SalesInvoices": [si1],
        "ManualJournals": [mj1, mj2, mj3],
        "Receipts": [pi1, si1, bd1, bd2, bd3, huls],  # unie-collectie zoals op VGG
        "PaymentTransactions": [
            _tx(PT[0], "00100", "2025-07-10", -200000.0, refs=[(bd1, 200000.0)]),
            _tx(PT[1], "00101", "2025-08-05", -150000.0, refs=[(bd2, 150000.0)]),
            _tx(PT[2], "00102", "2025-07-15", -20000.0, refs=[(bd3, 20000.0)]),
            _tx(PT[3], "00103", "2025-07-21", -230.99, refs=[(pi1, 230.99)], naam="V.V.B."),
            _tx(PT[4], "00104", "2025-07-28", 200000.0, refs=[(si1, 200000.0)], naam="N.O."),  # deelkoppeling
            _tx(PT[5], "00105", "2025-08-10", 60000.0, refs=[(si1, 60000.0)], naam="N.O."),
            _tx(PT[6], "00106", "2026-09-09", -500.0, refs=[(huls_ref, 500.0)], open_bedrag=-500.0),
        ],
        "PaymentAccounts": [{"id": REK, "Name": "Betaalrekening", "IBAN": "NL20INGB0001234567", "Type": 1}],
        "JournalEntryLines": [
            _jr(L_PANDEN, MJ1, "2025-07-10", debet=200000.0),
            _jr(L_NOTARIS, MJ1, "2025-07-10", credit=200000.0),
            _jr(L_PANDEN, MJ2, "2025-08-05", debet=150000.0),
            _jr(L_NOTARIS, MJ2, "2025-08-05", credit=150000.0),
            _jr(L_PANDEN, MJ3, "2025-07-15", debet=20000.0),
            _jr(L_NOTARIS, MJ3, "2025-07-15", credit=20000.0),
            _jr(L_NOTARIS, BD1, "2025-07-10", debet=200000.0),
            _jr(L_BANK, BD1, "2025-07-10", credit=200000.0),
            _jr(L_NOTARIS, BD2, "2025-08-05", debet=150000.0),
            _jr(L_BANK, BD2, "2025-08-05", credit=150000.0),
            _jr(L_NOTARIS, BD3, "2025-07-15", debet=20000.0),
            _jr(L_BANK, BD3, "2025-07-15", credit=20000.0),
            _jr(L_KOSTEN, PI1, "2025-07-20", debet=230.99),
            _jr(L_CRED, PI1, "2025-07-20", credit=230.99),
            _jr(L_CRED, PT[3], "2025-07-21", debet=230.99),
            _jr(L_BANK, PT[3], "2025-07-21", credit=230.99),
            _jr(L_DEB, SI1, "2025-07-25", debet=260000.0),
            _jr(L_OMZET, SI1, "2025-07-25", credit=260000.0),
            _jr(L_BANK, PT[4], "2025-07-28", debet=200000.0),
            _jr(L_DEB, PT[4], "2025-07-28", credit=200000.0),
            _jr(L_BANK, PT[5], "2025-08-10", debet=60000.0),
            _jr(L_DEB, PT[5], "2025-08-10", credit=60000.0),
        ],
        "Ledgers": LEDGERS,
        "TaxRates": [],
    }
    regels = {
        MJ1: [
            _regel(L_PANDEN, debet=200000.0, omschrijving="Koopsom"),
            _regel(L_NOTARIS, credit=200000.0, omschrijving="Notaris"),
        ],
        MJ2: [_regel(L_PANDEN, debet=150000.0), _regel(L_NOTARIS, credit=150000.0)],
        MJ3: [_regel(L_PANDEN, debet=20000.0, omschrijving="Aanbetaling"), _regel(L_NOTARIS, credit=20000.0)],
        PI1: [_regel(L_KOSTEN, net=230.99, omschrijving="Vaste lasten juli")],
        SI1: [_regel(L_OMZET, net=260000.0, omschrijving="Koopsom overdracht")],
        BD1: [_regel(L_NOTARIS, net=200000.0)],
        BD2: [_regel(L_NOTARIS, net=150000.0)],
        BD3: [_regel(L_NOTARIS, net=20000.0)],
    }
    statements = {
        REK: [
            {
                "id": str(uuid.uuid4()),
                "Number": "7",
                "Date": "2025-07-31T00:00:00",
                "StartBalance": 500000.0,
                "EndBalance": 479769.01,
            },
            {
                "id": str(uuid.uuid4()),
                "Number": "8",
                "Date": "2025-08-31T00:00:00",
                "StartBalance": 479769.01,
                "EndBalance": 389769.01,
            },
            {"id": str(uuid.uuid4()), "Number": "99999999", "Date": "2070-01-01T00:00:00"},
        ]
    }
    return collecties, regels, statements


PANDEN = {
    uuid.UUID(MJ1): PandToewijzing("gelderstraat-60", "Gustaaf Gelderstraat 60, Almere", "aankoop", "hoog", "voorstel"),
    uuid.UUID(MJ2): PandToewijzing(
        "rhijnauwensingel-93", "Rhijnauwensingel 93, Rotterdam", "aankoop", "midden", "voorstel"
    ),
    uuid.UUID(MJ3): PandToewijzing(
        "gelderstraat-60", "Gustaaf Gelderstraat 60, Almere", "aanbetaling", "midden", "mens"
    ),
    uuid.UUID(PI1): PandToewijzing(
        "gelderstraat-60", "Gustaaf Gelderstraat 60, Almere", "vaste_lasten", "hoog", "voorstel"
    ),
    uuid.UUID(SI1): PandToewijzing("gelderstraat-60", "Gustaaf Gelderstraat 60, Almere", "verkoop", "hoog", "mens"),
}


class NepClient:
    """Dict-client: collecties gepagineerd; `X/{id}/Lines` uit `regels`; `PaymentAccounts/{id}/Statements` uit
    `statements`; `fouten` per pad; `expand_weigeren` per pad → 400 bij $expand. Registreert élke GET."""

    def __init__(self, collecties, regels, statements, *, fouten=None, expand_weigeren=None) -> None:  # noqa: ANN001
        self.collecties, self.regels, self.statements = collecties, regels, statements
        self.fouten = fouten or {}
        self.expand_weigeren = expand_weigeren or set()
        self.calls: list[tuple[str, dict]] = []
        self.gesloten = False

    def get(self, path: str, *, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((path, params))
        if path in self.fouten:
            raise self.fouten[path]
        delen = path.split("/")
        if len(delen) == 3 and delen[2] == "Lines":
            if delen[1] not in self.regels:
                raise RlzApiError(404, "GET", path, "_NotFound")
            return {"value": self.regels[delen[1]]}
        if len(delen) == 3 and delen[0] == "PaymentAccounts" and delen[2] == "Statements":
            rijen = self.statements.get(delen[1], [])
        elif path in self.collecties:
            if "$expand" in params and path in self.expand_weigeren:
                raise RlzApiError(400, "GET", path, "expand niet ondersteund")
            rijen = self.collecties[path]
        else:
            raise RlzApiError(404, "GET", path, "_NotFound")
        skip = int(params.get("$skip", 0))
        top = int(params.get("$top", len(rijen) or 1))
        return {"value": rijen[skip : skip + top]}

    def close(self) -> None:
        self.gesloten = True


def _run(client: NepClient, **kw):  # noqa: ANN003, ANN202
    basis = dict(
        client=client,
        tot=TOT,
        doel=DOEL,
        odoo_accounts=ODOO_ACCOUNTS,
        rollen=ROLLEN,
        panden=PANDEN,
        administratie_naam="Vastgoedgroep Nederland B.V.",
        rlz_admin_id=RLZ_ADMIN,
    )
    basis.update(kw)
    return replay.dry_run(ADMIN, **basis)


# ---- ankers ----------------------------------------------------------------


class TestAnker:
    def test_deterministisch_en_per_administratie(self) -> None:
        a = anker_voor(ADMIN, MJ1)
        assert a == anker_voor(str(ADMIN), MJ1) and a.version == 5
        assert a != anker_voor(uuid.uuid4(), MJ1) and a != anker_voor(ADMIN, MJ2)
        assert uuid.uuid5(uuid.NAMESPACE_URL, "rlz-boekingsmodule/migratie") == vertaling.NAMESPACE_MIGRATIE

    def test_ref_vorm(self) -> None:
        a = anker_voor(ADMIN, MJ1)
        assert ref_voor("RLZ-06-00000026", a) == f"RLZ-06-00000026 · mig:{a}"
        assert ref_voor(None, a).startswith("— · mig:")


# ---- de mini-VGG ----------------------------------------------------------------


class TestMiniVgg:
    @pytest.fixture
    def rapport(self):  # noqa: ANN201
        collecties, regels, statements = mini_vgg()
        return _run(NepClient(collecties, regels, statements))

    def test_groen_en_tellers(self, rapport) -> None:  # noqa: ANN001
        assert rapport.fouten == [] and rapport.niet_vertaalbaar == []
        assert rapport.verschillen == 0, [
            r for r in rapport.saldibalans if r["verschil_tot_geschoond"] != 0 or r["verschil_jaareinde_geschoond"] != 0
        ]
        assert rapport.groen is True
        t = rapport.tellers
        assert t["per_collectie"]["PurchaseInvoices"] == {
            "gelezen": 2,
            "geboekt": 1,
            "concept": 1,
            "huls": 0,
            "niet_migreren": 1,
        }
        assert t["per_collectie"]["Receipts"] == {
            "gelezen": 4,
            "geboekt": 3,
            "concept": 0,
            "huls": 1,
            "niet_migreren": 1,
        }
        assert t["geboekt"] == 8 and t["niet_migreren"] == 2
        assert t["per_type"]["bank"] == {"vertaalbaar": 7, "zonder_pand": 0, "niet_vertaalbaar": 0}
        assert t["per_type"]["entry"] == {"vertaalbaar": 2, "zonder_pand": 1, "niet_vertaalbaar": 0}  # MJ2 midden
        assert t["btw_regels"] == 0 and t["regel_calls"] == 8 and t["regel_fouten"] == 0
        assert t["partners_nieuw"] == 2
        assert rapport.gelezen["Receipts"] == 6 and rapport.gelezen["JournalEntryLines"] == 22

    def test_saldibalans_per_rekening(self, rapport) -> None:  # noqa: ANN001
        per = {r["rekening"]: r for r in rapport.saldibalans}
        # bank: RLZ én Odoo −110.230,99 per 31-12-2025 (alles 2025); de open regel van 2026-09-09 valt buiten `tot`
        assert per["1100"]["rlz_jaareinde"] == Decimal("-110230.99") == per["1100"]["odoo_jaareinde"]
        # RJ 220: panden 0300 → rol 3000/3010, opbrengst 8000 → 8010 — geschoond 0, ongeschoond zichtbaar
        assert (
            per["300"]["verschil_jaareinde"] == Decimal("-220000.00")
            and per["300"]["verschil_jaareinde_geschoond"] == 0
        )
        assert per["300"]["rlz_tot"] == Decimal("370000.00") and per["300"]["odoo_tot"] == Decimal(
            "150000.00"
        )  # MJ2 blijft
        assert per["3000"]["odoo_tot"] == Decimal("200000.00") and per["3010"]["odoo_tot"] == Decimal("20000.00")
        assert per["8010"]["odoo_tot"] == Decimal("-260000.00") and per["8010"]["verschil_tot_geschoond"] == 0
        assert per["1600"]["rlz_tot"] == 0 == per["1600"]["odoo_tot"]
        herc = {(h["van"], h["naar"]): h for h in rapport.herclassificaties}
        assert herc[("300", "3000")]["documenten"] == 1 and herc[("300", "3000")]["bedrag"] == Decimal("200000.00")
        assert herc[("300", "3010")]["bedrag"] == Decimal("20000.00")  # aanbetaling: mens wint over zekerheid midden
        assert herc[("8000", "8010")]["bedrag"] == Decimal("-260000.00")
        assert rapport.journaal == {"regels": 22, "met_bron": 22, "zonder_bron": 0}

    def test_moves_vorm_contract(self, rapport) -> None:  # noqa: ANN001
        per = {m.rlz_id: m for m in rapport.moves}
        assert set(vars(per[MJ1])) == {
            "anker",
            "rlz_id",
            "boekstuk",
            "move_type",
            "date",
            "vals",
            "bank",
            "status",
            "reden",
            "partner",  # blok 7: partner-voorstel reist mee (None bij entry/bank_direct)
        }
        mj1 = per[MJ1]
        assert mj1.partner is None
        assert per[PI1].partner is not None and per[PI1].partner["sleutel"] in {"kvk", "btw", "iban", "naam"}
        assert mj1.move_type == "entry" and mj1.date == "2025-07-10" and mj1.anker == str(anker_voor(ADMIN, MJ1))
        assert mj1.vals["ref"] == f"RLZ-06-00000026 · mig:{mj1.anker}" and mj1.vals["journal_id"] == 50
        regels = [r for _, _, r in mj1.vals["line_ids"]]
        assert (
            regels[0]["account_id"] == 3000
            and regels[0]["debit"] == Decimal("200000.00")
            and regels[0]["tax_ids"] == [[6, 0, []]]
        )
        assert regels[0]["analytic_distribution"] == {"pand:gelderstraat-60": 100}
        assert "Gelderstraat 60 te Almere" in mj1.vals["narration"]  # ontknipt, geen "60\nte"
        pi1 = per[PI1]
        assert (
            pi1.move_type == "in_invoice" and pi1.vals["journal_id"] == 49 and pi1.vals["invoice_date"] == "2025-07-20"
        )
        assert pi1.vals["invoice_date_due"] == "2025-08-03" and pi1.vals["invoice_payment_term_id"] is False
        assert pi1.vals["invoice_line_ids"][0][2]["price_unit"] == Decimal("230.99")
        assert "nieuw (res.partner)" in pi1.reden and "kvk" in pi1.reden
        si1 = per[SI1]
        assert si1.move_type == "out_invoice" and si1.vals["invoice_line_ids"][0][2]["account_id"] == 8010
        assert "uitboeking kostprijs" in si1.reden
        assert per[MJ2].status == "zonder_pand" and "midden" in per[MJ2].reden
        assert per[MJ3].status == "vertaalbaar" and "vooruitbetaald_voorraad (3010)" in per[MJ3].reden

    def test_bankregels(self, rapport) -> None:  # noqa: ANN001
        per = {m.rlz_id: m for m in rapport.moves}
        b4 = per[PT[4]]
        assert b4.move_type == "bank" and b4.vals["journal_id"] == 53 and b4.vals["amount"] == Decimal("200000.00")
        assert b4.vals["payment_ref"] == "Aanbetaling volgens afspraak Allard Piersonlaan 20, Den Haag"
        assert b4.vals["account_number"] == "NL91ABNA0417164300" and b4.vals["unique_import_id"] == f"mig:{b4.anker}"
        assert b4.bank["reconcile"] == [
            {
                "anker": per[SI1].anker,
                "boekstuk": "RLZ-01-00000010",
                "move_type": "out_invoice",
                "bedrag": Decimal("200000.00"),
            }
        ]
        assert "deelkoppeling" in b4.reden
        b0 = per[PT[0]]
        assert b0.bank["reconcile"] == [] and b0.bank["tegenregel"][0]["account_id"] == 1650
        b6 = per[PT[6]]
        assert b6.bank["reconcile"] == [] and b6.bank["open_bedrag"] == Decimal("-500.00") and "open" in b6.reden
        assert [x["boekstuk"] for x in rapport.open_bank] == ["00106"]
        assert rapport.open_posten == []
        assert per[BD1].move_type == "bank_direct" and per[BD1].status == "vertaalbaar"

    def test_per_pand_partners_statements_export(self, rapport) -> None:  # noqa: ANN001
        pand = {p["pand"].split(" — ")[0]: p for p in rapport.per_pand}
        g = pand["gelderstraat-60"]
        assert (g["aankoop"], g["aanbetalingen"], g["kosten"], g["verkoop"]) == (
            Decimal("200000.00"),
            Decimal("20000.00"),
            Decimal("230.99"),
            Decimal("260000.00"),
        )
        assert g["marge"] == Decimal("59769.01")  # aanbetaling apart (balans tot levering)
        assert "rhijnauwensingel-93" not in pand  # midden/voorstel telt niet
        assert {p["sleutel"] for p in rapport.partners} == {"kvk", "naam"}
        assert [(s["maand"], s["sluit"]) for s in rapport.statements] == [
            ("2025-07", "ja"),
            ("2025-08", "ja"),
            ("2026-09", "geen afschrift-kop in RLZ voor deze maand"),
        ]
        assert rapport.export_melding is None
        assert {k: len(v) for k, v in rapport.export.items()} == {
            "in_invoice": 1,
            "entry": 2,
            "out_invoice": 1,
            "bank": 3,
        }
        assert all(m["date"].startswith("2025-07") for v in rapport.export.values() for m in v)

    def test_markdown_en_json(self, rapport) -> None:  # noqa: ANN001
        md = rapport.als_markdown()
        assert "**Oordeel: GROEN**" in md and "_alle verschillen 0,00_" in md and "EXPORT 2025-07" in md
        assert "RLZ-06-00000026 · mig:" in md and "Beslispunten Peter" in md
        data = json.loads(rapport.als_json())
        assert data["groen"] is True and data["tellers"]["moves"] == 15 == len(data["moves"])
        assert data["saldibalans"][0]["rlz_tot"].count(".") == 1  # Decimal → string, cent-exact
        assert data["beslispunten"][0].startswith("Statements per maand")


# ---- varianten ----------------------------------------------------------------


class TestVarianten:
    def test_ongemapte_rekening_niet_vertaalbaar_en_rood(self) -> None:
        collecties, regels, statements = mini_vgg()
        rapport = _run(
            NepClient(collecties, regels, statements), odoo_accounts=[a for a in ODOO_ACCOUNTS if a["code"] != "4400"]
        )
        assert rapport.groen is False
        assert [x["boekstuk"] for x in rapport.niet_vertaalbaar] == ["RLZ-04-00000100"]
        assert rapport.niet_vertaalbaar[0]["reden"].startswith("grootboek zonder Odoo-rekening: 4400")
        assert rapport.ongemapt == [
            {
                "rlz_ledger_id": L_KOSTEN,
                "rlz_code": "4400",
                "rlz_naam": "Vaste lasten panden",
                "account_type": 2,
                "regels": 1,
                "documenten": 1,
            }
        ]
        per = {r["rekening"]: r for r in rapport.saldibalans}
        assert per["ongemapt:4400"]["rlz_tot"] == Decimal("230.99") == per["ongemapt:4400"]["odoo_tot"]

    def test_rol_niet_ingesteld(self) -> None:
        collecties, regels, statements = mini_vgg()
        rapport = _run(NepClient(collecties, regels, statements), rollen=RolRekeningen())
        redenen = {x["boekstuk"]: x["reden"] for x in rapport.niet_vertaalbaar}
        assert set(redenen) == {"RLZ-06-00000026", "RLZ-06-00000030", "RLZ-01-00000010"}
        assert "rol-rekening voorraad_panden niet ingesteld" in redenen["RLZ-06-00000026"]

    def test_bookdate_terugval_zichtbaar(self) -> None:
        collecties, regels, statements = mini_vgg()
        del collecties["ManualJournals"][0]["BookDate"]
        rapport = _run(NepClient(collecties, regels, statements))
        m = next(x for x in rapport.moves if x.rlz_id == MJ1)
        assert m.date == "2025-07-10" and "BookDate ontbreekt → Date" in m.reden
        assert rapport.groen is True

    def test_btw_regel_telt(self) -> None:
        collecties, regels, statements = mini_vgg()
        regels[PI1][0]["TaxRate"] = {"id": str(uuid.uuid4())}
        regels[PI1][0]["TaxAmount"] = 48.51
        rapport = _run(NepClient(collecties, regels, statements))
        assert rapport.tellers["btw_regels"] == 1 and rapport.tellers["btw_documenten"] == 1
        m = next(x for x in rapport.moves if x.rlz_id == PI1)
        assert "mét btw" in m.reden and m.vals["invoice_line_ids"][0][2]["price_unit"] == Decimal("279.50")
        assert "moet 0 zijn" in rapport.als_markdown()

    def test_expand_terugval_zichtbaar(self) -> None:
        collecties, regels, statements = mini_vgg()
        client = NepClient(collecties, regels, statements, expand_weigeren={"PaymentTransactions"})
        rapport = _run(client)
        assert rapport.tellers["bank_expand_gelukt"] is False
        assert any("PaymentReferenceList" in x for x in rapport.let_op)
        assert any("$expand geweigerd" in x for x in rapport.overgeslagen)
        m = next(x for x in rapport.moves if x.rlz_id == PT[4])
        assert "$expand geweigerd" in m.reden

    def test_route_weigert_is_fout_en_rood(self) -> None:
        collecties, regels, statements = mini_vgg()
        client = NepClient(
            collecties,
            regels,
            statements,
            fouten={"JournalEntryLines": RlzApiError(403, "GET", "JournalEntryLines", "rechten")},
        )
        rapport = _run(client)
        assert rapport.fouten == [{"route": "JournalEntryLines", "status": 403, "melding": "403: rechten"}]
        assert rapport.groen is False and "FOUT JournalEntryLines" in rapport.als_markdown()

    def test_regels_niet_leesbaar_zichtbaar(self) -> None:
        collecties, regels, statements = mini_vgg()
        del regels[MJ2]
        rapport = _run(NepClient(collecties, regels, statements))
        assert rapport.tellers["regel_fouten"] == 1
        m = next(x for x in rapport.moves if x.rlz_id == MJ2)
        assert m.status == "niet_vertaalbaar" and "regels niet leesbaar" in m.reden and "404" in m.reden

    def test_tot_begrenst_de_saldibalans(self) -> None:
        collecties, regels, statements = mini_vgg()
        rapport = _run(NepClient(collecties, regels, statements), tot=date(2025, 7, 31))
        per = {r["rekening"]: r for r in rapport.saldibalans}
        assert per["1100"]["rlz_tot"] == Decimal("-20230.99") == per["1100"]["odoo_tot"]
        assert rapport.tot == "2025-07-31"

    def test_bank_direct_zonder_mutatie_is_niet_vertaalbaar(self) -> None:
        collecties, regels, statements = mini_vgg()
        collecties["PaymentTransactions"][1]["PaymentReferenceList"] = []
        rapport = _run(NepClient(collecties, regels, statements))
        m = next(x for x in rapport.moves if x.rlz_id == BD2)
        assert m.status == "niet_vertaalbaar" and "zonder gekoppelde bankmutatie" in m.reden

    def test_eigen_client_wordt_gesloten_en_geen_doel_is_let_op(self) -> None:
        collecties, regels, statements = mini_vgg()
        client = NepClient(collecties, regels, statements)
        rapport = _run(client, doel=Doel(), odoo_accounts=None)
        assert client.gesloten is False  # meegegeven client sluit de aanroeper
        assert any("doelkoppeling incompleet" in x for x in rapport.let_op)
        assert any("--odoo-rekeningen" in x for x in rapport.let_op)
        assert rapport.groen is False
        assert {o["rlz_code"] for o in rapport.ongemapt} == {"0300", "1650", "4400"}  # rol-regels (3000/3010/8010) niet


# ---- pure helpers ----------------------------------------------------------------


class TestBron:
    def test_huls_regels(self) -> None:
        open_bank = rlz_bron.open_bank_sleutels(
            [{"Amount": -500.0, "OpenAmount": -500.0, "BookDate": "2026-09-09T00:00:00"}]
        )
        assert open_bank == {("500.00", "2026-09-09")}
        assert rlz_bron.is_huls({"Status": 1, "IsSystemGenerated": True}, set())
        assert rlz_bron.is_huls({"Status": 1, "BaseInvoiceAmount": -500.0, "Date": "2026-09-09T00:00:00"}, open_bank)
        assert not rlz_bron.is_huls(
            {"Status": 1, "BaseInvoiceAmount": -500.0, "Date": "2026-09-09T00:00:00", "Entity": {"id": "x"}}, open_bank
        )
        assert not rlz_bron.is_huls({"Status": 3, "IsSystemGenerated": True}, set())

    def test_status_en_reeks(self) -> None:
        assert (
            rlz_bron.is_geboekt({"Status": 2})
            and rlz_bron.is_geboekt({"Status": "3"})
            and not rlz_bron.is_geboekt({"Status": 1})
        )
        assert rlz_bron.reeks_van("RLZ-06-00000026") == "RLZ-06" and rlz_bron.reeks_van(None) is None
        assert rlz_bron._eigen_is_bank_direct("ManualJournals", "RLZ-09-00000001", None)
        assert not rlz_bron._eigen_is_bank_direct("ManualJournals", "RLZ-06-00000001", "Memoriaal")

    def test_debet_credit_en_journaal_bron(self) -> None:
        assert rlz_bron.debet_credit({"DebitAmount": 10.0, "CreditAmount": 0}) == (Decimal("10.00"), Decimal("0.00"))
        assert rlz_bron.debet_credit({"CreditOrDebit": 2, "Amount": 5}) == (Decimal("0.00"), Decimal("5.00"))
        assert rlz_bron.debet_credit({"NetAmount": -7.5, "TaxAmount": 0}) == (Decimal("0.00"), Decimal("7.50"))
        jr = {"JournalEntry": {"BookDate": "2025-07-10T00:00:00", "EventID": "abc"}}
        assert rlz_bron.journaalregel_datum(jr) == date(2025, 7, 10) and rlz_bron.journaalregel_bron_id(jr) == "abc"

    def test_ontknip_in_de_bron(self) -> None:
        """De 32-tekens-knip uit RLZ komt nooit als spatie of `\\n` in payment_ref/narration (blok 0)."""
        collecties, regels, statements = mini_vgg()
        rapport = _run(NepClient(collecties, regels, statements))
        for m in rapport.moves:
            for w in (m.vals.get("payment_ref"), m.vals.get("narration")):
                assert w is None or ("\n" not in w and "All ard" not in w)


class TestLadersZonderRij:
    """De lazy laders naar C/D/B (rollen, doelkoppeling, panden) geven voor een onbekende administratie een fallback
    en gooien nooit — de dry-run loopt door mét LET OP (geen stille no-op, geen crash). Raakt de test-DB (lees)."""

    def test_rollen_doel_panden_fallback(self) -> None:
        onbekend = uuid.uuid4()
        rollen = vertaling.laad_rollen(onbekend)
        assert rollen.voorraad_panden is None and rollen.opbrengst_panden is None
        doel, melding = replay.laad_doel(onbekend)
        assert doel.compleet is False and melding is not None
        assert vertaling.laad_panden(onbekend, boekingen=[]) == {}
