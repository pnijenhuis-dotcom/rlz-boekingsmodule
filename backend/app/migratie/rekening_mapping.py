"""Expliciete rekeningmapping RLZ → Odoo voor de VGG-migratie (run 2 blok 8, opdracht Peter 15-09 STAP 1).

De generieke vertaling (`app/odoo/rj220.py::vertaal_grootboek`: zelfde code / code + "00" / RGS-naam) kent GEEN plek
voor afletter-/tegenzijde-rekeningen die in Odoo geen eigen grootboekrekening zijn maar een dagboek-instelling. Deze
module is dáár de ene bron voor — een kleine, getoetste tabel per RLZ-code:

* **1012 "Betalingen onderweg" → Odoo "Outstanding Payments" van het bankdagboek (BNK1).** In Odoo 19 hangt die
  rekening aan `account.journal.outbound_payment_method_line_ids → payment_account_id`; is die leeg, dan aan de
  company-default (`res.company.account_journal_payment_credit_account_id`, als dat veld in deze Odoo-versie bestaat).
  Beide worden lees-only opgezocht (`los_outstanding_payments_op`); staat er niets ingesteld, dan blijft 1012
  ongemapt mét een leesbaar KLIKPUNT voor Peter — nooit gegokt, nooit de bankrekening zelf (dat zou het banksaldo
  dubbel voeden). Geen nieuwe RJ-220-rol: 1012 hoort in de groepstoets bij de bankgroep, net als 1001.
* **1001 (bankrekening) — SCHRIJF b (modelpunt nazorg 7d 14-09; GEBOUWD blok 9 16-09).** De bankrekening wordt in
  Odoo uitsluitend door statement lines gevoed; memoriaal-1001-regels die tegen een statement line reconciliëren horen
  op de outstanding-/suspense-rekening van het bankdagboek, anders telt 1001 dubbel (−85.376,31 per 31-12 / +71.343,31
  per 14-09). Sinds blok 9 (16-09) modelleert `app/migratie/model_1001.py` dat in de replay: gekoppelde regels →
  outstanding BNK1 (statement line reconcilieert ertegen), regels zonder/meerduidige mutatie → tussenrekening mét
  reden. De tabelregel blijft fase `b` (de bankrekening krijgt nooit een directe Odoo-mapping) en de groepstoets
  toont het model als regel.

Alles hier is deterministisch en lees-only; de enige Odoo-calls zijn `read`/`search_read`/`fields_get` op een
read-only client. Guard: `tests/migratie/test_rekening_mapping.py`.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from app.migratie.vertaling import GrootboekVertaling

logger = logging.getLogger(__name__)

#: Doel-soorten in de tabel.
DOEL_OUTSTANDING_PAYMENTS = "outstanding_payments"  # rekening uit het bankdagboek (payment method line) of company
DOEL_BANK_STATEMENT_LINES = "bank_statement_lines"  # de bankrekening zelf — alleen via statement lines (SCHRIJF b)

#: Schrijffase waarin de mapping actief wordt: "a" = nu (blok 8), "b" = open modelpunt (bewust nog niet gebouwd).
FASE_A = "a"
FASE_B = "b"

#: Bron-label op de `GrootboekVertaling` van een expliciet gemapte rekening.
BRON_EXPLICIET = "expliciet"


@dataclass(frozen=True)
class ExplicieteMapping:
    rlz_code: str
    doel: str
    groep: str
    schrijf_fase: str
    toelichting: str


#: DE tabel — één regel per RLZ-code. Uitbreiden = hier + test.
EXPLICIETE_MAPPING: dict[str, ExplicieteMapping] = {
    "1012": ExplicieteMapping(
        rlz_code="1012",
        doel=DOEL_OUTSTANDING_PAYMENTS,
        groep="bank",
        schrijf_fase=FASE_A,
        toelichting=(
            "Betalingen onderweg → Odoo 'Outstanding Payments' van het bankdagboek (afletter-/tegenzijde-rekening, "
            "geen RJ-220-rol); telt in de groepstoets bij de bankgroep"
        ),
    ),
    "1001": ExplicieteMapping(
        rlz_code="1001",
        doel=DOEL_BANK_STATEMENT_LINES,
        groep="bank",
        schrijf_fase=FASE_B,
        toelichting=(
            "bankrekening — in Odoo uitsluitend gevoed door statement lines; memoriaal-1001-regels die tegen een "
            "statement line reconciliëren → outstanding-/suspense-rekening van het bankdagboek (modelpunt SCHRIJF b, "
            "nazorg 7d 14-09: anders dubbeltelling −85.376,31 per 31-12-2025 / +71.343,31 per 14-09-2026); GEBOUWD "
            "blok 9 16-09 als 1001-model in de replay (sectie '1001-model' in het rapport): gekoppeld → outstanding, "
            "zonder/meerduidig → tussenrekening mét reden"
        ),
    ),
}


def expliciete_codes_voor_groep(groep: str) -> frozenset[str]:
    """RLZ-codes die de tabel aan een afletter-groep toewijst (ongeacht fase)."""
    return frozenset(m.rlz_code for m in EXPLICIETE_MAPPING.values() if m.groep == groep)


def modelpunten_voor_groep(groep: str) -> list[str]:
    """Leesbare SCHRIJF-b-markeringen voor de 'Stand / reden'-kolom van de groepstoets."""
    return [
        f"RLZ {m.rlz_code}: modelpunt SCHRIJF {m.schrijf_fase} — {m.toelichting}"
        for m in EXPLICIETE_MAPPING.values()
        if m.groep == groep and m.schrijf_fase != FASE_A
    ]


# ---- outstanding payments (lees-only) --------------------------------------------------------------------------------

ROUTE_JOURNAL = "account.journal.outbound_payment_method_line_ids.payment_account_id"
ROUTE_COMPANY = "res.company.account_journal_payment_credit_account_id"
COMPANY_VELD_OUTSTANDING_PAYMENTS = "account_journal_payment_credit_account_id"
#: Kandidaten die het rapport noemt als er niets ingesteld staat — nooit gekozen (mens beslist).
_KANDIDAAT_REGEX = re.compile(r"outstanding.*payment|betalingen onderweg|payments? in transit", re.I)


@dataclass(frozen=True)
class OutstandingUitkomst:
    account_id: int | None
    code: str | None
    naam: str | None
    route: str | None
    melding: str
    kandidaten: tuple[str, ...] = ()

    @property
    def gevonden(self) -> bool:
        return self.account_id is not None

    def als_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "code": self.code,
            "naam": self.naam,
            "route": self.route,
            "melding": self.melding,
            "kandidaten": list(self.kandidaten),
        }


def _m2o(waarde: Any) -> int | None:
    if isinstance(waarde, (list, tuple)) and waarde:
        return int(waarde[0])
    if isinstance(waarde, int) and not isinstance(waarde, bool):
        return int(waarde)
    return None


def _rekening_tekst(client: Any, account_id: int) -> tuple[str | None, str | None]:
    rij = client.read_een("account.account", int(account_id), ["code", "name"]) or {}
    code = rij.get("code")
    return (str(code) if code not in (None, False) else None), (str(rij.get("name")) if rij.get("name") else None)


def los_outstanding_payments_op(
    client: Any, *, journal_bank_id: int | None, company_id: int, rekeningen: list[dict[str, Any]] | None = None
) -> OutstandingUitkomst:
    """Lees-only: de 'Outstanding Payments'-rekening van het bankdagboek. Volgorde: (1) `payment_account_id` op de
    uitgaande betaalmethode-regels van het dagboek — precies één onderscheiden rekening = gevonden, meerdere = niet
    gekozen (meerduidig); (2) company-default `account_journal_payment_credit_account_id` als dat veld bestaat;
    (3) niets → KLIKPUNT mét naam-kandidaten uit het rekeningschema (alleen gemeld)."""
    if journal_bank_id is None:
        return OutstandingUitkomst(
            None, None, None, None, "geen bankdagboek in de doelkoppeling — outstanding-rekening niet op te zoeken"
        )
    # (1) betaalmethode-regels op het dagboek
    dagboek = (
        client.read_een("account.journal", int(journal_bank_id), ["code", "outbound_payment_method_line_ids"]) or {}
    )
    regel_ids = [int(x) for x in (dagboek.get("outbound_payment_method_line_ids") or []) if isinstance(x, int)]
    dagboek_code = dagboek.get("code") or journal_bank_id
    if regel_ids:
        regels = client.read("account.payment.method.line", regel_ids, ["name", "payment_account_id"])
        accounts = sorted({a for a in (_m2o(r.get("payment_account_id")) for r in regels) if a is not None})
        if len(accounts) == 1:
            code, naam = _rekening_tekst(client, accounts[0])
            return OutstandingUitkomst(
                accounts[0],
                code,
                naam,
                ROUTE_JOURNAL,
                f"gevonden op dagboek {dagboek_code}: {code or '?'} {naam or ''} (id {accounts[0]}) via "
                f"{ROUTE_JOURNAL} "
                f"({len(regels)} uitgaande betaalmethode-regel(s))",
            )
        if len(accounts) > 1:
            teksten = []
            for a in accounts:
                code, naam = _rekening_tekst(client, a)
                teksten.append(f"{code or '?'} {naam or ''} (id {a})")
            return OutstandingUitkomst(
                None,
                None,
                None,
                None,
                f"meerduidig: de uitgaande betaalmethode-regels van dagboek {dagboek_code} wijzen naar "
                f"{len(accounts)} verschillende outstanding-rekeningen ({'; '.join(teksten)}) — niet gekozen, "
                "mens beslist",
                tuple(teksten),
            )
    # (2) company-default, alleen als het veld in deze Odoo-versie bestaat
    velden = client.fields_get("res.company", ["type"]) or {}
    if COMPANY_VELD_OUTSTANDING_PAYMENTS in velden:
        bedrijf = client.read_een("res.company", int(company_id), [COMPANY_VELD_OUTSTANDING_PAYMENTS]) or {}
        account_id = _m2o(bedrijf.get(COMPANY_VELD_OUTSTANDING_PAYMENTS))
        if account_id is not None:
            code, naam = _rekening_tekst(client, account_id)
            return OutstandingUitkomst(
                account_id,
                code,
                naam,
                ROUTE_COMPANY,
                f"gevonden als company-default: {code or '?'} {naam or ''} (id {account_id}) via {ROUTE_COMPANY} "
                f"(dagboek {dagboek_code} heeft geen payment_account_id op zijn uitgaande betaalmethode-regels)",
            )
        company_tekst = "company-default leeg"
    else:
        company_tekst = f"veld {COMPANY_VELD_OUTSTANDING_PAYMENTS} bestaat niet in deze Odoo-versie"
    # (3) niets ingesteld → klikpunt, kandidaten alleen gemeld
    kandidaten = tuple(
        f"{r.get('code')} {r.get('name')} (id {r.get('id')})"
        for r in (rekeningen or [])
        if _KANDIDAAT_REGEX.search(str(r.get("name") or ""))
    )
    extra = f"; kandidaten in het rekeningschema (mens beslist): {'; '.join(kandidaten)}" if kandidaten else ""
    return OutstandingUitkomst(
        None,
        None,
        None,
        None,
        f"KLIKPUNT PETER: geen 'Outstanding Payments'-rekening ingesteld op dagboek {dagboek_code} "
        f"({len(regel_ids)} uitgaande betaalmethode-regel(s) zonder payment_account_id; {company_tekst}) — "
        f"instellen in Odoo (Boekhouding › Dagboek {dagboek_code} › Uitgaande betalingen › Outstanding-rekening); "
        f"RLZ 1012 blijft tot dan ongemapt{extra}",
        kandidaten,
    )


# ---- toepassen op de grootboekvertaling ----------------------------------------------------------------------------


def pas_expliciete_mapping_toe(
    grootboek: Mapping[str, GrootboekVertaling],
    ledgers: Mapping[str, tuple[str | None, str | None, int | None]],
    *,
    outstanding: OutstandingUitkomst | None,
) -> tuple[dict[str, GrootboekVertaling], list[dict[str, Any]]]:
    """Legt de tabel over de generieke vertaling: fase-a-regels krijgen hun Odoo-rekening (bron `expliciet`), fase-b-
    regels blijven zoals ze waren (alleen gemarkeerd). Geeft (nieuwe vertaling, rapportregels per tabelregel)."""
    uit = dict(grootboek)
    rapport: list[dict[str, Any]] = []
    for m in EXPLICIETE_MAPPING.values():
        ledger_ids = [lid for lid, (code, _n, _t) in ledgers.items() if code == m.rlz_code]
        rij: dict[str, Any] = {
            "rlz_code": m.rlz_code,
            "doel": m.doel,
            "groep": m.groep,
            "schrijf_fase": m.schrijf_fase,
            "toelichting": m.toelichting,
            "in_rlz": bool(ledger_ids),
            "odoo_account_id": None,
            "odoo_code": None,
            "stand": None,
        }
        if not ledger_ids:
            rij["stand"] = "RLZ-rekening niet in deze administratie"
        elif m.schrijf_fase != FASE_A:
            rij["stand"] = f"gemarkeerd (SCHRIJF {m.schrijf_fase}) — generieke vertaling ongewijzigd"
        elif m.doel == DOEL_OUTSTANDING_PAYMENTS:
            if outstanding is None:
                rij["stand"] = "niet opgezocht — geen Odoo-doelkoppeling gelezen"
            elif not outstanding.gevonden:
                rij["stand"] = outstanding.melding
            else:
                rij.update(
                    {
                        "odoo_account_id": outstanding.account_id,
                        "odoo_code": outstanding.code,
                        "stand": f"gemapt → {outstanding.code or '?'} {outstanding.naam or ''} ({outstanding.route})",
                    }
                )
                for lid in ledger_ids:
                    oud = uit.get(lid)
                    code, naam, _t = ledgers[lid]
                    uit[lid] = (
                        replace(
                            oud, odoo_account_id=outstanding.account_id, odoo_code=outstanding.code, bron=BRON_EXPLICIET
                        )
                        if oud is not None
                        else GrootboekVertaling(
                            rlz_ledger_id=lid,
                            rlz_code=code,
                            rlz_naam=naam,
                            odoo_account_id=outstanding.account_id,
                            odoo_code=outstanding.code,
                            bron=BRON_EXPLICIET,
                        )
                    )
        rapport.append(rij)
    return uit, rapport


# ---- voorgestelde tegenhanger per ongemapte rekening (rapport 1b) --------------------------------------------------

#: RLZ `AccountType` (1 opbrengst, 2 kosten, 3 activa, 4 passiva) → Odoo-type-voorstel voor een nog aan te maken
#: rekening.
_TYPE_VOORSTEL: dict[int, str] = {1: "income", 2: "expense", 3: "asset_current", 4: "liability_current"}


def _norm(naam: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (naam or "").casefold())


def voorstel_tegenhanger(
    rlz_code: str | None,
    rlz_naam: str | None,
    account_type: int | None,
    odoo_accounts: list[dict[str, Any]],
    *,
    outstanding: OutstandingUitkomst | None,
) -> str:
    """Deterministisch VOORSTEL (mens beslist) voor een RLZ-rekening zonder Odoo-tegenhanger: (1) een tabelregel →
    haar stand; (2) een Odoo-rekening met dezelfde genormaliseerde naam (klasse mag afwijken) → 'kandidaat …';
    (3) anders 'aanmaken als <code>00 (<type>)' mét de melding of die code al bezet is."""
    m = EXPLICIETE_MAPPING.get(rlz_code or "")
    if m is not None:
        if m.schrijf_fase != FASE_A:
            return f"modelpunt SCHRIJF {m.schrijf_fase} — {m.toelichting}"
        if outstanding is None:
            return "outstanding-rekening niet opgezocht (geen doelkoppeling gelezen)"
        return outstanding.melding
    per_code = {str(a.get("code") or "").strip(): a for a in odoo_accounts if a.get("code")}
    naam_norm = _norm(rlz_naam)
    if naam_norm:
        kandidaten = [a for a in odoo_accounts if _norm(str(a.get("name") or "")) == naam_norm]
        if len(kandidaten) == 1:
            k = kandidaten[0]
            return (
                f"kandidaat {k.get('code')} {k.get('name')} (id {k.get('id')}) — naam gelijk, klasse anders; "
                "mens beslist"
            )
        if len(kandidaten) > 1:
            return (
                f"{len(kandidaten)} naamkandidaten ({', '.join(str(k.get('code')) for k in kandidaten)}) — mens beslist"
            )
    if not rlz_code:
        return "geen RLZ-code — handmatig"
    voorstel_code = f"{rlz_code}00"
    type_voorstel = _TYPE_VOORSTEL.get(int(account_type) if account_type is not None else -1, "onbekend type")
    if rlz_code[:1] == "0" and account_type == 3:
        type_voorstel = "asset_fixed"
    elif rlz_code[:1] == "0" and account_type == 4:
        type_voorstel = "equity of liability_non_current (mens kiest)"
    bezet = per_code.get(voorstel_code)
    if bezet is not None:
        return (
            f"aanmaken als {voorstel_code} ({type_voorstel}) NIET mogelijk — code bezet door "
            f"{bezet.get('name')} (id {bezet.get('id')}, {bezet.get('account_type') or 'type ?'}); mens kiest een code"
        )
    return f"aanmaken als {voorstel_code} '{rlz_naam or rlz_code}' ({type_voorstel}) — code vrij; mens bevestigt"


# ---- Odoo-doelgegevens lezen (rekeningen + outstanding) via de doelkoppeling ----------------------------------------


@dataclass(frozen=True)
class DoelGegevens:
    odoo_accounts: list[dict[str, Any]] = field(default_factory=list)
    outstanding: OutstandingUitkomst | None = None
    melding: str | None = None  # None = gelezen; anders de leesbare reden waarom niet


OdooLezer = Callable[[uuid.UUID, int | None, int | None], DoelGegevens]


def lees_doelgegevens(administratie_id: uuid.UUID, journal_bank_id: int | None, company_id: int | None) -> DoelGegevens:
    """Lees-only via de doelkoppeling (`odoo_doel.doelclient_voor(read_only=True)`): alle `account.account` van de
    doelcompany + de outstanding-payments-rekening. Elke fout = leesbare melding, nooit een crash van de replay."""
    from app.migratie.odoo_doel import GeenMigratieDoel, doelclient_voor  # noqa: PLC0415
    from app.odoo.rj220 import lees_rekeningen  # noqa: PLC0415

    if company_id is None:
        return DoelGegevens(melding="geen company in de doelkoppeling — Odoo-rekeningen niet gelezen")
    try:
        client = doelclient_voor(administratie_id, read_only=True)
    except GeenMigratieDoel as exc:
        return DoelGegevens(melding=f"Odoo-rekeningen niet gelezen: {exc}")
    except Exception as exc:  # noqa: BLE001 — credential-store/KMS: zichtbaar
        return DoelGegevens(melding=f"Odoo-rekeningen niet gelezen: {type(exc).__name__}: {exc}")
    try:
        rekeningen = lees_rekeningen(client, company_id=int(company_id))
        outstanding = los_outstanding_payments_op(
            client, journal_bank_id=journal_bank_id, company_id=int(company_id), rekeningen=rekeningen
        )
        return DoelGegevens(odoo_accounts=rekeningen, outstanding=outstanding)
    except Exception as exc:  # noqa: BLE001 — Odoo-fout: zichtbaar, replay loopt door zonder mapping
        logger.warning("Odoo-doelgegevens niet gelezen voor %s: %s", administratie_id, exc)
        return DoelGegevens(melding=f"Odoo-rekeningen niet gelezen: {type(exc).__name__}: {exc}")
    finally:
        if hasattr(client, "close"):
            client.close()
