"""Blok 6 run 2 VGG (12-09): replay-motor dry-run getest zonder RLZ/Odoo/DB — dict-client (stijl test_schoonlijst).

Mini-VGG: 2 notaris-aankopen (memoriaal RLZ-06), 1 aanbetaling, 1 vaste-lasten-inkoop, 1 verkoopfactuur notaris, 3 bank-
directe boekingen (DocumentType 19, RLZ-09) + 7 bankregels mét PaymentReferenceList waarvan één deelkoppeling (2 × op de
verkoopfactuur), 1 concept, 1 systeemhuls + open bankregel, JournalEntryLines die sluiten → saldibalans verschil 0,00 =
GROEN. Varianten: ongemapte rekening → niet-vertaalbaar + exit 1; anker deterministisch; BookDate-terugval zichtbaar;
btw-regel → teller; $expand-terugval zichtbaar; 403 op een route = fout + ROOD; JSON-roundtrip.

Blok 7c 13-09 (`TestBlok7c`): regelroute = document-vorm `{collectie}/{id}?$expand=DocumentLineList(…)` (kop mét
BookDate + regels in één call; `ManualJournals/{id}/Lines` bestaat niet — de NepClient geeft daar zoals RLZ 404-HTML);
BookDate uit de document-vorm stuurt de saldibalans per 31-12; > 0 documenten zonder regels = "ONVOLLEDIG — niet
doorrekenen"; EventID = soortcode (int) en telt niet; partner uit de tegenpartij van de bankmutatie; btw tweede bron;
afletter- groepen; pandenmodel op grootboek-regels (Rijswijkseweg-/Kapershoek-/Ruyghweg-/Verschoorstraat-casussen uit
de echte bedragen van de nameting 13-09, Donkerslootstraat 0101 = vast actief, concept-verkoopfactuur = signaal)."""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.migratie import replay, rlz_bron, vertaling
from app.migratie.vertaling import Doel, PandToewijzing, RolRekeningen, anker_marker, anker_voor
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
    {
        "id": L_PANDEN,
        "AccountNumber": "3100",
        "Description": "Voorraad panden",
        "AccountType": 3,
        "IsTotalAccount": False,
    },
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
    {"id": 300, "code": "3100", "name": "Voorraad panden (oud)"},
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


_JOURNAALPOSTEN: dict[str, str] = {}
#: JournalEntry.DocumentType per fixture-document (RLZ: 1 inkoop, 10 verkoop, 11 memoriaal, 19 bank-direct; bank = None)
_JR_DOCTYPE: dict[str, int | None] = {}


def _jr(ledger: str, bron_id: str, datum: str, *, debet: float = 0.0, credit: float = 0.0) -> dict:
    """Eén JournalEntryLine zoals RLZ 'm geeft (STAP-0 13-09): `JournalEntry` draagt alleen id/BookDate/DocumentType/
    EventID — en EventID is een SOORTCODE (71 inkoop, 51 verkoop), géén document-id. Regels van hetzelfde document delen
    één JournalEntry.id (de fixture onthoudt die per bron-document)."""
    dt = _JR_DOCTYPE.get(bron_id)
    jid = _JOURNAALPOSTEN.setdefault(bron_id, str(uuid.uuid4()))
    return {
        "id": str(uuid.uuid4()),
        "Account": {"id": ledger},
        "DebitAmount": debet,
        "CreditAmount": credit,
        "VatAmount": 0.0,
        "JournalEntry": {
            "id": jid,
            "BookDate": f"{datum}T00:00:00",
            "DocumentType": dt,
            "EventID": {1: 71, 10: 51, 11: 61, 19: 81}.get(dt or 0, 91),
        },
    }


def mini_vgg() -> tuple[dict[str, list[dict]], dict[str, list[dict]], dict[str, list[dict]]]:
    """(collecties, regels per document-id, statements per rekening-id)."""
    _JOURNAALPOSTEN.clear()
    _JR_DOCTYPE.update({MJ1: 11, MJ2: 11, MJ3: 11, PI1: 1, SI1: 10, BD1: 19, BD2: 19, BD3: 19})
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


HTML_404 = "<html>\n<head>\n\t<style>\n\t\tbody {\n\t\t\tmargin: 0;"  # RLZ's 404-pagina (STAP-0 13-09)
RECORD_COLLECTIES = ("PurchaseInvoices", "SalesInvoices", "ManualJournals", "BankMutationDirectBookings")


