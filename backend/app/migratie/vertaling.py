"""Vertaling RLZ-document → Odoo-move-vorm (run 2 VGG 12-09, blok 6; contract E). Puur, geen netwerk, geen DB.

Per GEBOEKT RLZ-document één `MoveVoorstel` (veldnamen bindend voor D: anker, rlz_id, boekstuk, move_type, date, vals,
bank, status, reden):
- `anker` = uuid5(NAMESPACE_MIGRATIE, f"{administratie_id}:{rlz_id}") — BLOK 7b 13-09 (beslispunt 3, advies
  overgenomen): facturen dragen `ref` = het KALE RLZ-factuur-/boekstuknummer (`Reference`, anders `ReceiptNumber`) en
  het anker `mig:<anker>` in `invoice_origin`; memorialen dragen het anker in `ref`; bankregels in `unique_import_id`
  (`ref` = kale TransactionId). Zoek-vóór-create per type op dát veld (`odoo_schrijf.zoek_move_op_anker`).
- `date` = `invoice_date` = RLZ `BookDate`; terugval `Date` is zichtbaar in `reden` ("BookDate ontbreekt → Date").
- grootboek per regel via `app.odoo.rj220.vertaal_grootboek` (agent C, lazy) — fallback
`mapping.bepaal_grootboek_voorstel`
  (zelfde code / code+"00"); ongemapt = geen gok → `niet_vertaalbaar`.
- RJ 220-rollen (`rj220.rollen_voor`, lazy; fallback alles None → "rol-rekening niet ingesteld"): B's soort `aankoop` →
  voorraad_panden, `aanbetaling` → vooruitbetaald_voorraad, `verkoop` → opbrengst_panden (uitboeking kostprijs =
  rapportregel, géén tweede move in run 2), `kosten`/`vaste_lasten` → kostenrekening uit de mapping mét pand-analytic,
  `balans` → gewone mapping zonder analytic. De rol vervangt DETERMINISTISCH één regel: bij aankoop/aanbetaling de
  activa-regel (Ledgers.AccountType 3) met het grootste debetbedrag, bij verkoop de opbrengst-regel (AccountType 1) met
  het grootste creditbedrag; zonder zo'n regel de grootste debet-/creditregel. Elke herclassificatie staat apart in het
  rapport zodat de saldibalans-vergelijking 'm kan schonen.
- pand-analytic via `app.panden.service.pand_per_document` (agent B, lazy; fallback lege dict): alleen `herkomst ==
"mens"`
  of `zekerheid == "hoog"` telt; midden/laag → status `zonder_pand`. Company 6 kent nog geen pand-analytics: de
  `analytic_distribution`-sleutel is in de dry-run `"pand:<code>"` (run 3 zoekt/maakt de analytic aan —
  lookup-vóór-create).
- partner = VOORSTEL zoek-vóór-create op KvK → btw → IBAN → naam; de dry-run leest Odoo NIET ("nieuw (res.partner)" /
  "onbekend" / "n.v.t.").
- BTW (besluit Peter 13-09, blok 7b): VGG is NIET btw-plichtig — de btw in de RLZ-historie stamt van een foute
  registratie door de Belastingdienst (later afgemeld). Élke regel mét `TaxAmount` ≠ 0 splitst in de netto-regel op de
  eigen rekening + één balansregel voor het btw-bedrag op de rol `btw_afwikkeling_historisch` (zonder tax_ids); regels
  waarvan het RLZ-grootboek een btw-rekening is (`Context.btw_ledgers`: OB-afwikkeling via memoriaal/bank) gaan als
  herclassificatie naar dezelfde rol. Zonder rol-rekening = niet vertaalbaar (zichtbaar). `tax_ids = [[6, 0, []]]` op
  élke regel — geen enkele Odoo-move krijgt een btw-code. De btw-teller telt regels mét TaxAmount ≠ 0.
- Regelsom cent-exact (blok 7b punt 4): Σ regels (netto + btw, in boekrichting) ≠ `BaseInvoiceAmount` → `som_verschil`
  in `Vertaald` + reden; nooit stil afronden.
- Bankregel = `account.bank.statement.line`-vals (date, journal_id, payment_ref = `ontknip(Reference)`, amount mét
teken,
  partner_name, account_number = CounterAccount, ref/unique_import_id = anker) + `bank`-blok: tegenregel (bank-directe
  boeking: grootboek + analytic uit de gekoppelde DocumentType-19-regels) óf reconcile-paar (PaymentReferenceList →
  Document → anker; deelkoppeling = deelbedrag); referenties naar een systeemhuls tellen als open.
Geld in Decimal; datums ISO-strings."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from app.migratie import rlz_bron
from app.rlz.lezen import als_bedrag, als_datum, als_int, entity_van
from app.rlz.tekst import ontknip, ontknip_velden

NAMESPACE_MIGRATIE = uuid.uuid5(uuid.NAMESPACE_URL, "rlz-boekingsmodule/migratie")
NUL = Decimal("0.00")
LEGE_TAX: list[list[Any]] = [[6, 0, []]]

STATUS_VERTAALBAAR = "vertaalbaar"
STATUS_ZONDER_PAND = "zonder_pand"
STATUS_NIET = "niet_vertaalbaar"

ROLLEN = ("voorraad_panden", "vooruitbetaald_voorraad", "opbrengst_panden", "kostprijs_panden")
ROL_PER_SOORT = {"aankoop": "voorraad_panden", "aanbetaling": "vooruitbetaald_voorraad", "verkoop": "opbrengst_panden"}
PAND_SOORTEN = frozenset({"aankoop", "aanbetaling", "verkoop", "kosten", "vaste_lasten"})
LEDGERTYPE_OPBRENGST = 1
LEDGERTYPE_ACTIVA = 3

#: Pseudo-rekeningen voor de impliciete tegenzijde als de doelkoppeling geen Odoo-id kent — zichtbaar in de saldibalans.
IMPLICIET_CREDITEUREN = "impliciet:crediteuren"
IMPLICIET_DEBITEUREN = "impliciet:debiteuren"
IMPLICIET_TUSSENREKENING = "impliciet:bank-tussenrekening"
#: Pseudo-rekening voor de btw-afwikkelrol zolang die geen Odoo-id heeft — het restsaldo blijft zo berekenbaar.
ROL_BTW_PSEUDO = "rol:btw_afwikkeling_historisch"
BRON_BTW = "btw"


# ---- contract-dataclasses (eigen spiegel; C/B leveren de echte) ---------------------------------------------


@dataclass(frozen=True)
class RolRekeningen:
    voorraad_panden: int | None = None
    vooruitbetaald_voorraad: int | None = None
    opbrengst_panden: int | None = None
    kostprijs_panden: int | None = None
    analytic_overhead: int | None = None
    btw_afwikkeling_historisch: int | None = None  # blok 7b 13-09


@dataclass(frozen=True)
class GrootboekVertaling:
    rlz_ledger_id: str
    rlz_code: str | None
    rlz_naam: str | None
    odoo_account_id: int | None
    odoo_code: str | None
    bron: str | None


@dataclass(frozen=True)
class PandToewijzing:
    pand_code: str
    adres: str
    soort: str
    zekerheid: str
    herkomst: str


@dataclass(frozen=True)
class Doel:
    """Odoo-doel (company 6): dagboeken uit de doelkoppeling (D), optioneel de Odoo-id's van de impliciete zijden."""

    company_id: int | None = None
    journal_sale_id: int | None = None
    journal_purchase_id: int | None = None
    journal_general_id: int | None = None
    journal_bank_id: int | None = None
    analytic_plan_id: int | None = None
    rekening_crediteuren_id: int | None = None
    rekening_debiteuren_id: int | None = None
    rekening_bank_ids: dict[str, int] = field(default_factory=dict)  # RLZ PaymentAccount-id → Odoo account-id

    @property
    def compleet(self) -> bool:
        return None not in (
            self.journal_sale_id,
            self.journal_purchase_id,
            self.journal_general_id,
            self.journal_bank_id,
        )