class NepClient:
    """Dict-client zoals RLZ zich op 13-09 gedroeg: collecties gepagineerd (een `DocumentLineList(…)`-expand op de
    collectie wordt STIL genegeerd); de DOCUMENT-vorm `X/{id}` geeft de kop (+ `koppen[id]`, bv. een BookDate die de
    collectie niet draagt) mét `DocumentLineList` uit `regels` als `$expand` die vraagt; `X/{id}/Lines` uit `regels`
    behalve `ManualJournals/{id}/Lines` = 404-HTML (route bestaat niet); `PaymentAccounts/{id}/Statements` uit
    `statements`; `fouten` per pad; `expand_weigeren` per pad → 400 bij $expand; `documentvorm_weigeren` per collectie →
    404 op `X/{id}` (test van de /Lines-terugval). Registreert élke GET."""

    def __init__(
        self,
        collecties,  # noqa: ANN001
        regels,  # noqa: ANN001
        statements,  # noqa: ANN001
        *,
        fouten=None,  # noqa: ANN001
        expand_weigeren=None,  # noqa: ANN001
        documentvorm_weigeren=None,  # noqa: ANN001
        koppen=None,  # noqa: ANN001
    ) -> None:
        self.collecties, self.regels, self.statements = collecties, regels, statements
        self.fouten = fouten or {}
        self.expand_weigeren = expand_weigeren or set()
        self.documentvorm_weigeren = documentvorm_weigeren or set()
        self.koppen = koppen or {}
        self.calls: list[tuple[str, dict]] = []
        self.gesloten = False

    def _rij(self, rlz_id: str) -> dict | None:
        for rijen in self.collecties.values():
            if not isinstance(rijen, list):
                continue
            for r in rijen:
                if isinstance(r, dict) and r.get("id") == rlz_id:
                    return r
        return None

    def get(self, path: str, *, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((path, params))
        if path in self.fouten:
            raise self.fouten[path]
        delen = path.split("/")
        if len(delen) == 3 and delen[2] == "Lines":
            if delen[0] == "ManualJournals":
                raise RlzApiError(404, "GET", path, HTML_404)  # route bestaat niet in RLZ (STAP-0 13-09)
            if delen[1] not in self.regels:
                raise RlzApiError(404, "GET", path, "_NotFound")
            return {"value": self.regels[delen[1]]}
        if len(delen) == 2 and delen[0] in RECORD_COLLECTIES:
            if delen[0] in self.documentvorm_weigeren:
                raise RlzApiError(404, "GET", path, HTML_404)
            rij = self._rij(delen[1])
            if rij is None:
                raise RlzApiError(404, "GET", path, '{"Message":"NotFound"}')
            uit = {**rij, **self.koppen.get(delen[1], {})}
            uit.pop("DocumentLineList", None)
            if "DocumentLineList" in params.get("$expand", "") and delen[1] in self.regels:
                uit["DocumentLineList"] = self.regels[delen[1]]
            return uit
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
        assert anker_marker(a) == f"mig:{a}"  # blok 7b punt 6: het anker staat kaal in het anker-veld per type


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
        assert t["per_type"]["bank"] == {"vertaalbaar": 7, "zonder_pand": 0, "niet_vertaalbaar": 0, "geblokkeerd": 0}
        assert t["per_type"]["entry"] == {
            "vertaalbaar": 2,
            "zonder_pand": 1,
            "niet_vertaalbaar": 0,
            "geblokkeerd": 0,
        }  # MJ2 midden
        assert t["btw_regels"] == 0 and t["regel_calls"] == 8 and t["regel_fouten"] == 0
        assert t["regels_via_documentvorm"] == 8 and t["regels_via_lines"] == 0  # blok 7c: één call per document
        assert t["bookdate_uit_document"] == 8 and t["bookdate_terugval_date"] == 0
        assert t["partners_nieuw"] == 2 and t["partners_uit_bank"] == 0 and t["partners_onbekend"] == 0
        assert rapport.gelezen["Receipts"] == 6 and rapport.gelezen["JournalEntryLines"] == 22

    def test_saldibalans_per_rekening(self, rapport) -> None:  # noqa: ANN001
        per = {r["rekening"]: r for r in rapport.saldibalans}
        # bank: RLZ én Odoo −110.230,99 per 31-12-2025 (alles 2025); de open regel van 2026-09-09 valt buiten `tot`
        assert per["1100"]["rlz_jaareinde"] == Decimal("-110230.99") == per["1100"]["odoo_jaareinde"]
        # RJ 220: voorraad panden 3100 (rubriek 3 = voorraad; rubriek 0 = vast actief) → rol 3000/3010, opbrengst
        # 8000 → 8010 — geschoond 0, ongeschoond zichtbaar
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
        assert rapport.journaal["regels"] == 22
        assert rapport.journaal["rlz_kolom"].startswith("koppeling journaalregel ↔ document bestaat niet in de RLZ-API")
        per_dt = {x["documenttype"]: x for x in rapport.journaal["per_documenttype"]}
        assert {k: per_dt[11][k] for k in ("documenttype", "naam", "journaalposten", "journaalregels")} == {
            "documenttype": 11,
            "naam": "memoriaal (11)",
            "journaalposten": 3,
            "journaalregels": 6,
        }
        assert per_dt[11]["documenten_geboekt"] == 3
        # blok 7d punt 2: DocumentType 11 heeft nog geen bewezen document-EventID → "niet uitvoerbaar", nooit stil
        assert per_dt[11]["oordeel"].startswith("toets niet uitvoerbaar met deze API") and "61" in per_dt[11]["oordeel"]
        assert per_dt[1]["journaalposten"] == 1 and per_dt[1]["documenten_geboekt"] == 1
        assert per_dt[1]["documentposten"] == 1 and per_dt[1]["oordeel"].startswith("sluit (1 documentposten = 1")
        assert per_dt[None]["journaalregels"] == 6 and per_dt[None]["documenten_geboekt"] == 0  # bankjournaal
        # blok 7c punt 7 (b): 1600/1300/1100 zitten in een groep, de groepen sluiten
        assert per["1600"]["groep"] == "crediteuren" and per["1300"]["groep"] == "debiteuren"
        assert per["1100"]["groep"] == "bank" and per["3000"]["groep"] is None
        groepen = {g["groep"]: g for g in rapport.afletter_groepen}
        assert groepen["crediteuren"]["verschil_tot"] == 0 and groepen["bank"]["rekeningen"] == ["1100"]

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
        assert mj1.vals["ref"] == f"mig:{mj1.anker}" and mj1.vals["journal_id"] == 50  # memoriaal: anker in ref
        assert mj1.vals["narration"].startswith("RLZ-06-00000026")
        pi1 = per[PI1]
        assert pi1.vals["invoice_origin"] == f"mig:{pi1.anker}" and "mig:" not in pi1.vals["ref"]  # factuur: ref kaal
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
        assert g["notaris_ontvangst"] == 0 and g["controle"].startswith("SIGNAAL")  # geen bank op het pand
        # midden/voorstel telt niet in de sommen — blok 7d punt 5: wél zichtbaar als "wacht op Toewijzing"
        assert pand["rhijnauwensingel-93"]["midden_wachtend"] == 1 and pand["rhijnauwensingel-93"]["documenten"] == 0
        assert pand["rhijnauwensingel-93"]["aankoop"] == 0 and g["midden_wachtend"] == 0
        assert {p["sleutel"] for p in rapport.partners} == {"kvk", "naam"}
        sluit = [(s["maand"], s["sluit"]) for s in rapport.statements]
        assert sluit[0][0] == "2025-07" and sluit[0][1].startswith("ja (RLZ-kop sluit op de som")
        assert sluit[1][0] == "2025-08" and sluit[1][1].startswith("ja (RLZ-kop sluit op de som")
        assert sluit[2] == ("2026-09", "geen afschrift-kop in RLZ — balance_end_real = berekend lopend saldo")
        # blok 7b punt 3: balance_end_real = lopend saldo (beginsaldo 0), saldo-toets per journal
        assert rapport.statements[0]["beginsaldo"] == Decimal("0.00")
        assert rapport.statements[1]["beginsaldo"] == rapport.statements[0]["eindsaldo"]
        assert rapport.statements[0]["balance_end_real"] == rapport.statements[0]["eindsaldo_rlz_kop"]  # RLZ-kop wint
        [toets] = rapport.saldo_toets
        assert toets["saldo_jaareinde"] == Decimal("-110230.99") == toets["saldo_tot"]  # de 2026-09-09-regel > tot
        assert toets["rlz_rekeningen"] == 1 and toets["afschrift_koppen_rlz"] == 2
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
        assert "Saldo-toets bank" in md and "Beslispunten Peter" in md and "Btw-afwikkeling historisch" in md
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
        # zonder rol-rekening: zichtbaar niet vertaalbaar; het restsaldo blijft berekend op de pseudo-rekening
        rapport = _run(NepClient(collecties, regels, statements))
        assert rapport.tellers["btw_regels"] == 1 and rapport.tellers["btw_documenten"] == 1
        m = next(x for x in rapport.moves if x.rlz_id == PI1)
        assert m.status == "niet_vertaalbaar" and "btw_afwikkeling_historisch niet ingesteld" in m.reden
        assert rapport.btw["rekening"] == "rol:btw_afwikkeling_historisch"
        assert rapport.btw["restsaldo_tot"] == Decimal("48.51") and rapport.btw["laatste_btw_regel"] == "2025-07-20"
        assert rapport.btw["afmeldingsdatum_uit_data"] == "2025-07-20"
        # mét rol-rekening (besluit Peter 13-09): netto-regel + één balansregel btw zonder tax_ids, geen btw-code
        rollen = RolRekeningen(
            voorraad_panden=3000,
            vooruitbetaald_voorraad=3010,
            opbrengst_panden=8010,
            kostprijs_panden=7000,
            btw_afwikkeling_historisch=1590,
        )
        rapport = _run(NepClient(collecties, regels, statements), rollen=rollen)
        m = next(x for x in rapport.moves if x.rlz_id == PI1)
        assert m.status == "vertaalbaar" and "Btw-afwikkeling historisch" in m.reden
        netto, btw = m.vals["invoice_line_ids"][0][2], m.vals["invoice_line_ids"][1][2]
        assert netto["price_unit"] == Decimal("230.99") and netto["account_id"] == 4400
        assert btw["price_unit"] == Decimal("48.51") and btw["account_id"] == 1590 and btw["tax_ids"] == [[6, 0, []]]
        assert rapport.btw["rol_ingesteld"] == 1590 and rapport.btw["restsaldo_tot"] == Decimal("48.51")
        md = rapport.als_markdown()
        assert "besluit Peter 13-09" in md and "Restsaldo rekening" in md and "moet 0 zijn" not in md

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
        assert m.status == "niet_vertaalbaar" and "regels niet leesbaar" in m.reden
        assert "zonder DocumentLineList" in m.reden and "bestaat niet in RLZ" in m.reden
        # blok 7c punt 1: één memoriaal zonder regels = ONVOLLEDIG, geen saldibalans-toets
        assert rapport.oordeel == "ONVOLLEDIG — niet doorrekenen" and rapport.groen is False
        assert rapport.saldibalans == [] and rapport.per_pand == [] and rapport.open_posten == []
        assert [x["boekstuk"] for x in rapport.onvolledig] == ["RLZ-06-00000074"]
        assert "ONVOLLEDIG — niet doorrekenen — 1 geboekt(e) document(en)" in rapport.als_markdown()

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
        assert {o["rlz_code"] for o in rapport.ongemapt} == {"3100", "1650", "4400"}  # rol-regels (3000/3010/8010) niet


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
        # blok 7d punt 1: de CreditOrDebit-code is GEEN richting meer — zonder Debit/CreditAmount is een memoriaalregel
        # onvertaalbaar (None), en debet_credit valt niet stil op de code terug
        assert rlz_bron.memoriaal_debet_credit({"CreditOrDebit": 2, "Amount": 5}) is None
        assert rlz_bron.debet_credit({"CreditOrDebit": 2, "Amount": 5}) == (Decimal("0.00"), Decimal("0.00"))
        assert rlz_bron.memoriaal_debet_credit({"CreditOrDebit": 1, "CreditAmount": 70.0, "NetAmount": 70.0}) == (
            Decimal("0.00"),
            Decimal("70.00"),
        )
        assert rlz_bron.debet_credit({"NetAmount": -7.5, "TaxAmount": 0}) == (Decimal("0.00"), Decimal("7.50"))
        jr = {"JournalEntry": {"id": "j1", "BookDate": "2025-07-10T00:00:00", "DocumentType": 1, "EventID": 71}}
        assert rlz_bron.journaalregel_datum(jr) == date(2025, 7, 10)
        assert rlz_bron.journaalregel_bron_id(jr) is None  # EventID is een soortcode, geen bron-id (STAP-0 13-09)
        assert rlz_bron.journaalregel_documenttype(jr) == 1 and rlz_bron.journaalregel_journaalpost_id(jr) == "j1"
        assert rlz_bron.journaalregel_bron_id({"Document": {"id": "d1"}}) == "d1"

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


# ---- blok 7b 13-09 ------------------------------------------------------------


class TestBlok7b:
    """Fixes uit de productienameting 13-09 (opdracht Peter): regels via de collectie-expand, webfilter-blokkering =
    meting ongeldig, verrekening factuur↔creditnota als paar, per pand mét bankmutaties, regelsom cent-exact."""

    def test_documentvorm_geeft_kop_en_regels_in_een_call_geen_collectie_expand(self) -> None:
        """Blok 7c (herziet 7b 1a): de collectie-expand `DocumentLineList(…)` wordt door RLZ stil genegeerd — de replay
        vraagt 'm niet meer; kop + regels komen per document uit `X/{id}?$expand=DocumentLineList(…)`, nul
        /Lines-calls."""
        collecties, regels, statements = mini_vgg()
        client = NepClient(collecties, regels, statements)
        rapport = _run(client)
        assert rapport.groen is True
        assert rapport.tellers["regels_via_documentvorm"] == 8 and rapport.tellers["regel_calls"] == 8
        assert not any(p.endswith("/Lines") for p, _ in client.calls)
        assert [prm.get("$expand") for p, prm in client.calls if p == "PurchaseInvoices"] == ["Entity"]
        assert [prm.get("$expand") for p, prm in client.calls if p == "ManualJournals"] == ["JournalEntryDiary"]
        assert all(
            prm.get("$expand") == "DocumentLineList($expand=Account,TaxRate)"
            for p, prm in client.calls
            if p.startswith(("ManualJournals/", "PurchaseInvoices/", "SalesInvoices/", "BankMutationDirectBookings/"))
        )
        assert (
            "8 via de document-vorm (kop mét BookDate + DocumentLineList), 0 via /Lines-terugval"
            in rapport.als_markdown()
        )
        assert not any("gaf geen DocumentLineList" in o for o in rapport.overgeslagen)

    def test_documentvorm_geweigerd_valt_terug_op_lines_behalve_memoriaal(self) -> None:
        collecties, regels, statements = mini_vgg()
        client = NepClient(collecties, regels, statements, documentvorm_weigeren={"PurchaseInvoices"})
        rapport = _run(client)
        assert rapport.groen is True and rapport.tellers["regels_via_lines"] == 1
        assert any(p == f"PurchaseInvoices/{PI1}/Lines" for p, _ in client.calls)
        # ManualJournals kent géén /Lines-route: document-vorm weg = document zonder regels = ONVOLLEDIG
        client = NepClient(collecties, regels, statements, documentvorm_weigeren={"ManualJournals"})
        rapport = _run(client)
        assert rapport.oordeel == "ONVOLLEDIG — niet doorrekenen" and rapport.tellers["regel_fouten"] == 3
        assert not any(p.startswith("ManualJournals/") and p.endswith("/Lines") for p, _ in client.calls)
        assert all("bestaat niet in RLZ (404-HTML" in x["route"] for x in rapport.onvolledig)

    def test_webfilter_blokkering_is_meting_ongeldig_niets_doorgerekend(self) -> None:
        from app.rlz.client import RlzWebfilterError

        collecties, regels, statements = mini_vgg()
        html = "<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD><BODY>You don't have permission</BODY></HTML>"
        client = NepClient(
            collecties,
            regels,
            statements,
            fouten={"PaymentAccounts": RlzWebfilterError(403, "GET", "PaymentAccounts", html)},
        )
        rapport = _run(client)
        assert rapport.blokkering is not None and rapport.blokkering.startswith("PaymentAccounts: webfilter 403")
        assert rapport.oordeel == "ROOD — RLZ-blokkering — meting ongeldig" and rapport.groen is False
        assert rapport.saldibalans == [] and rapport.moves == [] and rapport.per_pand == []  # niets doorgerekend
        assert not any(p in ("JournalEntryLines", "Ledgers", "TaxRates") for p, _ in client.calls)  # lezen gestopt
        md = rapport.als_markdown()
        assert "**RLZ-blokkering — meting ongeldig:**" in md and "Niets doorgerekend" in md
        assert any("meting ongeldig" in f["melding"] for f in rapport.fouten)
        assert json.loads(rapport.als_json())["blokkering"] == rapport.blokkering

    def test_webfilter_midden_in_de_regel_calls_stopt_direct(self) -> None:
        from app.rlz.client import RlzWebfilterError

        collecties, regels, statements = mini_vgg()
        client = NepClient(collecties, regels, statements)
        pad = f"BankMutationDirectBookings/{BD2}"  # blok 7c: de document-vorm is de eerste regelroute
        client.fouten = {pad: RlzWebfilterError(403, "GET", pad, "<HTML>Access Denied</HTML>")}
        rapport = _run(client)
        assert rapport.blokkering and "webfilter 403" in rapport.blokkering
        assert not any(p == "PaymentAccounts" for p, _ in client.calls)

    def test_verrekening_factuur_creditnota_als_paar(self) -> None:
        collecties, regels, statements = mini_vgg()
        # factuur € 46,51 + creditnota € −46,51 op dezelfde crediteur, beide in RLZ open 0, geen bankmutatie
        f_id, c_id = str(uuid.uuid4()), str(uuid.uuid4())
        f = _doc(f_id, "RLZ-04-00000068", "2025-07-05", 46.51, dt=1, Entity=VVE)
        c = _doc(c_id, "RLZ-04-00000088", "2025-07-09", -46.51, dt=1, Entity=VVE)
        collecties["PurchaseInvoices"] += [f, c]
        regels[f_id] = [_regel(L_KOSTEN, net=46.51)]
        regels[c_id] = [_regel(L_KOSTEN, net=-46.51)]
        rapport = _run(NepClient(collecties, regels, statements))
        assert rapport.verrekeningen == [
            {
                "factuur": "RLZ-04-00000068",
                "factuur_anker": str(anker_voor(ADMIN, f_id)),
                "creditnota": "RLZ-04-00000088",
                "creditnota_anker": str(anker_voor(ADMIN, c_id)),
                "bedrag": Decimal("46.51"),
                "herkomst": "afgeleid uit bedrag + relatie (RLZ-verrekeningsspoor niet gelezen)",
            }
        ]
        assert not [r for r in rapport.open_posten if r["boekstuk"] in ("RLZ-04-00000068", "RLZ-04-00000088")]
        assert "RLZ-04-00000068" in rapport.als_markdown() and rapport.verschillen == 0

    def test_koppelingen_som_ongelijk_totaal_is_zichtbare_oorzaak_nooit_stil_afgerond(self) -> None:
        collecties, regels, statements = mini_vgg()
        # de bank koppelt € 231,01 op een factuur van € 230,99 (betalingsverschil-afboeking in RLZ)
        collecties["PaymentTransactions"][3]["PaymentReferenceList"][0]["Amount"] = 231.01
        rapport = _run(NepClient(collecties, regels, statements))
        # blok 7d punt 4: RLZ toont de post volledig betaald (open 0) → write-off op Betalingsverschillen, open 0
        assert not [r for r in rapport.open_posten if r["boekstuk"] == "RLZ-04-00000100"]
        [wo] = rapport.betalingsverschillen
        assert wo["boekstuk"] == "RLZ-04-00000100" and wo["write_off"] == Decimal("0.02")
        assert wo["restant"] == Decimal("-0.02") and wo["betaald"] == Decimal("231.01") and wo["datum"] == "2025-07-21"
        assert wo["rekening"] == "ongemapt:4900"  # mini-VGG kent geen 4900-ledger: zichtbaar, nooit stil
        # de saldibalans draagt de write-off (Odoo-kant) — zonder RLZ-journaalregel op 4900 blijft dat een verschil
        per = {r["rekening"]: r for r in rapport.saldibalans}
        assert per["ongemapt:4900"]["odoo_tot"] == Decimal("0.02") and rapport.groen is False
        bank = next(m for m in rapport.moves if m.boekstuk == "00103")
        assert bank.bank["reconcile"][0]["write_off"]["bedrag"] == Decimal("0.02")

    def test_regelsom_ongelijk_documenttotaal_wordt_gemeld(self) -> None:
        collecties, regels, statements = mini_vgg()
        regels[PI1][0]["NetAmount"] = 230.97  # twee cent te weinig op de regels
        rapport = _run(NepClient(collecties, regels, statements))
        assert rapport.som_verschillen == [
            {
                "boekstuk": "RLZ-04-00000100",
                "move_type": "in_invoice",
                "bedrag": Decimal("230.99"),
                "som_verschil": Decimal("-0.02"),
            }
        ]
        m = next(x for x in rapport.moves if x.rlz_id == PI1)
        assert "regelsom € 230.97 ≠ documenttotaal € 230.99 (Δ -0.02)" in m.reden and rapport.groen is False
        assert "1 regelsom ≠ totaal" in rapport.als_markdown()

    def test_per_pand_telt_bankmutaties_uit_dezelfde_bron(self) -> None:
        collecties, regels, statements = mini_vgg()
        # de notaris-ontvangst 00105 (€ 60.000) krijgt in de afleiding een verkoop-toewijzing (hoog) op een ander pand
        panden = dict(PANDEN)
        panden[uuid.UUID(PT[5])] = PandToewijzing(
            "koraalerf-45", "Koraalerf 45, Heerlen", "verkoop", "hoog", "afgeleid"
        )
        rapport = _run(NepClient(collecties, regels, statements), panden=panden)
        pand = {p["pand"].split(" — ")[0]: p for p in rapport.per_pand}
        # blok 7c punt 4: de notaris-ONTVANGST is geen verkoop maar de netto-uitkering — eigen kolom, signaal zonder
        # geboekte verkoopfactuur
        k = pand["koraalerf-45"]
        assert k["notaris_ontvangst"] == Decimal("60000.00") and k["verkoop"] == 0 and k["documenten"] == 1
        assert k["marge"] == Decimal("0.00") and k["controle"].startswith("SIGNAAL")
        assert any("notaris-ontvangst zonder geboekte verkoopfactuur" in sg for sg in k["signalen"])
        b5 = next(x for x in rapport.moves if x.rlz_id == PT[5])
        assert b5.status == "vertaalbaar"

    def test_rlz_boekingen_bevat_bankmutaties(self) -> None:
        collecties, regels, statements = mini_vgg()
        bron = rlz_bron.lees_bron(NepClient(collecties, regels, statements))
        boekingen = replay._rlz_boekingen(bron)
        assert boekingen is not None
        assert sum(1 for b in boekingen if b.collectie == "PaymentTransactions") == 7

    def test_statements_zonder_koppen_lopend_saldo_per_iban_journal(self) -> None:
        collecties, regels, statements = mini_vgg()
        statements.clear()  # VGG: géén /Statements-koppen
        rek2 = str(uuid.uuid4())
        collecties["PaymentAccounts"].append({"id": rek2, "Name": "Spaar", "IBAN": "NL20 INGB 0001 2345 67", "Type": 1})
        collecties["PaymentTransactions"][5]["PaymentAccount"] = {"id": rek2, "Name": "Spaar"}
        rapport = _run(NepClient(collecties, regels, statements))
        [toets] = rapport.saldo_toets  # twee RLZ-rekeningen, één IBAN = één journal
        assert toets["rlz_rekeningen"] == 2 and toets["afschrift_koppen_rlz"] == 0
        assert toets["saldo_jaareinde"] == Decimal("-110230.99")
        assert all(s["sluit"].startswith("geen afschrift-kop in RLZ") for s in rapport.statements)
        assert rapport.statements[0]["beginsaldo"] == Decimal("0.00")
        assert [s["balance_end_real"] for s in rapport.statements] == [
            Decimal("-20230.99"),
            Decimal("-110230.99"),
            Decimal("-110730.99"),
        ]
        m = next(x for x in rapport.moves if x.rlz_id == PT[5])
        assert m.bank["statement_maand"] == "2025-08" and m.bank["journal_sleutel"] == "NL20INGB0001234567"

    def test_ob_afwikkeling_op_btw_grootboek_gaat_naar_de_rol(self) -> None:
        collecties, regels, statements = mini_vgg()
        l_ob = str(uuid.uuid4())
        collecties["Ledgers"].append(
            {
                "id": l_ob,
                "AccountNumber": "1520",
                "Description": "Te betalen OB",
                "AccountType": 4,
                "IsTotalAccount": False,
            }
        )
        # bank-directe boeking BD3 boekt op het OB-grootboek (teruggaaf/aangifte)
        regels[BD3] = [_regel(l_ob, net=20000.0, omschrijving="TERUGGAAF OB 3e kw 2025")]
        rollen = RolRekeningen(
            voorraad_panden=3000,
            vooruitbetaald_voorraad=3010,
            opbrengst_panden=8010,
            kostprijs_panden=7000,
            btw_afwikkeling_historisch=1590,
        )
        rapport = _run(NepClient(collecties, regels, statements), rollen=rollen)
        m = next(x for x in rapport.moves if x.rlz_id == BD3)
        assert m.status == "vertaalbaar" and "btw-grootboek) → btw_afwikkeling_historisch (1590)" in m.reden
        assert m.vals["regels"][0][2]["account_id"] == 1590
        assert rapport.btw["documenten_ob_afwikkeling"] == 1 and rapport.btw["laatste_ob_mutatie"] == "2025-07-15"
        assert rapport.btw["btw_ledgers"] == [{"code": "1520", "naam": "Te betalen OB"}]
        assert rapport.btw["journaalregels_btw_grootboek"] == 0  # de journaalregels boeken op L_NOTARIS, niet op OB


# ---- blok 7c 13-09 ------------------------------------------------------------


L_7000 = str(uuid.uuid4())
L_7001 = str(uuid.uuid4())
L_4612 = str(uuid.uuid4())
L_4601 = str(uuid.uuid4())
L_0101 = str(uuid.uuid4())
L_1405 = str(uuid.uuid4())
L_OB = str(uuid.uuid4())
LEDGERS_7C = [
    {
        "id": L_7000,
        "AccountNumber": "7000",
        "Description": "Inkopen vastgoed",
        "AccountType": 2,
        "IsTotalAccount": False,
    },
    {
        "id": L_7001,
        "AccountNumber": "7001",
        "Description": "Inkoop vaste lasten",
        "AccountType": 2,
        "IsTotalAccount": False,
    },
    {"id": L_4612, "AccountNumber": "4612", "Description": "Kosten bemiddeling makelaar", "AccountType": 2},
    {"id": L_4601, "AccountNumber": "4601", "Description": "Notariskosten", "AccountType": 2},
    {"id": L_0101, "AccountNumber": "0101", "Description": "Gebouwen en terreinen", "AccountType": 3},
    {"id": L_1405, "AccountNumber": "1405", "Description": "Aanbetaling Pand/Projecten", "AccountType": 3},
]
ODOO_7C = [
    {"id": 7000, "code": "7000", "name": "Inkopen vastgoed"},
    {"id": 7001, "code": "7001", "name": "Inkoop vaste lasten"},
    {"id": 4612, "code": "4612", "name": "Makelaar"},
    {"id": 4601, "code": "4601", "name": "Notaris"},
    {"id": 101, "code": "0101", "name": "Gebouwen en terreinen"},
    {"id": 1405, "code": "1405", "name": "Aanbetaling"},
]
NOTARIS_BUMA = {"id": str(uuid.uuid4()), "Name": "Buma Algera Notarissen"}


def _pand(code: str, adres: str, soort: str) -> PandToewijzing:
    return PandToewijzing(code, adres, soort, "hoog", "afgeleid")


def _casus_panden() -> tuple[dict, dict, dict, dict[uuid.UUID, PandToewijzing]]:
    """De vier verkochte panden uit de nameting 13-09 mét de échte totalen (verdeling over de grootboeken is fixture):
    Rijswijkseweg 409 (notaris-nota € 341.333,86 op 7000/4612/7001, verkoop € 385.000 als Receipt, notaris-ontvangst
    € 43.666,14, concept-verkoopfactuur RLZ-01-00000006 € 43.666,14), Kapershoek 34 (nota € 212.556,86 + vaste lasten
    € 440,47, aanbetalingen € 40.000, ontvangst € 52.443,14), Ruyghweg 71 (nota € 220.667,05 + vaste lasten € 1.177,09,
    aanbetaling € 1.500, ontvangst € 31.232,93), Verschoorstraat 70-02 (nota € 229.859,89, verkoopfactuur
    RLZ-01-00000013 € 282.500, ontvangst € 52.640,11) en Donkerslootstraat 105B (RLZ-24-00000770 € 183.871,22 op 0101 =
    vast actief)."""
    collecties, regels, statements = mini_vgg()
    collecties["Ledgers"] = LEDGERS + LEDGERS_7C
    panden = dict(PANDEN)
    docs: list[tuple[str, dict, list[dict], str, str, str]] = []  # (collectie, rij, regels, code, adres, soort)

    def nota(
        boekstuk: str, datum: str, totaal: float, verdeling: list[tuple[str, float]], code: str, adres: str
    ) -> None:
        rid = str(uuid.uuid4())
        rij = _doc(rid, boekstuk, datum, totaal, dt=1, Entity=NOTARIS_BUMA, Description=f"Nota van afrekening {adres}")
        docs.append(("PurchaseInvoices", rij, [_regel(led, net=b) for led, b in verdeling], code, adres, "aankoop"))

    nota(
        "RLZ-04-00000077",
        "2025-08-11",
        341333.86,
        [(L_7000, 330000.0), (L_4612, 9500.0), (L_7001, 1833.86)],
        "rijswijkseweg-409",
        "Rijswijkseweg 409",
    )
    nota(
        "RLZ-04-00000075",
        "2025-08-20",
        212556.86,
        [(L_7000, 205000.0), (L_4612, 6000.0), (L_7001, 1556.86)],
        "kapershoek-34",
        "Kapershoek 34",
    )
    nota(
        "RLZ-04-00000073",
        "2025-08-27",
        220667.05,
        [(L_7000, 212000.0), (L_4612, 6400.0), (L_4601, 1200.0), (L_7001, 1067.05)],
        "ruyghweg-71",
        "Ruyghweg 71",
    )
    nota(
        "RLZ-17-00000076",
        "2025-07-25",
        229859.89,
        [(L_7000, 222000.0), (L_4612, 7859.89)],
        "verschoorstraat-70-02",
        "Verschoorstraat 70-02",
    )
    # vaste lasten (kosten) + aanbetalingen (soort aanbetaling, documentbedrag)
    for boekstuk, datum, bedrag, code, adres in (
        ("RLZ-25-00000049", "2025-08-01", 440.47, "kapershoek-34", "Kapershoek 34"),
        ("RLZ-25-00000048", "2025-08-01", 1177.09, "ruyghweg-71", "Ruyghweg 71"),
    ):
        rid = str(uuid.uuid4())
        docs.append(
            (
                "PurchaseInvoices",
                _doc(rid, boekstuk, datum, bedrag, dt=1),
                [_regel(L_7001, net=bedrag)],
                code,
                adres,
                "vaste_lasten",
            )
        )
    for boekstuk, datum, bedrag, code, adres in (
        ("RLZ-04-00000201", "2025-07-01", 40000.0, "kapershoek-34", "Kapershoek 34"),
        ("RLZ-04-00000202", "2025-07-02", 1500.0, "ruyghweg-71", "Ruyghweg 71"),
    ):
        rid = str(uuid.uuid4())
        docs.append(
            (
                "PurchaseInvoices",
                _doc(rid, boekstuk, datum, bedrag, dt=1),
                [_regel(L_1405, net=bedrag)],
                code,
                adres,
                "aanbetaling",
            )
        )
    # verkopen: Rijswijkseweg als Receipt (out_invoice zonder Entity), Verschoorstraat als echte SalesInvoice
    rid_rv = str(uuid.uuid4())
    docs.append(
        (
            "Receipts",
            _doc(rid_rv, "RLZ-01-00000009", "2025-08-13", 385000.0, dt=10, Description="Verkoop Rijswijkseweg 409"),
            [_regel(L_OMZET, net=385000.0)],
            "rijswijkseweg-409",
            "Rijswijkseweg 409",
            "verkoop",
        )
    )
    rid_vs = str(uuid.uuid4())
    docs.append(
        (
            "SalesInvoices",
            _doc(rid_vs, "RLZ-01-00000013", "2025-07-28", 282500.0, dt=10, Description="Verkoop Verschoorstraat 70-02"),
            [_regel(L_OMZET, net=282500.0)],
            "verschoorstraat-70-02",
            "Verschoorstraat 70-02",
            "verkoop",
        )
    )
    # Donkerslootstraat 105B: vast actief op 0101 — nooit aan een pand
    rid_dk = str(uuid.uuid4())
    docs.append(
        (
            "PurchaseInvoices",
            _doc(rid_dk, "RLZ-24-00000770", "2025-10-23", 183871.22, dt=1, Entity=VVE),
            [_regel(L_0101, net=183871.22)],
            "donkerslootstraat-105-b",
            "Donkerslootstraat 105B",
            "kosten",
        )
    )
    for coll, rij, rgl, code, adres, soort in docs:
        collecties[coll].append(rij)
        regels[rij["id"]] = rgl
        panden[uuid.UUID(rij["id"])] = _pand(code, adres, soort)
    # concept-verkoopfactuur Rijswijkseweg (Status 1) — niet migreren, wél signaal
    rid_c = str(uuid.uuid4())
    collecties["SalesInvoices"].append(
        _doc(
            rid_c,
            "RLZ-01-00000006",
            "2025-08-13",
            43666.14,
            status=1,
            dt=10,
            Description="Overdracht Rijswijkseweg 409",
        )
    )
    panden[uuid.UUID(rid_c)] = _pand("rijswijkseweg-409", "Rijswijkseweg 409", "verkoop")
    # notaris-ontvangsten op de bank (positief, verkoop-toewijzing) — netto-uitkering, nooit verkoop
    for nr, (tx_id, datum, bedrag, code, adres) in enumerate(
        (
            (str(uuid.uuid4()), "2025-08-13", 43666.14, "rijswijkseweg-409", "Rijswijkseweg 409"),
            (str(uuid.uuid4()), "2025-08-21", 52443.14, "kapershoek-34", "Kapershoek 34"),
            (str(uuid.uuid4()), "2025-08-28", 31232.93, "ruyghweg-71", "Ruyghweg 71"),
            (str(uuid.uuid4()), "2025-07-31", 52640.11, "verschoorstraat-70-02", "Verschoorstraat 70-02"),
        )
    ):
        collecties["PaymentTransactions"].append(_tx(tx_id, f"0020{nr}", datum, bedrag, naam="B.A.N."))
        panden[uuid.UUID(tx_id)] = _pand(code, adres, "verkoop")
    return collecties, regels, statements, panden


class TestBlok7c:
    """Fixes uit de productienameting 13-09 (opdracht Peter, blok 7c): document-vorm mét BookDate, ONVOLLEDIG-oordeel,
    journaal zonder koppeling, partner uit bank, btw tweede bron, afletter-groepen, pandenmodel op grootboek-regels."""

    def test_bookdate_uit_documentvorm_stuurt_de_saldibalans_per_jaareinde(self) -> None:
        collecties, regels, statements = mini_vgg()
        pi1 = collecties["PurchaseInvoices"][0]
        del pi1["BookDate"]
        pi1["Date"] = (
            "2026-01-05T00:00:00"  # factuurdatum in 2026, geboekt in 2025 (BookDate alleen op de document-vorm)
        )
        rapport = _run(NepClient(collecties, regels, statements, koppen={PI1: {"BookDate": "2025-07-20T00:00:00"}}))
        m = next(x for x in rapport.moves if x.rlz_id == PI1)
        assert m.date == "2025-07-20" and m.vals["invoice_date"] == "2025-07-20" and "BookDate ontbreekt" not in m.reden
        assert rapport.tellers["bookdate_uit_document"] == 8 and rapport.tellers["bookdate_terugval_date"] == 0
        assert rapport.groen is True
        # zonder de kop valt de datum terug op Date → 4400 per 31-12 sluit niet en de teller toont dat
        rapport = _run(NepClient(collecties, regels, statements))
        m = next(x for x in rapport.moves if x.rlz_id == PI1)
        assert m.date == "2026-01-05" and "BookDate ontbreekt → Date" in m.reden
        assert rapport.tellers["bookdate_terugval_date"] == 1 and rapport.groen is False
        per = {r["rekening"]: r for r in rapport.saldibalans}
        assert per["4400"]["verschil_jaareinde_geschoond"] == Decimal("-230.99")
        assert "1 terugval op Date" in rapport.als_markdown()

    def test_partner_uit_de_tegenpartij_van_de_bankmutatie_en_beslispunt_voor_de_rest(self) -> None:
        collecties, regels, statements = mini_vgg()
        # RLZ-15-reeks: inkoopfactuur zónder Entity, betaald door een bankmutatie van "Shell" — tegenpartij = partner
        shell_id, los_id = str(uuid.uuid4()), str(uuid.uuid4())
        collecties["PurchaseInvoices"].append(_doc(shell_id, "RLZ-15-00000045", "2025-08-06", 264.34, dt=1))
        regels[shell_id] = [_regel(L_KOSTEN, net=264.34)]
        tx = _tx(
            str(uuid.uuid4()),
            "00107",
            "2025-08-06",
            -264.34,
            refs=[(collecties["PurchaseInvoices"][-1], 264.34)],
            naam="Shell",
        )
        tx["CounterAccount"] = "NL55INGB0000000055"
        collecties["PaymentTransactions"].append(tx)
        # RLZ-17-reeks: zonder Entity én zonder bankmutatie — blijft onbekend (beslispunt Peter)
        collecties["PurchaseInvoices"].append(_doc(los_id, "RLZ-17-00000061", "2025-08-21", 795.0, dt=1))
        regels[los_id] = [_regel(L_KOSTEN, net=795.0)]
        rapport = _run(NepClient(collecties, regels, statements))
        per = {m.rlz_id: m for m in rapport.moves}
        assert per[shell_id].partner == {
            "naam": "Shell",
            "kvk": None,
            "btw": None,
            "iban": "NL55INGB0000000055",
            "sleutel": "iban",
            "voorstel": "nieuw (res.partner)",
            "herkomst": "bank",
            "bron_tekst": "bankmutatie 00107",
        }
        assert "uit bankmutatie 00107" in per[shell_id].reden
        # blok 7d punt 6 (besluit Peter 14-09): geen dummy-partner — geblokkeerd concept, eigen tabel, niet "niet
        # vertaalbaar"
        assert per[los_id].partner["voorstel"] == "onbekend" and vertaling.PARTNER_ONBEKEND_REDEN in per[los_id].reden
        assert per[los_id].status == vertaling.STATUS_GEBLOKKEERD
        assert [g["boekstuk"] for g in rapport.geblokkeerd] == ["RLZ-17-00000061"]
        assert not [x for x in rapport.niet_vertaalbaar if x["boekstuk"] == "RLZ-17-00000061"]
        assert rapport.tellers["partners_uit_bank"] == 1 and rapport.tellers["partners_onbekend"] == 1
        assert rapport.tellers["geblokkeerd_partner"] == 1
        md = rapport.als_markdown()
        assert "waarvan 1 uit de tegenpartij van de bankmutatie" in md and "BESLISPUNT PETER" not in md
        assert "#### Geblokkeerd — partner onbekend — 1" in md
        assert any(p["voorstel"] == "onbekend" for p in rapport.partners)
        assert any("GEEN dummy-partner" in b for b in json.loads(rapport.als_json())["beslispunten"])
        assert rapport.tellers["per_type"]["in_invoice"]["geblokkeerd"] == 1

    def test_btw_tweede_bron_en_btw_code_zonder_bedrag(self) -> None:
        collecties, regels, statements = mini_vgg()
        collecties["Ledgers"].append(
            {"id": L_OB, "AccountNumber": "1520", "Description": "Te betalen OB", "AccountType": 4}
        )
        _JR_DOCTYPE[MJ1] = 11
        collecties["JournalEntryLines"].append(_jr(L_OB, MJ1, "2025-07-10", debet=100.0))
        collecties["JournalEntryLines"].append(_jr(L_NOTARIS, MJ1, "2025-07-10", credit=100.0))
        regels[PI1][0]["TaxRate"] = {"id": str(uuid.uuid4())}  # btw-code "Geen BTW" mét TaxAmount 0 → geen btw
        rapport = _run(NepClient(collecties, regels, statements))
        assert rapport.tellers["btw_regels"] == 0 and rapport.tellers["btw_code_zonder_bedrag"] == 1
        assert rapport.btw["journaalregels_btw_grootboek"] == 1 and rapport.btw["journaalregels_btw_som"] == Decimal(
            "100.00"
        )
        assert rapport.btw["laatste_journaalregel_btw"] == "2025-07-10" == rapport.btw["afmeldingsdatum_uit_data"]
        md = rapport.als_markdown()
        assert "1 regel(s) dragen een btw-code (TaxRate) met bedrag 0" in md and "Tweede bron (JournalEntryLines" in md

    def test_afletter_groepen_tellen_per_groep_niet_per_rekening(self) -> None:
        collecties, regels, statements = mini_vgg()
        collecties["PaymentTransactions"][3]["PaymentReferenceList"] = []  # PI1 niet gekoppeld → open aan beide kanten
        rapport = _run(
            NepClient(collecties, regels, statements),
            doel=Doel(
                company_id=6, journal_sale_id=48, journal_purchase_id=49, journal_general_id=50, journal_bank_id=53
            ),
        )
        per = {r["rekening"]: r for r in rapport.saldibalans}
        assert per["impliciet:crediteuren"]["groep"] == "crediteuren" and per["1600"]["groep"] == "crediteuren"
        assert per["impliciet:bank-tussenrekening"]["groep"] == "tussenrekening"
        assert per["bank:Betaalrekening"]["groep"] == "bank" and per["1100"]["groep"] == "bank"
        groepen = {g["groep"]: g for g in rapport.afletter_groepen}
        assert groepen["bank"]["verschil_tot"] == 0  # RLZ 1100 ↔ bank:Betaalrekening sluiten als groep
        assert groepen["crediteuren"]["verschil_tot"] == Decimal("-230.99")  # factuur open in Odoo, in RLZ betaald
        assert groepen["tussenrekening"]["verschil_tot"] == Decimal("230.99")
        # oordeel: per groep (2: crediteuren + tussenrekening) plús de open post van PI1 — niet per rekening (dat
        # zouden 4 rijen zijn: impliciet:crediteuren, 1600, impliciet:bank-tussenrekening en bank:/1100)
        open_met_verschil = sum(1 for r in rapport.open_posten if r["verschil"] != 0)
        assert open_met_verschil == 1 and rapport.verschillen == 2 + open_met_verschil and rapport.groen is False
        assert sum(1 for r in rapport.saldibalans if r["groep"] is None and r["verschil_tot_geschoond"] != 0) == 0
        assert "Groepstoets afletter-/tegenzijde-rekeningen" in rapport.als_markdown()

    def test_pandenmodel_op_grootboekregels_vier_casussen_nameting_13_09(self) -> None:
        collecties, regels, statements, panden = _casus_panden()
        rapport = _run(NepClient(collecties, regels, statements), panden=panden, odoo_accounts=ODOO_ACCOUNTS + ODOO_7C)
        assert rapport.oordeel != "ONVOLLEDIG — niet doorrekenen"
        pand = {p["pand"].split(" — ")[0]: p for p in rapport.per_pand}
        r = pand["rijswijkseweg-409"]
        assert (r["aankoop"], r["kosten"], r["verkoop"], r["notaris_ontvangst"]) == (
            Decimal("330000.00"),
            Decimal("11333.86"),
            Decimal("385000.00"),
            Decimal("43666.14"),
        )
        assert r["marge"] == Decimal("43666.14") and r["controle"] == "sluit"  # 385.000 − 341.333,86 = de bankontvangst
        assert r["signalen"] == ["verkoopfactuur RLZ-01-00000006 nog concept in RLZ — boeken vóór replay"]
        k = pand["kapershoek-34"]
        assert (k["aankoop"], k["aanbetalingen"], k["kosten"], k["notaris_ontvangst"]) == (
            Decimal("205000.00"),
            Decimal("40000.00"),
            Decimal("7997.33"),
            Decimal("52443.14"),
        )
        assert k["verkoop"] == 0 and k["marge"] == Decimal("-212997.33")  # geen verkoopfactuur in de fixture → signaal
        assert any("notaris-ontvangst zonder geboekte verkoopfactuur" in sg for sg in k["signalen"])
        ru = pand["ruyghweg-71"]
        assert (ru["aankoop"], ru["aanbetalingen"], ru["kosten"]) == (
            Decimal("212000.00"),
            Decimal("1500.00"),
            Decimal("9844.14"),
        )
        v = pand["verschoorstraat-70-02"]
        assert (v["aankoop"], v["kosten"], v["verkoop"], v["notaris_ontvangst"]) == (
            Decimal("222000.00"),
            Decimal("7859.89"),
            Decimal("282500.00"),
            Decimal("52640.11"),
        )
        assert v["marge"] == Decimal("52640.11") and v["controle"] == "sluit" and v["signalen"] == []
        d = pand["donkerslootstraat-105-b"]
        assert d["kosten"] == 0 and d["aankoop"] == 0 and d["marge"] is None  # 0101 = vast actief, telt nergens
        md = rapport.als_markdown()
        assert "Notaris-ontvangst (bank)" in md and "Panden mét signaal:" in md
        # geen negatieve marge zonder verklarende regel op een pand mét verkoopfactuur én ontvangst
        assert not any("negatieve marge" in sg for p in (r, v) for sg in p["signalen"])

    def test_pandenmodel_controle_sluit_na_aanbetalingen(self) -> None:
        collecties, regels, statements, panden = _casus_panden()
        # Kapershoek krijgt zijn verkoopfactuur: 225.440,47 = aankoop + kosten + ontvangst − aanbetalingen (40.000 al
        # rechtstreeks aan de verkoper betaald → de notaris keert dat méér uit)
        rid = str(uuid.uuid4())
        collecties["SalesInvoices"].append(_doc(rid, "RLZ-01-00000014", "2025-08-21", 225440.47, dt=10))
        regels[rid] = [_regel(L_OMZET, net=225440.47)]
        panden[uuid.UUID(rid)] = _pand("kapershoek-34", "Kapershoek 34", "verkoop")
        rapport = _run(NepClient(collecties, regels, statements), panden=panden, odoo_accounts=ODOO_ACCOUNTS + ODOO_7C)
        k = {p["pand"].split(" — ")[0]: p for p in rapport.per_pand}["kapershoek-34"]
        assert k["verkoop"] == Decimal("225440.47") and k["marge"] == Decimal("12443.14")
        assert k["controle"] == "sluit ná aanbetalingen (Δ -40000.00 = aanbetalingen)" and k["signalen"] == []

    def test_rlz_boekingen_dragen_grootboeken_en_concepten(self) -> None:
        collecties, regels, statements, _ = _casus_panden()
        bron = rlz_bron.lees_bron(NepClient(collecties, regels, statements))
        boekingen = replay._rlz_boekingen(bron)
        assert boekingen is not None
        per = {b.boekstuk: b for b in boekingen}
        assert per["RLZ-04-00000077"].grootboeken == frozenset({"7000", "4612", "7001"})
        assert per["RLZ-24-00000770"].grootboeken == frozenset({"0101"}) == per["RLZ-24-00000770"].vaste_activa
        assert per["RLZ-01-00000006"].grootboeken == frozenset()  # concept: geen regels gelezen, wél in de lijst
        assert bron.koppen[PI1]["BookDate"] == "2025-07-20T00:00:00"  # kop uit de document-vorm

    def test_statusregel_onvolledig(self) -> None:
        from app.migratie.cli_replay import statusregel

        collecties, regels, statements = mini_vgg()
        del regels[MJ2]
        rapport = _run(NepClient(collecties, regels, statements))
        assert statusregel(rapport).startswith("UITKOMST: ONVOLLEDIG — niet doorrekenen — 1 geboekt(e) document(en)")