@dataclass
class MoveVoorstel:
    anker: str
    rlz_id: str
    boekstuk: str | None
    move_type: str  # in_invoice | in_refund | out_invoice | out_refund | entry | bank_direct | bank
    date: str | None
    vals: dict[str, Any]
    bank: dict[str, Any] | None
    status: str
    reden: str
    #: Blok 7 run 2 (besluit Peter 12-09 punt 3): het partner-VOORSTEL (naam/kvk/btw/iban/sleutel) reist mee op de
    #: move zodat de partners-stap van `vgg-odoo-stap0` zoek-vóór-create kan doen; None = geen partner nodig (entry,
    #: bank_direct). `vals["partner_id"]` blijft None tot die stap 'm invult.
    partner: dict[str, Any] | None = None

    def als_dict(self) -> dict[str, Any]:
        return {
            "anker": self.anker,
            "rlz_id": self.rlz_id,
            "boekstuk": self.boekstuk,
            "move_type": self.move_type,
            "date": self.date,
            "vals": self.vals,
            "bank": self.bank,
            "status": self.status,
            "reden": self.reden,
            "partner": self.partner,
        }


@dataclass(frozen=True)
class BalansRegel:
    """Eén regel voor de berekende Odoo-saldibalans: `rekening` = str(odoo-id) of een pseudo-sleutel."""

    rekening: str
    rlz_ledger_id: str | None
    debet: Decimal
    credit: Decimal
    datum: str | None
    bron: str  # regel | impliciet | bank | tegenregel


@dataclass(frozen=True)
class PartnerVoorstel:
    naam: str | None
    kvk: str | None
    btw: str | None
    iban: str | None
    sleutel: str  # kvk | btw | iban | naam | geen
    voorstel: str  # "nieuw (res.partner)" | "onbekend" | "n.v.t."


@dataclass
class Vertaald:
    move: MoveVoorstel
    regels: list[BalansRegel] = field(default_factory=list)
    partner: PartnerVoorstel | None = None
    btw_regels: int = 0
    pand: PandToewijzing | None = None
    herclassificaties: list[tuple[str, str, Decimal]] = field(default_factory=list)  # (van, naar, bedrag)
    ongemapt: list[str] = field(default_factory=list)  # RLZ-ledger-id's zonder Odoo-rekening
    bedrag: Decimal | None = None
    open_bedrag: Decimal | None = None
    #: Blok 7b 13-09
    entity_id: str | None = None  # RLZ Entity-id (voor verrekening factuur↔creditnota binnen dezelfde relatie)
    btw_bedrag: Decimal = NUL  # Σ btw (debet − credit) naar de afwikkelrol
    ob_afwikkeling: bool = False  # een regel op een RLZ-btw-grootboek (OB-aangifte/-teruggaaf) → afwikkelrol
    som_verschil: Decimal | None = None  # Σ regels − documenttotaal (≠ 0 = melden, nooit stil afronden)


@dataclass
class Context:
    administratie_id: uuid.UUID
    doel: Doel
    grootboek: dict[str, GrootboekVertaling]
    ledgers: dict[str, tuple[str | None, str | None, int | None]]  # id → (code, naam, AccountType)
    rollen: RolRekeningen
    panden: dict[uuid.UUID, PandToewijzing]
    #: RLZ-ledger-id's die een btw-rekening zijn (naam-regex op Ledgers + Account-refs van TaxRates) — blok 7b 13-09.
    btw_ledgers: frozenset[str] = frozenset()


# ---- ankers ----------------------------------------------------------------------------------------------


def anker_voor(administratie_id: uuid.UUID | str, rlz_id: uuid.UUID | str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE_MIGRATIE, f"{administratie_id}:{rlz_id}")


def anker_marker(anker: uuid.UUID | str) -> str:
    return f"mig:{anker}"


def ref_kaal(rij: dict[str, Any], boekstuk: str | None, rlz_id: str) -> str:
    """Het kale RLZ-factuur-/boekstuknummer voor Odoo-veld `ref` (blok 7b punt 6): `Reference` (ontknipt), anders
    het boekstuknummer, anders het RLZ-id."""
    return ontknip(rij.get("Reference")) or boekstuk or rlz_id


_BTW_LEDGER_NAAM = re.compile(r"\bbtw\b|omzetbelasting|\bo\.?b\.?\b|voorbelasting|af te dragen ob|te vorderen ob", re.I)


def btw_ledgers_uit(ledgers: list[dict[str, Any]], taxrates: list[dict[str, Any]]) -> frozenset[str]:
    """RLZ-grootboekrekeningen die btw zijn: naam-regex op `Ledgers.Description` + élke `Account`/`Ledger`-ref op de
    TaxRates-rijen (RLZ hangt het aangifte-grootboek aan het tarief). Deterministisch; het rapport noemt de lijst."""
    uit: set[str] = set()
    for r in ledgers:
        rid = rlz_bron.doc_id(r)
        naam = str(r.get("Description") or r.get("Name") or "")
        if rid and _BTW_LEDGER_NAAM.search(naam):
            uit.add(rid)
    for t in taxrates:
        for sleutel, waarde in t.items():
            if ("Account" in sleutel or "Ledger" in sleutel) and isinstance(waarde, dict) and waarde.get("id"):
                uit.add(str(waarde["id"]))
    return frozenset(uit)


# ---- laders (lazy naar C en B; fallback zonder afhankelijkheid) --------------------------------------------------


def ledgers_index(ledgers: list[dict[str, Any]]) -> dict[str, tuple[str | None, str | None, int | None]]:
    uit: dict[str, tuple[str | None, str | None, int | None]] = {}
    for r in ledgers:
        rid = rlz_bron.doc_id(r)
        if rid:
            code = r.get("AccountNumber")
            uit[rid] = (str(code) if code is not None else None, r.get("Description"), als_int(r.get("AccountType")))
    return uit


def _fallback_vertaal_grootboek(rlz: list[tuple[str, str | None, str | None]], odoo: list[dict[str, Any]]):
    from app.odoo.mapping import OdooRekening, RlzRekening, bepaal_grootboek_voorstel  # noqa: PLC0415

    odoo_rek = [
        OdooRekening(
            odoo_id=int(a["id"]),
            lokaal_id=uuid.uuid5(NAMESPACE_MIGRATIE, f"odoo-account:{a['id']}"),
            code=str(a.get("code") or "").strip(),
            naam=str(a.get("name") or ""),
        )
        for a in odoo
        if a.get("id") is not None
    ]
    rlz_rek = [
        RlzRekening(
            rlz_id=uuid.UUID(rid) if _is_uuid(rid) else uuid.uuid5(NAMESPACE_MIGRATIE, f"ledger:{rid}"),
            code=code,
            naam=naam,
            in_gebruik_observaties=0,
            in_gebruik_open_regels=0,
        )
        for rid, code, naam in rlz
    ]
    uit = []
    for (rid, code, naam), rij in zip(rlz, bepaal_grootboek_voorstel(rlz_rek, odoo_rek), strict=True):
        uit.append(
            GrootboekVertaling(
                rlz_ledger_id=rid,
                rlz_code=code,
                rlz_naam=naam,
                odoo_account_id=rij.voorstel.odoo_id if rij.voorstel else None,
                odoo_code=rij.voorstel.code if rij.voorstel else None,
                bron=rij.reden,
            )
        )
    return uit


def _is_uuid(tekst: str) -> bool:
    try:
        uuid.UUID(str(tekst))
        return True
    except (ValueError, TypeError):
        return False


def laad_grootboek(ledgers: list[dict[str, Any]], odoo_accounts: list[dict[str, Any]]) -> dict[str, GrootboekVertaling]:
    """RLZ-ledger-id → vertaling. Via C's `rj220.vertaal_grootboek` als die er is, anders de mapping-fallback."""
    idx = ledgers_index(ledgers)
    rlz = [(rid, code, naam) for rid, (code, naam, _t) in idx.items()]
    try:
        from app.odoo.rj220 import vertaal_grootboek  # noqa: PLC0415 — C bouwt 'm parallel

        ruw = vertaal_grootboek([(uuid.UUID(r) if _is_uuid(r) else r, c, n) for r, c, n in rlz], odoo_accounts)  # type: ignore[arg-type]
        return {
            str(v.rlz_ledger_id): GrootboekVertaling(
                rlz_ledger_id=str(v.rlz_ledger_id),
                rlz_code=v.rlz_code,
                rlz_naam=v.rlz_naam,
                odoo_account_id=v.odoo_account_id,
                odoo_code=v.odoo_code,
                bron=v.bron,
            )
            for v in ruw
        }
    except ImportError:
        return {v.rlz_ledger_id: v for v in _fallback_vertaal_grootboek(rlz, odoo_accounts)}


def laad_rollen(administratie_id: uuid.UUID) -> RolRekeningen:
    try:
        from app.odoo.rj220 import rollen_voor  # noqa: PLC0415

        r = rollen_voor(administratie_id)
        return RolRekeningen(
            voorraad_panden=r.voorraad_panden,
            vooruitbetaald_voorraad=r.vooruitbetaald_voorraad,
            opbrengst_panden=r.opbrengst_panden,
            kostprijs_panden=r.kostprijs_panden,
            analytic_overhead=r.analytic_overhead,
            btw_afwikkeling_historisch=getattr(r, "btw_afwikkeling_historisch", None),
        )
    except ImportError:
        return RolRekeningen()


def laad_panden(administratie_id: uuid.UUID, *, boekingen: Any = None) -> dict[uuid.UUID, PandToewijzing]:
    try:
        from app.panden.service import pand_per_document  # noqa: PLC0415 — B bouwt 'm parallel
    except ImportError:
        return {}
    ruw = pand_per_document(administratie_id, boekingen=boekingen)
    return {
        k: PandToewijzing(
            pand_code=str(v.pand_code),
            adres=str(v.adres),
            soort=str(v.soort),
            zekerheid=str(v.zekerheid),
            herkomst=str(v.herkomst),
        )
        for k, v in ruw.items()
    }


def pand_telt(p: PandToewijzing | None) -> bool:
    return p is not None and (p.herkomst == "mens" or p.zekerheid == "hoog")


# ---- partner --------------------------------------------------------------------------------------------------


def _eerste(entity: dict[str, Any], *sleutels: str) -> str | None:
    for s in sleutels:
        w = entity.get(s)
        if isinstance(w, str) and w.strip():
            return w.strip()
    return None


def partner_voorstel(rij: dict[str, Any], *, nodig: bool) -> PartnerVoorstel:
    entity = rij.get("Entity") if isinstance(rij.get("Entity"), dict) else {}
    _, naam = entity_van(rij)
    if not nodig and not entity:
        return PartnerVoorstel(None, None, None, None, "geen", "n.v.t.")
    kvk = _eerste(entity, "ChamberOfCommerceNumber", "CoCNumber", "KvkNumber", "RegistrationNumber")
    btw = _eerste(entity, "VatNumber", "TaxNumber", "VATNumber")
    iban = _eerste(entity, "IBAN", "BankAccount", "BankAccountNumber")
    sleutel = "kvk" if kvk else "btw" if btw else "iban" if iban else "naam" if naam else "geen"
    voorstel = "nieuw (res.partner)" if sleutel != "geen" else "onbekend"
    return PartnerVoorstel(naam=naam, kvk=kvk, btw=btw, iban=iban, sleutel=sleutel, voorstel=voorstel)


# ---- document → move -------------------------------------------------------------------------------------------


def move_type_voor(collectie: str, rij: dict[str, Any]) -> str:
    dt = rlz_bron.documenttype_van(collectie, rij)
    bedrag = als_bedrag(rij.get("BaseInvoiceAmount")) or NUL
    if dt == rlz_bron.DOCTYPE_BANK_DIRECT:
        return "bank_direct"
    if dt == rlz_bron.DOCTYPE_MEMORIAAL:
        return "entry"
    if dt == rlz_bron.DOCTYPE_VERKOOP:
        return "out_refund" if bedrag < 0 else "out_invoice"
    return "in_refund" if bedrag < 0 else "in_invoice"


def _datum(rij: dict[str, Any]) -> tuple[str | None, str | None]:
    """(iso-datum, terugval-melding)."""
    bd = als_datum(rij.get("BookDate"))
    if bd:
        return bd.isoformat(), None
    d = als_datum(rij.get("Date"))
    if d:
        return d.isoformat(), "BookDate ontbreekt → Date"
    return None, "geen BookDate en geen Date"


def _netto_en_btw(regel: dict[str, Any]) -> tuple[Decimal, Decimal] | None:
    """(NetAmount, TaxAmount) mét teken voor factuurregels; None voor memoriaal-/journaalregels (Debit/CreditAmount,
    daar zit de btw als eigen regel op een btw-grootboek)."""
    net = als_bedrag(regel.get("NetAmount"))
    if net is None:
        return None  # memoriaal-/journaalregel (Debit/CreditAmount of CreditOrDebit+Amount): geen netto/btw-splitsing
    tax = als_bedrag(regel.get("TaxAmount")) or NUL
    return net, tax


def _orienteer_bedrag(bedrag: Decimal, move_type: str) -> tuple[Decimal, Decimal]:
    """(debet, credit) van één bedrag mét teken in boekrichting: inkoop positief = debet, verkoop positief = credit."""
    b = bedrag.quantize(Decimal("0.01"))
    if move_type in ("out_invoice", "out_refund"):
        return (NUL, b) if b >= 0 else (-b, NUL)
    return (b, NUL) if b >= 0 else (NUL, -b)


def orienteer(regels: list[dict[str, Any]], move_type: str) -> list[tuple[Decimal, Decimal]]:
    """(debet, credit) per regel in BOEKRICHTING: een verkoopregel met positief NetAmount is credit (opbrengst)."""
    uit: list[tuple[Decimal, Decimal]] = []
    for r in regels:
        d, c = rlz_bron.debet_credit(r)
        uit.append((c, d) if move_type in ("out_invoice", "out_refund") else (d, c))
    return uit


def _kies_rolregel(
    regels: list[dict[str, Any]], bedragen: list[tuple[Decimal, Decimal]], ctx: Context, soort: str
) -> int | None:
    """Index van de regel die de RJ 220-rol krijgt (zie moduledoc) — None als er geen regels zijn."""
    if not regels:
        return None
    zoek_type, kant = (LEDGERTYPE_OPBRENGST, 1) if soort == "verkoop" else (LEDGERTYPE_ACTIVA, 0)
    kandidaten = [
        i
        for i, r in enumerate(regels)
        if (ctx.ledgers.get(rlz_bron.ref_id(r.get("Account")) or "") or (None, None, None))[2] == zoek_type
    ]
    pool = kandidaten or list(range(len(regels)))
    return max(pool, key=lambda i: (bedragen[i][kant], -i))


def vertaal_document(
    ctx: Context, collectie: str, rij: dict[str, Any], regels: list[dict[str, Any]] | None
) -> Vertaald:
    rlz_id = rlz_bron.doc_id(rij) or ""
    boekstuk = rlz_bron.boekstuk_van(rij)
    anker = anker_voor(ctx.administratie_id, rlz_id)
    move_type = move_type_voor(collectie, rij)
    datum, datum_melding = _datum(rij)
    bedrag = als_bedrag(rij.get("BaseInvoiceAmount"))
    redenen: list[str] = []
    if datum_melding:
        redenen.append(datum_melding)
    pand = ctx.panden.get(uuid.UUID(rlz_id)) if _is_uuid(rlz_id) else None
    partner = partner_voorstel(rij, nodig=move_type not in ("entry", "bank_direct"))
    uit = Vertaald(
        move=MoveVoorstel(
            str(anker),
            rlz_id,
            boekstuk,
            move_type,
            datum,
            {},
            None,
            STATUS_VERTAALBAAR,
            "",
            partner=asdict(partner) if partner.voorstel != "n.v.t." else None,
        ),
        partner=partner,
        pand=pand,
        bedrag=bedrag,
        open_bedrag=als_bedrag(rij.get("BaseRemainingAmount")),
        entity_id=entity_van(rij)[0],
    )
    status = STATUS_VERTAALBAAR
    if datum is None:
        status = STATUS_NIET
    if regels is None:
        status = STATUS_NIET
        redenen.append("regels niet leesbaar")
        regels = []
    elif not regels:
        status = STATUS_NIET
        redenen.append("document zonder regels")

    # pand / rol
    analytic: dict[str, int] | None = None
    rol_index: int | None = None
    rol_naam: str | None = None
    if pand is not None and pand.soort in PAND_SOORTEN:
        if pand_telt(pand):
            analytic = {f"pand:{pand.pand_code}": 100}
            redenen.append(f"pand {pand.pand_code} ({pand.soort}, {pand.zekerheid}/{pand.herkomst})")
            rol_naam = ROL_PER_SOORT.get(pand.soort)
            if rol_naam:
                rol_index = _kies_rolregel(regels, orienteer(regels, move_type), ctx, pand.soort)
                if getattr(ctx.rollen, rol_naam) is None:
                    status = STATUS_NIET
                    redenen.append(f"rol-rekening {rol_naam} niet ingesteld")
            if pand.soort == "verkoop":
                redenen.append("uitboeking kostprijs verkochte panden = rapportregel (geen tweede move in run 2)")
        else:
            if status == STATUS_VERTAALBAAR:
                status = STATUS_ZONDER_PAND
            redenen.append(f"pand-voorstel {pand.pand_code} zekerheid {pand.zekerheid} — niet als analytic genomen")
    elif pand is not None and pand.soort == "balans":
        redenen.append(f"balansboeking (pand {pand.pand_code}) — geen analytic")

    # regels
    omkeren = move_type in ("in_refund", "out_refund")
    regel_vals: list[dict[str, Any]] = []
    btw_rol_id = ctx.rollen.btw_afwikkeling_historisch
    btw_rek = str(btw_rol_id) if btw_rol_id is not None else ROL_BTW_PSEUDO
    btw_rol_gemeld = False
    som = NUL
    for i, (r, (d_tot, c_tot)) in enumerate(zip(regels, orienteer(regels, move_type), strict=True)):
        ledger_id = rlz_bron.ref_id(r.get("Account"))
        vert = ctx.grootboek.get(ledger_id or "")
        odoo_id: int | None = vert.odoo_account_id if vert else None
        netto_btw = _netto_en_btw(r)
        if netto_btw is None:
            d, c = d_tot, c_tot
            t_d = t_c = NUL
        else:
            d, c = _orienteer_bedrag(netto_btw[0], move_type)
            t_d, t_c = _orienteer_bedrag(netto_btw[1], move_type)
        som += (d_tot - c_tot) if move_type in ("in_invoice", "in_refund", "entry", "bank_direct") else (c_tot - d_tot)
        if rol_index is not None and i == rol_index and rol_naam:
            rol_id = getattr(ctx.rollen, rol_naam)
            if rol_id is not None:
                if odoo_id is not None:
                    uit.herclassificaties.append((str(odoo_id), str(rol_id), (d - c).quantize(Decimal("0.01"))))
                odoo_id = rol_id
                redenen.append(f"regel {i + 1} → {rol_naam} ({rol_id})")
        if ledger_id and ledger_id in ctx.btw_ledgers:
            # OB-afwikkeling (aangifte/teruggaaf via memoriaal of bank) → de afwikkelrol, herclassificatie zichtbaar
            uit.ob_afwikkeling = True
            uit.btw_bedrag += d - c
            if odoo_id is not None:
                uit.herclassificaties.append((str(odoo_id), btw_rek, (d - c).quantize(Decimal("0.01"))))
            odoo_id = btw_rol_id
            rekening = btw_rek
            if btw_rol_id is None:
                status = STATUS_NIET
                if not btw_rol_gemeld:
                    redenen.append("rol-rekening btw_afwikkeling_historisch niet ingesteld")
                    btw_rol_gemeld = True
            else:
                redenen.append(f"regel {i + 1} (btw-grootboek) → btw_afwikkeling_historisch ({btw_rol_id})")
        else:
            if odoo_id is None:
                if ledger_id and ledger_id not in uit.ongemapt:
                    uit.ongemapt.append(ledger_id)
                status = STATUS_NIET
            rekening = (
                str(odoo_id)
                if odoo_id is not None
                else f"ongemapt:{(vert.rlz_code if vert else None) or ledger_id or '?'}"
            )
        uit.regels.append(BalansRegel(rekening, ledger_id, d, c, datum, "regel"))
        naam = ontknip(r.get("Description")) or boekstuk or rlz_id
        rv: dict[str, Any] = {"name": naam, "account_id": odoo_id, "tax_ids": LEGE_TAX}
        if analytic:
            rv["analytic_distribution"] = dict(analytic)
        if move_type == "entry":
            rv["debit"] = d
            rv["credit"] = c
        else:
            netto = (d - c) if move_type in ("in_invoice", "in_refund") else (c - d)
            rv["quantity"] = 1
            rv["price_unit"] = (-netto if omkeren else netto).quantize(Decimal("0.01"))
        regel_vals.append([0, 0, rv])
        if t_d or t_c:
            # btw-bedrag = gewone balansregel op de afwikkelrol, zónder tax_ids (besluit Peter 13-09)
            uit.btw_regels += 1
            uit.btw_bedrag += t_d - t_c
            uit.regels.append(BalansRegel(btw_rek, None, t_d, t_c, datum, BRON_BTW))
            if btw_rol_id is None:
                status = STATUS_NIET
                if not btw_rol_gemeld:
                    redenen.append("rol-rekening btw_afwikkeling_historisch niet ingesteld")
                    btw_rol_gemeld = True
            btw_netto = (t_d - t_c) if move_type in ("in_invoice", "in_refund") else (t_c - t_d)
            rv_btw: dict[str, Any] = {
                "name": f"btw historisch — {naam}",
                "account_id": btw_rol_id,
                "tax_ids": LEGE_TAX,
                "quantity": 1,
                "price_unit": (-btw_netto if omkeren else btw_netto).quantize(Decimal("0.01")),
            }
            regel_vals.append([0, 0, rv_btw])

    # regelsom cent-exact tegen het documenttotaal (blok 7b punt 4) — melden, nooit stil afronden
    if regels:
        if move_type == "entry":
            uit.som_verschil = som.quantize(Decimal("0.01"))
            if uit.som_verschil != 0:
                redenen.append(f"memoriaal sluit niet: debet − credit = € {uit.som_verschil}")
        elif bedrag is not None:
            # bank-directe boeking: het documenttotaal draagt het teken van de MUTATIE, de regels de boekrichting
            uit.som_verschil = ((abs(som) - abs(bedrag)) if move_type == "bank_direct" else (som - bedrag)).quantize(
                Decimal("0.01")
            )
            if uit.som_verschil != 0:
                redenen.append(
                    f"regelsom € {som.quantize(Decimal('0.01'))} ≠ documenttotaal € {bedrag} (Δ {uit.som_verschil})"
                )

    # impliciete tegenzijde (crediteuren/debiteuren) voor de saldibalans
    if move_type in ("in_invoice", "in_refund") and regels:
        tot = sum((rg.debet - rg.credit for rg in uit.regels), NUL)
        rek = str(ctx.doel.rekening_crediteuren_id) if ctx.doel.rekening_crediteuren_id else IMPLICIET_CREDITEUREN
        uit.regels.append(
            BalansRegel(rek, None, NUL if tot >= 0 else -tot, tot if tot >= 0 else NUL, datum, "impliciet")
        )
    elif move_type in ("out_invoice", "out_refund") and regels:
        tot = sum((rg.credit - rg.debet for rg in uit.regels), NUL)
        rek = str(ctx.doel.rekening_debiteuren_id) if ctx.doel.rekening_debiteuren_id else IMPLICIET_DEBITEUREN
        uit.regels.append(
            BalansRegel(rek, None, tot if tot >= 0 else NUL, NUL if tot >= 0 else -tot, datum, "impliciet")
        )

    # vals — anker (blok 7b punt 6): facturen `ref` kaal + `invoice_origin` = mig:<anker>; memoriaal anker in `ref`
    marker = anker_marker(anker)
    kaal = ref_kaal(rij, boekstuk, rlz_id)
    omschrijving = ontknip_velden(rij, "Header", "Description", "Reference")
    if move_type == "entry":
        vals: dict[str, Any] = {
            "move_type": "entry",
            "company_id": ctx.doel.company_id,
            "journal_id": ctx.doel.journal_general_id,
            "date": datum,
            "ref": marker,
            "line_ids": regel_vals,
        }
        omschrijving = f"{boekstuk or rlz_id}" + (f" — {omschrijving}" if omschrijving else "")
    elif move_type == "bank_direct":
        vals = {"move_type": "bank_direct", "ref": kaal, "anker": marker, "date": datum, "regels": regel_vals}
        redenen.append("tegenregel van een bankregel — geen eigen move")
    else:
        inkoop = move_type in ("in_invoice", "in_refund")
        vals = {
            "move_type": move_type,
            "company_id": ctx.doel.company_id,
            "journal_id": ctx.doel.journal_purchase_id if inkoop else ctx.doel.journal_sale_id,
            "partner_id": None,
            "ref": kaal,
            "invoice_origin": marker,
            "invoice_date": datum,
            "date": datum,
            "invoice_line_ids": regel_vals,
        }
        vervaldatum = als_datum(rij.get("DueDate"))
        if vervaldatum:
            vals["invoice_date_due"] = vervaldatum.isoformat()
            vals["invoice_payment_term_id"] = False
        redenen.append(
            f"partner {partner.voorstel}" + (f" [{partner.sleutel}: {partner.naam}]" if partner.naam else "")
        )
    if omschrijving:
        vals["narration"] = omschrijving
    if uit.ongemapt:
        codes = [(ctx.grootboek.get(x).rlz_code if ctx.grootboek.get(x) else None) or x for x in uit.ongemapt]
        redenen.insert(0, f"grootboek zonder Odoo-rekening: {', '.join(str(c) for c in codes)}")
    if uit.btw_regels:
        btw_som = uit.btw_bedrag.quantize(Decimal("0.01"))
        redenen.append(
            f"{uit.btw_regels} btw-regel(s) → Btw-afwikkeling historisch (€ {btw_som}, zonder tax_ids; besluit 13-09)"
        )
    uit.move.vals = vals
    uit.move.status = status
    uit.move.reden = "; ".join(redenen) if redenen else "1-op-1 vertaald"
    return uit


# ---- bankregel → statement line -------------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentAnker:
    anker: str
    boekstuk: str | None
    move_type: str
    is_huls: bool
    tegenregels: tuple[dict[str, Any], ...] = ()  # alleen bank_direct: regel-vals (account_id, analytic, bedrag)
    tegen_balans: tuple[BalansRegel, ...] = ()
    bedrag: Decimal | None = None  # documentbedrag — een koppeling kleiner dan dit is een deelkoppeling


def vertaal_bankregel(
    ctx: Context, tx: dict[str, Any], ankers: dict[str, DocumentAnker], *, expand_gelukt: bool = True
) -> Vertaald:
    rlz_id = rlz_bron.doc_id(tx) or ""
    anker = anker_voor(ctx.administratie_id, rlz_id)
    datum, datum_melding = _datum(tx)
    bedrag = als_bedrag(tx.get("Amount")) or NUL
    open_bedrag = als_bedrag(tx.get("OpenAmount"))
    rekening = tx.get("PaymentAccount") if isinstance(tx.get("PaymentAccount"), dict) else {}
    rekening_id = str(rekening.get("id") or "")
    boekstuk = str(tx.get("TransactionId") or "") or None
    redenen: list[str] = [datum_melding] if datum_melding else []
    status = STATUS_VERTAALBAAR if datum else STATUS_NIET

    statement_line: dict[str, Any] = {
        "date": datum,
        "journal_id": ctx.doel.journal_bank_id,
        "company_id": ctx.doel.company_id,
        "payment_ref": ontknip(tx.get("Reference")) or boekstuk or rlz_id,
        "amount": bedrag,
        "partner_name": tx.get("Name") if isinstance(tx.get("Name"), str) else None,
        "account_number": tx.get("CounterAccount") if isinstance(tx.get("CounterAccount"), str) else None,
        "ref": boekstuk or rlz_id,  # kaal (blok 7b punt 6); het anker zit in unique_import_id
        "unique_import_id": anker_marker(anker),
    }
    reconcile: list[dict[str, Any]] = []
    tegenregels: list[dict[str, Any]] = []
    deel = False
    regels: list[BalansRegel] = []
    bank_rek = (
        str(ctx.doel.rekening_bank_ids[rekening_id])
        if rekening_id in ctx.doel.rekening_bank_ids
        else (f"bank:{rekening.get('Name') or rekening.get('IBAN') or rekening_id or '?'}")
    )
    regels.append(
        BalansRegel(bank_rek, None, bedrag if bedrag >= 0 else NUL, -bedrag if bedrag < 0 else NUL, datum, "bank")
    )
    gekoppeld = NUL
    refs = tx.get("PaymentReferenceList") if isinstance(tx.get("PaymentReferenceList"), list) else []
    for pr in refs:
        if not isinstance(pr, dict):
            continue
        doc = pr.get("Document") if isinstance(pr.get("Document"), dict) else {}
        did = rlz_bron.doc_id(doc)
        pr_bedrag = als_bedrag(pr.get("Amount")) or NUL
        if doc.get("IsSystemGenerated") is True and rlz_bron.is_concept(doc):
            continue  # systeemhuls = open
        da = ankers.get(did or "")
        if da is None or da.is_huls:
            redenen.append(f"koppeling naar onbekend/niet-gemigreerd document {doc.get('ReceiptNumber') or did}")
            status = STATUS_NIET
            continue
        gekoppeld += pr_bedrag
        if da.move_type == "bank_direct":
            tegenregels.extend(da.tegenregels)
            # tegenzijde = het omgekeerde van de mutatie, verdeeld naar de omvang van de directe regels
            omvang = [abs(r.debet - r.credit) for r in da.tegen_balans]
            totaal = sum(omvang, NUL)
            for r, o in zip(da.tegen_balans, omvang, strict=True):
                deel = (abs(pr_bedrag) * o / totaal).quantize(Decimal("0.01")) if totaal else abs(pr_bedrag)
                regels.append(
                    BalansRegel(
                        r.rekening,
                        r.rlz_ledger_id,
                        deel if bedrag < 0 else NUL,
                        deel if bedrag >= 0 else NUL,
                        datum,
                        "tegenregel",
                    )
                )
            redenen.append(f"direct op grootboek via {da.boekstuk or did}")
        else:
            reconcile.append(
                {"anker": da.anker, "boekstuk": da.boekstuk, "move_type": da.move_type, "bedrag": pr_bedrag}
            )
            if da.bedrag is not None and abs(pr_bedrag) != abs(da.bedrag):
                deel = True
            if da.move_type in ("in_invoice", "in_refund"):
                tegen = (
                    str(ctx.doel.rekening_crediteuren_id) if ctx.doel.rekening_crediteuren_id else IMPLICIET_CREDITEUREN
                )
            elif da.move_type in ("out_invoice", "out_refund"):
                tegen = (
                    str(ctx.doel.rekening_debiteuren_id) if ctx.doel.rekening_debiteuren_id else IMPLICIET_DEBITEUREN
                )
            else:
                tegen = IMPLICIET_TUSSENREKENING
            # betaling van een inkoopfactuur (mutatie −) = crediteuren debet
            regels.append(
                BalansRegel(
                    tegen, None, -bedrag if bedrag < 0 else NUL, bedrag if bedrag >= 0 else NUL, datum, "tegenregel"
                )
            )
    if not expand_gelukt:
        redenen.append("PaymentReferenceList niet gelezen ($expand geweigerd) — koppelingen onbekend")
    rest = (bedrag - gekoppeld).quantize(Decimal("0.01")) if refs else bedrag
    if not reconcile and not tegenregels:
        regels.append(
            BalansRegel(
                IMPLICIET_TUSSENREKENING,
                None,
                -bedrag if bedrag < 0 else NUL,
                bedrag if bedrag >= 0 else NUL,
                datum,
                "tegenregel",
            )
        )
        if open_bedrag is not None and open_bedrag != 0:
            redenen.append(f"open € {open_bedrag} — geen koppeling, blijft op de tussenrekening")
    elif reconcile and (deel or len(reconcile) > 1 or abs(reconcile[0]["bedrag"]) != abs(bedrag)):
        redenen.append("deelkoppeling(en)")
    uit = Vertaald(
        move=MoveVoorstel(
            str(anker),
            rlz_id,
            boekstuk,
            "bank",
            datum,
            statement_line,
            {
                "rekening_rlz_id": rekening_id or None,
                "tegenregel": tegenregels or None,
                "reconcile": reconcile,
                "open_bedrag": open_bedrag,
                "restant_berekend": rest,
            },
            status,
            "; ".join(redenen) if redenen else "1-op-1 vertaald",
        ),
        regels=regels,
        bedrag=bedrag,
        open_bedrag=open_bedrag,
        pand=ctx.panden.get(uuid.UUID(rlz_id)) if _is_uuid(rlz_id) else None,  # blok 7b punt 5: één bron
    )
    return uit


def document_anker(ctx: Context, v: Vertaald) -> DocumentAnker:
    m = v.move
    tegenregels: tuple[dict[str, Any], ...] = ()
    tegen_balans: tuple[BalansRegel, ...] = ()
    if m.move_type == "bank_direct":
        tegenregels = tuple(rv for _, _, rv in m.vals.get("regels", []))
        tegen_balans = tuple(r for r in v.regels if r.bron == "regel")
    return DocumentAnker(m.anker, m.boekstuk, m.move_type, False, tegenregels, tegen_balans, v.bedrag)
